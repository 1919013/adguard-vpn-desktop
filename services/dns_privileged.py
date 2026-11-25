"""Privileged temporary NetworkManager DNS override with recovery.

Only active physical Ethernet/Wi-Fi devices are touched. Connection profiles
are never modified. Runtime overrides are reverted with `nmcli device reapply`
only when the same active connection UUID is still attached to that device.
"""
from __future__ import annotations

import fcntl
import ipaddress
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Callable

STATE_DIR = Path("/var/lib/adguard-vpn-desktop")
STATE_FILE = STATE_DIR / "dns-runtime.json"
OWNER = "adguard-vpn-desktop-dns"
PHYSICAL_TYPES = {"ethernet", "wifi", "wireless"}
DEFAULT_DNS = ("46.243.231.30", "46.243.231.31")


class DNSHelperError(RuntimeError):
    """A temporary DNS operation could not be completed safely."""


def _default_runner(argv, *, input_text=None, timeout=12):
    try:
        result = subprocess.run(
            argv, input=input_text, text=True, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, timeout=timeout, check=False,
        )
        return int(result.returncode), (result.stdout or "").strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)


def _unescape(value: str) -> str:
    return value.replace(r"\:", ":").replace(r"\\", "\\")


class TemporaryDNSHelper:
    """Root-only runtime DNS override; no persistent NM profile mutations."""

    def __init__(self, *, state_file=STATE_FILE, runner=_default_runner,
                 euid=os.geteuid, uid=os.getuid, which=shutil.which,
                 sleep=time.sleep, manage_guard=True):
        self.state_file = Path(state_file)
        self.runner = runner
        self.euid = euid
        self.uid = uid
        self.which = which
        self.sleep = sleep
        self.manage_guard = manage_guard
        self.lock_file = self.state_file.with_suffix(".lock")

    def _run(self, argv, *, timeout=12):
        code, output = self.runner(argv, timeout=timeout)
        if code:
            raise DNSHelperError(output or f"Команда {argv[0]} завершилась с кодом {code}.")
        return output

    def _require_root(self):
        if self.euid() != 0:
            raise DNSHelperError("DNS-helper должен выполняться через Polkit с правами root.")

    def _locked(self):
        self.state_file.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        directory = self.state_file.parent.lstat()
        if (not stat.S_ISDIR(directory.st_mode) or stat.S_ISLNK(directory.st_mode)
                or directory.st_uid != self.uid()):
            raise DNSHelperError("Каталог системного состояния DNS имеет небезопасный тип или владельца.")
        os.chmod(self.state_file.parent, 0o700)
        flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(self.lock_file, flags, 0o600)
        try:
            metadata = os.fstat(fd)
            if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != self.uid()):
                raise DNSHelperError("Файл блокировки DNS имеет небезопасный тип или владельца.")
            os.fchmod(fd, 0o600)
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            os.close(fd)
            raise DNSHelperError("Уже выполняется операция временной настройки DNS.") from exc
        except Exception:
            os.close(fd)
            raise
        return fd

    def _write_state(self, state):
        directory = self.state_file.parent
        info = directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_uid != self.uid():
            raise DNSHelperError("Небезопасный каталог системного состояния DNS.")
        fd, temporary = tempfile.mkstemp(prefix=".dns-runtime-", dir=directory)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(state, stream, ensure_ascii=False, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.state_file)
            os.chmod(self.state_file, 0o600)
            dirfd = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(dirfd)
            finally:
                os.close(dirfd)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass

    def _read_state(self):
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(self.state_file, flags)
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise DNSHelperError(f"Не удалось безопасно открыть файл состояния DNS: {exc}") from exc
        try:
            metadata = os.fstat(fd)
            if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != self.uid()
                    or stat.S_IMODE(metadata.st_mode) != 0o600):
                raise DNSHelperError("Файл состояния DNS имеет небезопасного владельца, тип или права.")
            with os.fdopen(fd, "r", encoding="utf-8") as stream:
                fd = -1
                state = json.load(stream)
        except (OSError, json.JSONDecodeError) as exc:
            raise DNSHelperError(f"Файл состояния DNS повреждён: {exc}") from exc
        finally:
            if fd >= 0:
                os.close(fd)
        if (not isinstance(state, dict) or state.get("owner") != OWNER
                or state.get("version") != 1
                or not isinstance(state.get("devices"), list)):
            raise DNSHelperError("Формат или владелец состояния DNS не распознан.")
        for item in state["devices"]:
            if (not isinstance(item, dict)
                    or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,15}", str(item.get("ifname", "")))
                    or not re.fullmatch(r"[0-9a-fA-F-]{36}", str(item.get("uuid", "")))
                    or not isinstance(item.get("original_dns"), list)
                    or not isinstance(item.get("applied_dns"), list)):
                raise DNSHelperError("Состояние DNS содержит недопустимое устройство.")
            try:
                for address in item["original_dns"] + item["applied_dns"]:
                    ipaddress.ip_address(address)
            except (TypeError, ValueError) as exc:
                raise DNSHelperError("Состояние DNS содержит некорректный исходный DNS.") from exc
        return state

    def _device_records(self):
        output = self._run([
            "nmcli", "--colors", "no", "--terse", "--escape", "yes",
            "--fields", "GENERAL.DEVICE,GENERAL.TYPE,GENERAL.STATE,GENERAL.CON-UUID",
            "device", "show",
        ])
        records = {}
        current = None
        for line in output.splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            key, value = key.strip(), _unescape(value.strip())
            if key == "GENERAL.DEVICE":
                current = value
                records.setdefault(current, {"ifname": current})
            elif current is not None and key.startswith("GENERAL."):
                records[current][key.split(".", 1)[1].lower()] = value
        devices = []
        for item in records.values():
            if (str(item.get("type", "")).casefold() in PHYSICAL_TYPES
                    and str(item.get("state", "")).startswith("100")
                    and re.fullmatch(r"[0-9a-fA-F-]{36}", str(item.get("con-uuid", "")))):
                devices.append(item)
        return sorted(devices, key=lambda item: item["ifname"])

    def _vpn_connected(self, tunnel):
        code, output = self.runner(["adguardvpn-cli", "status"], timeout=10)
        clean = re.sub(r"\x1b\[[0-9;]*m", "", output or "")
        return code == 0 and "Connected to " in clean and re.search(
            rf"running on\s+{re.escape(tunnel)}\b", clean, re.IGNORECASE
        ) is not None

    def _validate_dns_routes(self, tunnel, servers):
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,15}", tunnel):
            raise DNSHelperError("Недопустимое имя TUN-интерфейса.")
        for server in servers:
            address = ipaddress.ip_address(server)
            family = "-6" if address.version == 6 else "-4"
            output = self._run(["ip", "-j", family, "route", "get", str(address)])
            try:
                routes = json.loads(output)
            except json.JSONDecodeError as exc:
                raise DNSHelperError(f"Не удалось разобрать маршрут к DNS {server}.") from exc
            if not isinstance(routes, list) or not routes or any(
                not isinstance(route, dict) or route.get("dev") != tunnel
                for route in routes
            ):
                raise DNSHelperError(f"Маршрут DNS-сервера {server} не подтверждён через {tunnel}.")

    def _effective_dns(self, ifname):
        output = self._run([
            "nmcli", "--colors", "no", "--terse",
            "--fields", "IP4.DNS,IP6.DNS", "device", "show", ifname,
        ])
        addresses = []
        for line in output.splitlines():
            value = line.split(":", 1)[-1].strip()
            try:
                addresses.append(str(ipaddress.ip_address(value)))
            except ValueError:
                continue
        return sorted(set(addresses))

    def _current_uuid(self, ifname):
        output = self._run([
            "nmcli", "--colors", "no", "--terse", "--escape", "yes",
            "--fields", "GENERAL.DEVICE,GENERAL.CON-UUID", "device", "show", ifname,
        ])
        for line in output.splitlines():
            if line.startswith("GENERAL.CON-UUID:"):
                return _unescape(line.split(":", 1)[1].strip())
        return None

    def _reapply(self, item):
        ifname, uuid = item["ifname"], item["uuid"]
        if self._current_uuid(ifname) != uuid:
            actual = self._effective_dns(ifname)
            if sorted(set(actual)) == sorted(set(item["applied_dns"])):
                raise DNSHelperError(
                    f"Подключение на {ifname} сменилось, но временный DNS override всё ещё виден. "
                    "Устройство не изменялось; состояние сохранено для повторного восстановления."
                )
            return "skipped-connection-changed"
        self._run(["nmcli", "device", "reapply", ifname], timeout=30)
        actual = self._effective_dns(ifname)
        expected = sorted(set(item["original_dns"]))
        if actual != expected:
            raise DNSHelperError(
                f"DNS на {ifname} после reapply не совпадает с исходным состоянием: "
                f"ожидалось {expected}, получено {actual}."
            )
        return "restored-and-verified"

    def apply(self, tunnel, dns_servers=DEFAULT_DNS):
        self._require_root()
        try:
            servers = tuple(sorted({str(ipaddress.ip_address(x)) for x in dns_servers}))
        except (TypeError, ValueError) as exc:
            raise DNSHelperError("Список DNS содержит недопустимый IP-адрес.") from exc
        if not servers:
            raise DNSHelperError("Не указан ни один DNS upstream.")
        lock = self._locked()
        try:
            if self._read_state() is not None:
                raise DNSHelperError("Временная DNS-настройка уже активна; сначала восстановите её.")
            if not self._vpn_connected(tunnel):
                raise DNSHelperError("AdGuard VPN не подтвердил активный TUN; DNS не изменён.")
            self._validate_dns_routes(tunnel, servers)
            devices = self._device_records()
            if not devices:
                raise DNSHelperError("Не обнаружено активных физических Ethernet/Wi-Fi подключений.")
            state = {
                "owner": OWNER, "version": 1, "tunnel": tunnel,
                "dns_servers": list(servers),
                "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip(),
                "devices": [
                    {
                        "ifname": x["ifname"],
                        "uuid": x["con-uuid"],
                        "original_dns": self._effective_dns(x["ifname"]),
                        "applied_dns": list(servers),
                    }
                    for x in devices
                ],
            }
            self._write_state(state)
            attempted = []
            try:
                for item in state["devices"]:
                    ifname = item["ifname"]
                    if self._current_uuid(ifname) != item["uuid"]:
                        raise DNSHelperError(f"Подключение {ifname} сменилось во время настройки DNS.")
                    attempted.append(item)
                    ipv4_servers = [server for server in servers if ipaddress.ip_address(server).version == 4]
                    ipv6_servers = [server for server in servers if ipaddress.ip_address(server).version == 6]
                    args = ["nmcli", "device", "modify", ifname,
                            "ipv4.dns", " ".join(ipv4_servers),
                            "ipv4.ignore-auto-dns", "yes",
                            "ipv6.dns", " ".join(ipv6_servers),
                            "ipv6.ignore-auto-dns", "yes"]
                    self._run(args, timeout=30)
                    current = self._run([
                        "nmcli", "--colors", "no", "--terse",
                        "--fields", "IP4.DNS,IP6.DNS", "device", "show", ifname,
                    ])
                    actual = set()
                    for raw in current.splitlines():
                        value = raw.split(":", 1)[-1].strip()
                        try:
                            actual.add(str(ipaddress.ip_address(value)))
                        except ValueError:
                            continue
                    if actual != set(servers):
                        raise DNSHelperError(
                            f"Проверка активного DNS на {ifname} не пройдена: "
                            f"ожидались {', '.join(servers)}, получены {', '.join(sorted(actual)) or 'нет серверов'}."
                        )
                if self.manage_guard:
                    self._run(
                        ["systemctl", "start", "adguard-vpn-desktop-dns-guard.service"],
                        timeout=30,
                    )
                    active = self._run(
                        ["systemctl", "is-active", "adguard-vpn-desktop-dns-guard.service"],
                        timeout=10,
                    )
                    if active.strip() != "active":
                        raise DNSHelperError("Служба аварийного восстановления DNS не запустилась.")
            except Exception as exc:
                rollback_errors = []
                if self.manage_guard:
                    self.runner(["systemctl", "stop", "adguard-vpn-desktop-dns-guard.service"], timeout=20)
                for item in reversed(attempted):
                    try:
                        self._reapply(item)
                    except Exception as rollback_exc:
                        rollback_errors.append(f"{item['ifname']}: {rollback_exc}")
                if rollback_errors:
                    raise DNSHelperError(
                        f"Настройка DNS не завершена: {exc}. Откат требует восстановления: "
                        + "; ".join(rollback_errors)
                    ) from exc
                self.state_file.unlink(missing_ok=True)
                raise DNSHelperError(f"Настройка DNS отменена; исходные профили повторно применены: {exc}") from exc
            return {"active": True, "tunnel": tunnel, "devices": state["devices"], "dns_servers": list(servers)}
        finally:
            os.close(lock)

    def restore(self, *, stop_guard=False):
        self._require_root()
        lock = self._locked()
        try:
            state = self._read_state()
            if state is None:
                return {"restored": False, "detail": "no-active-override"}
            results, errors = [], []
            for item in reversed(state["devices"]):
                try:
                    results.append({
                        "ifname": item["ifname"],
                        "result": self._reapply(item),
                    })
                except Exception as exc:
                    errors.append(f"{item['ifname']}: {exc}")
            if errors:
                raise DNSHelperError(
                    "Не все временные DNS-настройки удалось восстановить; состояние сохранено: "
                    + "; ".join(errors)
                )
            self.state_file.unlink(missing_ok=True)
            if stop_guard and self.manage_guard:
                code, output = self.runner(
                    ["systemctl", "stop", "adguard-vpn-desktop-dns-guard.service"],
                    timeout=20,
                )
                if code not in (0, 5):
                    raise DNSHelperError(
                        "DNS восстановлен, но служба наблюдения не остановлена: " + (output or str(code))
                    )
            return {"restored": True, "devices": results}
        finally:
            os.close(lock)

    def watch(self, interval=4):
        """System service loop; restores runtime DNS after VPN loss or SIGTERM."""
        self._require_root()
        try:
            while True:
                state = self._read_state()
                if state is None:
                    self.sleep(interval)
                    continue
                tunnel = state.get("tunnel")
                try:
                    current_boot = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
                except OSError:
                    current_boot = None
                if (state.get("boot_id") != current_boot
                        or not isinstance(tunnel, str) or not self._vpn_connected(tunnel)):
                    self.restore()
                self.sleep(interval)
        finally:
            try:
                self.restore()
            except Exception:
                # Keep the state file for explicit recovery on next service start.
                pass


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description="Temporary DNS helper")
    sub = parser.add_subparsers(dest="operation", required=True)
    apply_parser = sub.add_parser("apply")
    apply_parser.add_argument("--tunnel", required=True)
    apply_parser.add_argument("--dns-server", action="append", required=True)
    sub.add_parser("restore")
    sub.add_parser("watch")
    args = parser.parse_args(argv)
    helper = TemporaryDNSHelper()
    try:
        if args.operation == "apply":
            result = helper.apply(args.tunnel, args.dns_server)
        elif args.operation == "restore":
            result = helper.restore(stop_guard=True)
        else:
            helper.watch()
            return 0
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except DNSHelperError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
