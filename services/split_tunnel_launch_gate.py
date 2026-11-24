"""Fail-closed launch coordinator for per-application VPN routing.

The target process is not executed until its systemd scope is visible in cgroup
v2 and the caller has applied AND independently verified the routing policy.
This module is deliberately not wired into the GUI or polkit yet.
"""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable, Sequence

from services.process_split_tunnel import (
    SplitTunnelError, _safe_unit_name, read_process_cgroup,
)

class LaunchGateError(RuntimeError):
    """The application could not be launched without risking a VPN bypass."""


def _apply_verify_release(cgroup: str, apply_rules: Callable,
                          verify_rules: Callable, release: Callable,
                          abort: Callable) -> None:
    """Enforce the security ordering; a failed gate is never released."""
    try:
        apply_rules(cgroup)
        if verify_rules(cgroup) is not True:
            raise LaunchGateError("Правила nftables/ip rule не прошли независимую проверку.")
        release()
    except Exception:
        try:
            abort()
        finally:
            raise


class SplitTunnelLaunchGate:
    """Run an application in its own gated scope under one shared policy slice.

    apply_rules(cgroup) must install rules through the narrow privileged
    helper. verify_rules(cgroup) must inspect live nftables and ip rules and
    return True only when both exact objects are active. remove_rules() must
    remove only helper-owned state. No arbitrary shell is ever used.
    """

    def __init__(self, *, runtime_dir: Path | None = None,
                 popen: Callable = subprocess.Popen,
                 cgroup_reader: Callable = read_process_cgroup,
                 scope_stopper: Callable | None = None,
                 poll_interval: float = 0.1):
        self.runtime_dir = Path(runtime_dir or os.environ.get("XDG_RUNTIME_DIR", ""))
        self.popen = popen
        self.cgroup_reader = cgroup_reader
        self.scope_stopper = scope_stopper or self._stop_scope
        self.poll_interval = poll_interval
        self._lock = threading.Lock()

    @staticmethod
    def _stop_scope(unit: str) -> None:
        subprocess.run(
            ["systemctl", "--user", "stop", unit],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, timeout=10, check=False,
        )

    def _secure_runtime_dir(self) -> Path:
        if not str(self.runtime_dir) or not self.runtime_dir.is_absolute():
            raise LaunchGateError("Не задан абсолютный XDG_RUNTIME_DIR.")
        base = self.runtime_dir
        try:
            info = base.lstat()
        except OSError as exc:
            raise LaunchGateError(f"Недоступен XDG_RUNTIME_DIR: {exc}") from exc
        if not base.is_dir() or base.is_symlink() or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise LaunchGateError("XDG_RUNTIME_DIR должен быть каталогом текущего пользователя.")
        target = base / "adguard-vpn-desktop"
        target.mkdir(mode=0o700, exist_ok=True)
        info = target.lstat()
        if target.is_symlink() or not target.is_dir() or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise LaunchGateError("Каталог блокировки запуска имеет небезопасные права.")
        return target

    def run(self, command: Sequence[str], app_id: str, *,
            apply_rules: Callable[[str], None],
            verify_rules: Callable[[str], bool],
            remove_rules: Callable[[], None],
            cancel_event=None, handshake_timeout: float = 15.0) -> int:
        if isinstance(command, (str, bytes)) or not command:
            raise LaunchGateError("Команда приложения пуста или задана строкой.")
        if not all(isinstance(arg, str) and arg for arg in command):
            raise LaunchGateError("Команда приложения содержит пустой аргумент.")
        if cancel_event is None:
            raise LaunchGateError("Нельзя запускать приложение без наблюдателя отключения VPN.")
        if not self._lock.acquire(blocking=False):
            raise LaunchGateError("Этот экземпляр запуска уже занят.")
        unit = _safe_unit_name(app_id)
        listener = None
        connection = None
        process = None
        applied = False
        released = False
        socket_path = None
        try:
            directory = self._secure_runtime_dir()
            # Unix socket paths are limited on Linux; keep the generated name short.
            fd, name = tempfile.mkstemp(prefix="g-", dir=directory)
            os.close(fd)
            os.unlink(name)
            socket_path = Path(name)
            listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            listener.bind(str(socket_path))
            os.chmod(socket_path, 0o600)
            listener.listen(1)
            listener.settimeout(self.poll_interval)

            worker = [
                shutil.which("python3") or "python3", "-m",
                "services.split_tunnel_gate_worker", "--socket",
                str(socket_path), "--", *command,
            ]
            argv = [
                "systemd-run", "--user", "--scope", "--wait", "--collect",
                "--unit", unit, "--slice", "app-adguard-vpn.slice", "--", *worker,
            ]
            process = self.popen(
                argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, close_fds=True,
            )
            deadline = time.monotonic() + handshake_timeout
            while connection is None:
                if cancel_event is not None and cancel_event.is_set():
                    raise LaunchGateError("Запуск отменён до установки маршрутизации.")
                if process.poll() is not None:
                    raise LaunchGateError("Процесс блокировки завершился до подтверждения готовности.")
                if time.monotonic() >= deadline:
                    raise LaunchGateError("Истекло время ожидания процесса в cgroup.")
                try:
                    connection, _ = listener.accept()
                except socket.timeout:
                    continue

            stream = connection.makefile("rwb", buffering=0)
            line = stream.readline(128)
            try:
                import json
                message = json.loads(line.decode("utf-8"))
                pid = message.get("pid") if isinstance(message, dict) else None
            except (ValueError, UnicodeDecodeError):
                pid = None
            if not isinstance(pid, int) or pid <= 0:
                raise LaunchGateError("Процесс блокировки передал некорректный PID.")
            cgroup = self.cgroup_reader(pid)
            if not cgroup.endswith("/app-adguard-vpn.slice/" + unit):
                raise LaunchGateError(
                    "Процесс приложения оказался вне общей app-adguard-vpn.slice."
                )
            policy_cgroup = cgroup.rsplit("/", 1)[0]
            if not policy_cgroup.endswith("/app.slice/app-adguard-vpn.slice"):
                raise LaunchGateError("Не удалось подтвердить родительскую cgroup общей сессии.")

            def release():
                nonlocal released
                stream.write(b"GO\n")
                released = True

            def abort():
                stream.write(b"ABORT\n")

            # Mark that cleanup is required before attempting the transaction:
            # a privileged helper may fail after a partial kernel change.
            applied = True
            _apply_verify_release(policy_cgroup, apply_rules, verify_rules, release, abort)
            stream.close()
            connection.close()
            connection = None

            while process.poll() is None:
                if cancel_event is not None and cancel_event.is_set():
                    self.scope_stopper(unit)
                    try:
                        process.terminate()
                    except OSError:
                        pass
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
                    raise LaunchGateError("VPN отключён: приложение остановлено и маршрутизация очищается.")
                time.sleep(self.poll_interval)
            return int(process.returncode or 0)
        except LaunchGateError:
            raise
        except Exception as exc:
            raise LaunchGateError(f"Безопасный запуск приложения прерван: {exc}") from exc
        finally:
            cleanup_error = None
            try:
                if process is not None and process.poll() is None:
                    try:
                        self.scope_stopper(unit)
                    except Exception:
                        pass
                    try:
                        process.terminate()
                    except Exception:
                        pass
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        try:
                            process.kill()
                            process.wait(timeout=5)
                        except Exception:
                            pass
                if applied:
                    try:
                        remove_rules()
                    except Exception as exc:
                        cleanup_error = exc
            finally:
                try:
                    if connection is not None:
                        try:
                            connection.close()
                        except OSError:
                            pass
                    if listener is not None:
                        try:
                            listener.close()
                        except OSError:
                            pass
                    if socket_path is not None:
                        try:
                            socket_path.unlink()
                        except OSError:
                            pass
                finally:
                    self._lock.release()
            if cleanup_error is not None:
                raise LaunchGateError(
                    f"Не удалось очистить правила маршрутизации: {cleanup_error}"
                ) from cleanup_error
