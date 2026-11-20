"""Safe NetworkManager DNS management for AdGuard VPN Desktop.

This module never changes production profiles.  The default allowlist contains
only the two legacy test profiles from the original DNS manager.  Add a new
test profile only after reviewing it explicitly.
"""
from __future__ import annotations

import datetime
import fcntl
import json
import os
import re
import stat
import subprocess
from pathlib import Path
from typing import Callable, Iterable

ADGUARD_DNS = ("46.243.231.30", "46.243.231.31")
TEST_PROFILES = ("vpn-desktop-test-wired", "vpn-desktop-test-wireless")
BACKUP_FIELDS = (
    "ipv4.method", "ipv4.dns", "ipv4.dns-search", "ipv4.dns-options",
    "ipv4.dns-priority", "ipv4.ignore-auto-dns", "ipv4.route-metric",
    "ipv6.method", "ipv6.dns", "ipv6.dns-search", "ipv6.dns-options",
    "ipv6.dns-priority", "ipv6.ignore-auto-dns", "ipv6.route-metric",
)
RESTORE_FIELDS = (
    "ipv4.dns", "ipv4.dns-search", "ipv4.dns-options",
    "ipv4.dns-priority", "ipv4.ignore-auto-dns",
    "ipv6.dns", "ipv6.dns-search", "ipv6.dns-options",
    "ipv6.dns-priority", "ipv6.ignore-auto-dns",
)


class DNSManagerError(RuntimeError):
    """Raised when a DNS operation cannot be completed safely."""


def _default_runner(command: list[str], timeout: int = 15) -> tuple[int, str]:
    try:
        result = subprocess.run(
            command, text=True, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, timeout=timeout, check=False,
        )
        return result.returncode, result.stdout.strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)


class DNSManager:
    """Transactional DNS manager restricted to explicitly allowed test profiles."""

    def __init__(
        self,
        *,
        profiles: Iterable[str] = TEST_PROFILES,
        state_dir: str | os.PathLike | None = None,
        runner: Callable = _default_runner,
    ):
        self.profiles = tuple(profiles)
        if not self.profiles or len(set(self.profiles)) != len(self.profiles):
            raise ValueError("A non-empty, unique profile allowlist is required")
        if any(not isinstance(p, str) or not p for p in self.profiles):
            raise ValueError("Invalid NetworkManager profile name")
        # Do not permit callers to broaden the allowlist to production profiles.
        if not set(self.profiles).issubset(TEST_PROFILES):
            raise ValueError("Only the built-in test profiles are permitted")
        self.state_dir = Path(
            state_dir or Path.home() / ".local/state/adguard-vpn-desktop"
        )
        self.backup_file = self.state_dir / "dns-backup-test-v2.json"
        self.lock_file = self.state_dir / "dns-manager.lock"
        self.runner = runner

    def _run(self, command: list[str]) -> tuple[int, str]:
        return self.runner(command)

    def vpn_status(self) -> tuple[bool, str]:
        code, output = self._run(["adguardvpn-cli", "status"])
        clean = re.sub(r"\x1b\[[0-9;]*m", "", output)
        # The CLI may assign tun0, tun1, etc.; do not assume a fixed
        # interface number when confirming TUN mode.
        running_tun = re.search(
            r"(?:VPN is )?running on ([A-Za-z0-9_.:-]+)", clean, re.IGNORECASE
        )
        connected = code == 0 and "Connected to " in clean and bool(running_tun)
        return connected, clean

    def active_profiles(self) -> dict[str, str]:
        code, output = self._run([
            "nmcli", "--colors", "no", "--terse", "--fields", "NAME,DEVICE",
            "connection", "show", "--active",
        ])
        if code:
            raise DNSManagerError(f"Cannot read active connections: {output}")
        active = {}
        for line in output.splitlines():
            if not line:
                continue
            fields = self._split_nmcli_fields(line, 2)
            if len(fields) == 2:
                name, device = fields
                active[name] = device
        return active

    def _read_settings(self, profile: str, fields=BACKUP_FIELDS) -> dict[str, str]:
        if profile not in self.profiles:
            raise DNSManagerError(f"Profile is not allowlisted: {profile}")
        code, output = self._run([
            "nmcli", "--colors", "no", "--terse",
            "--fields", ",".join(fields), "connection", "show", "id", profile,
        ])
        if code:
            raise DNSManagerError(f"Cannot read profile {profile}: {output}")
        settings = {}
        for line in output.splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                settings[key] = value
        missing = set(fields) - set(settings)
        if missing:
            raise DNSManagerError(
                f"Missing settings for {profile}: {', '.join(sorted(missing))}"
            )
        return settings

    @staticmethod
    def _split_nmcli_fields(line: str, expected: int) -> list[str]:
        """Split nmcli terse output while respecting escaped separators."""
        fields = []
        current = []
        escaped = False
        for char in line:
            if escaped:
                current.append(char)
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == ":" and len(fields) < expected - 1:
                fields.append("".join(current))
                current = []
            else:
                current.append(char)
        if escaped:
            current.append("\\")
        fields.append("".join(current))
        return fields

    def discover_profiles(self) -> list[dict[str, str | bool]]:
        """Discover ordinary wired/Wi-Fi NetworkManager profiles (read-only)."""
        code, output = self._run([
            "nmcli", "--colors", "no", "--terse",
            "--fields", "NAME,UUID,TYPE,DEVICE",
            "connection", "show",
        ])
        if code:
            raise DNSManagerError(f"Cannot discover NetworkManager profiles: {output}")
        active = self.active_profiles()
        allowed_types = {"802-3-ethernet", "802-11-wireless", "ethernet", "wifi"}
        discovered = []
        for line in output.splitlines():
            if not line:
                continue
            fields = self._split_nmcli_fields(line, 4)
            if len(fields) != 4:
                continue
            name, uuid, kind, device = fields
            if kind not in allowed_types:
                continue
            discovered.append({
                "name": name,
                "uuid": uuid,
                "type": kind,
                "device": device if device and device != "--" else "",
                "active": name in active,
            })
        return discovered

    def network_interfaces(self) -> list[dict[str, str]]:
        """Return current physical NetworkManager device states without changing them."""
        code, output = self._run([
            "nmcli", "--colors", "no", "--terse",
            "--fields", "DEVICE,TYPE,STATE,CONNECTION",
            "device", "status",
        ])
        if code:
            raise DNSManagerError(f"Cannot inspect network interfaces: {output}")
        interfaces = []
        for line in output.splitlines():
            if not line:
                continue
            fields = self._split_nmcli_fields(line, 4)
            if len(fields) != 4:
                continue
            device, kind, state, connection = fields
            if kind in {"loopback", "tun", "wireguard", "bridge"}:
                continue
            interfaces.append({
                "device": device,
                "type": kind,
                "state": state,
                "connection": connection if connection != "--" else "",
            })
        return interfaces

    def status(self) -> dict:
        connected, vpn_output = self.vpn_status()
        active = self.active_profiles()
        profiles = {}
        for profile in self.profiles:
            try:
                profiles[profile] = {
                    "active_device": active.get(profile),
                    "settings": self._read_settings(profile),
                }
            except DNSManagerError as exc:
                profiles[profile] = {"error": str(exc)}
        try:
            discovered_profiles = self.discover_profiles()
        except DNSManagerError as exc:
            discovered_profiles = {"error": str(exc)}
        try:
            interfaces = self.network_interfaces()
        except DNSManagerError as exc:
            interfaces = {"error": str(exc)}
        return {
            "vpn_connected_tun": connected,
            "vpn_output": vpn_output,
            "profiles": profiles,
            "discovered_profiles": discovered_profiles,
            "network_interfaces": interfaces,
        }

    def dry_run(self) -> dict:
        connected, output = self.vpn_status()
        active = self.active_profiles()
        return {
            "vpn_connected_tun": connected,
            "vpn_output": output,
            "profiles": {
                p: {
                    "active_device": active.get(p),
                    "planned_dns": list(ADGUARD_DNS) if p in active else None,
                }
                for p in self.profiles
            },
            "changes_made": False,
        }

    def _ensure_state_dir(self) -> None:
        self.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.state_dir, 0o700)

    def _locked(self):
        """Context manager acquiring a non-blocking per-user operation lock."""
        self._ensure_state_dir()
        fd = os.open(self.lock_file, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            raise DNSManagerError("Another DNS operation is already running")
        return fd

    def _snapshot(self) -> dict[str, dict[str, str]]:
        return {p: self._read_settings(p, RESTORE_FIELDS) for p in self.profiles}

    def create_backup(self) -> Path:
        self._ensure_state_dir()
        data = {
            "version": 1,
            "created": datetime.datetime.now().astimezone().isoformat(),
            "profiles": {p: self._read_settings(p) for p in self.profiles},
        }
        for settings in data["profiles"].values():
            if set(settings) != set(BACKUP_FIELDS) or not all(
                isinstance(v, str) for v in settings.values()
            ):
                raise DNSManagerError("Incomplete or invalid profile settings")
        temporary = self.backup_file.with_name(
            self.backup_file.name + f".tmp-{os.getpid()}"
        )
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(data, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.link(temporary, self.backup_file)
            os.unlink(temporary)
            directory_fd = os.open(self.state_dir, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except FileExistsError as exc:
            try:
                temporary.unlink()
            except OSError:
                pass
            raise DNSManagerError("Backup already exists; overwrite is forbidden") from exc
        except Exception:
            try:
                temporary.unlink()
            except OSError:
                pass
            raise
        return self.backup_file

    def validate_backup(self) -> dict:
        try:
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(self.backup_file, flags)
            with os.fdopen(fd, "r", encoding="utf-8") as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode):
                    raise DNSManagerError("Backup is not a regular file")
                if info.st_uid != os.getuid():
                    raise DNSManagerError("Backup has an unexpected owner")
                if stat.S_IMODE(info.st_mode) != 0o600:
                    raise DNSManagerError("Backup permissions must be 0600")
                data = json.load(stream)
        except DNSManagerError:
            raise
        except Exception as exc:
            raise DNSManagerError(f"Cannot read backup: {exc}") from exc
        if not isinstance(data, dict) or data.get("version") != 1:
            raise DNSManagerError("Unsupported or invalid backup format")
        if not isinstance(data.get("created"), str):
            raise DNSManagerError("Backup timestamp is missing")
        saved = data.get("profiles")
        if not isinstance(saved, dict) or set(saved) != set(self.profiles):
            raise DNSManagerError("Backup profile set does not match allowlist")
        for profile in self.profiles:
            settings = saved[profile]
            if not isinstance(settings, dict) or set(settings) != set(BACKUP_FIELDS):
                raise DNSManagerError(f"Incomplete backup for {profile}")
            if not all(isinstance(v, str) for v in settings.values()):
                raise DNSManagerError(f"Invalid values in backup for {profile}")
        return data

    def _apply_settings(self, profile: str, settings: dict[str, str]) -> None:
        if profile not in self.profiles:
            raise DNSManagerError(f"Profile is not allowlisted: {profile}")
        command = ["nmcli", "connection", "modify", "id", profile]
        for field in RESTORE_FIELDS:
            command.extend([field, settings[field]])
        code, output = self._run(command)
        if code:
            raise DNSManagerError(f"Cannot modify {profile}: {output}")

    def _verify(self, profile: str, expected: dict[str, str]) -> None:
        actual = self._read_settings(profile, RESTORE_FIELDS)
        for field in RESTORE_FIELDS:
            left, right = expected[field], actual[field]
            if field == "ipv4.dns":
                normalize = lambda value: sorted(
                    x.strip() for x in re.split(r"[,;\s]+", value) if x.strip()
                )
                if normalize(left) != normalize(right):
                    raise DNSManagerError(
                        f"Verification failed: {profile} {field}: "
                        f"expected {left!r}, got {right!r}"
                    )
            elif left != right:
                raise DNSManagerError(
                    f"Verification failed: {profile} {field}: "
                    f"expected {left!r}, got {right!r}"
                )

    def _rollback(self, attempted: list[str], snapshot: dict) -> None:
        errors = []
        for profile in reversed(attempted):
            try:
                self._apply_settings(profile, snapshot[profile])
                self._verify(profile, snapshot[profile])
            except Exception as exc:
                errors.append(f"{profile}: {exc}")
        if errors:
            raise DNSManagerError("Rollback incomplete: " + "; ".join(errors))

    def apply_adguard_dns(self) -> None:
        self.apply_dns_servers(ADGUARD_DNS)

    def apply_dns_servers(self, dns_servers) -> None:
        """Apply validated resolver IPs to explicitly allowlisted test profiles only."""
        import ipaddress
        try:
            servers = tuple(str(ipaddress.ip_address(value)) for value in dns_servers)
        except (TypeError, ValueError) as exc:
            raise DNSManagerError("Invalid DNS server address") from exc
        if not servers or len(servers) > 6 or len(set(servers)) != len(servers):
            raise DNSManagerError("Provide between one and six unique DNS addresses")
        lock_fd = self._locked()
        try:
            connected, detail = self.vpn_status()
            if not connected:
                raise DNSManagerError(
                    "VPN is not confirmed in TUN mode; refusing DNS changes. " + detail
                )
            active = self.active_profiles()
            active_targets = [p for p in self.profiles if p in active]
            if active_targets:
                raise DNSManagerError(
                    "Test profiles must be inactive: " + ", ".join(active_targets)
                )
            snapshot = self._snapshot()
            desired = {}
            for profile, settings in snapshot.items():
                changed = dict(settings)
                changed["ipv4.dns"] = " ".join(servers)
                changed["ipv4.ignore-auto-dns"] = "yes"
                # IPv6 and all other fields are intentionally preserved.
                desired[profile] = changed
            attempted = []
            try:
                for profile in self.profiles:
                    attempted.append(profile)  # include partial nmcli failures
                    self._apply_settings(profile, desired[profile])
                    self._verify(profile, desired[profile])
            except Exception as exc:
                try:
                    self._rollback(attempted, snapshot)
                except Exception as rollback_exc:
                    raise DNSManagerError(
                        f"Apply failed: {exc}. CRITICAL: {rollback_exc}"
                    ) from exc
                raise DNSManagerError(f"Apply failed; original settings restored: {exc}") from exc
        finally:
            os.close(lock_fd)

    def restore(self) -> None:
        lock_fd = self._locked()
        try:
            data = self.validate_backup()
            active = self.active_profiles()
            active_targets = [p for p in self.profiles if p in active]
            if active_targets:
                raise DNSManagerError(
                    "Test profiles must be inactive: " + ", ".join(active_targets)
                )
            snapshot = self._snapshot()
            attempted = []
            try:
                for profile in self.profiles:
                    attempted.append(profile)
                    saved = {
                        field: data["profiles"][profile][field]
                        for field in RESTORE_FIELDS
                    }
                    self._apply_settings(profile, saved)
                    self._verify(profile, saved)
            except Exception as exc:
                try:
                    self._rollback(attempted, snapshot)
                except Exception as rollback_exc:
                    raise DNSManagerError(
                        f"Restore failed: {exc}. CRITICAL: {rollback_exc}"
                    ) from exc
                raise DNSManagerError(
                    f"Restore failed; pre-operation settings restored: {exc}"
                ) from exc
        finally:
            os.close(lock_fd)
