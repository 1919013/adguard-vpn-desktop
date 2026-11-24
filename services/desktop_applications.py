"""Discover launchable Linux desktop applications for split-tunnel UI.

Discovery is read-only. Desktop Exec entries are parsed into argv without a
shell; field-code placeholders are removed because the routing launcher does
not open a user-selected document. Applications requiring D-Bus activation
are marked as such and must be restarted through their scoped launcher.
"""
from __future__ import annotations

import os
import re
import shlex
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from services.process_split_tunnel import SplitTunnelError, build_scoped_launch_command

SYSTEM_DIRS = (
    Path("/usr/local/share/applications"),
    Path("/usr/share/applications"),
    Path("/var/lib/flatpak/exports/share/applications"),
)
USER_DIRS = (
    Path.home() / ".local/share/applications",
    Path.home() / ".local/share/flatpak/exports/share/applications",
)
FIELD_CODE = re.compile(r"%(?:[fFuUdDnNickvm]|%)")
INVALID_FIELD = re.compile(r"%[A-Za-z]")


@dataclass(frozen=True)
class DesktopApplication:
    desktop_id: str
    name: str
    exec_argv: tuple[str, ...]
    source: str
    dbus_activatable: bool
    flatpak: bool


def _desktop_id(path: Path, root: Path) -> str:
    relative = path.relative_to(root)
    return relative.as_posix().replace("/", "-")


def _read_desktop_entry(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    in_entry = False
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return values
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            in_entry = line == "[Desktop Entry]"
            continue
        if in_entry and "=" in line:
            key, value = line.split("=", 1)
            # Ignore localized variants; prefer the base Name key.
            if "[" not in key:
                values[key] = value
    return values


def _exec_argv(value: str) -> tuple[str, ...]:
    try:
        raw = shlex.split(value, posix=True)
    except ValueError:
        return ()
    cleaned: list[str] = []
    for token in raw:
        # Remove supported desktop-entry field codes before rejecting unknown
        # codes; otherwise valid %f/%F/%u/%U placeholders are misclassified.
        token = FIELD_CODE.sub("", token)
        if INVALID_FIELD.search(token):
            return ()
        if token:
            cleaned.append(token)
    return tuple(cleaned)


def _flatpak_id(argv: Sequence[str]) -> bool:
    if not argv:
        return False
    first = Path(argv[0]).name
    return first == "flatpak" and "run" in argv[1:3]


def discover_applications(
    directories: Iterable[Path] | None = None,
    *,
    which=shutil.which,
    environ=None,
) -> list[DesktopApplication]:
    """Return visible desktop apps, with user entries overriding system ones."""
    env = os.environ if environ is None else environ
    dirs = tuple(directories) if directories is not None else (*SYSTEM_DIRS, *USER_DIRS)
    found: dict[str, DesktopApplication] = {}
    for root in dirs:
        root = Path(root)
        if not root.is_dir():
            continue
        try:
            paths = sorted(root.rglob("*.desktop"))
        except OSError:
            continue
        for path in paths:
            try:
                desktop_id = _desktop_id(path, root)
            except ValueError:
                continue
            values = _read_desktop_entry(path)
            if values.get("Type", "Application") != "Application":
                continue
            if values.get("Hidden", "").lower() == "true" or values.get("NoDisplay", "").lower() == "true":
                found.pop(desktop_id, None)
                continue
            name = values.get("Name", "").strip()
            argv = _exec_argv(values.get("Exec", ""))
            if not name or not argv:
                continue
            try_exec = values.get("TryExec", "").strip()
            if try_exec and not (Path(try_exec).is_absolute() and Path(try_exec).exists()) and not which(try_exec):
                continue
            if values.get("Terminal", "").lower() == "true":
                continue
            # Do not advertise entries restricted to another desktop session.
            only_show = values.get("OnlyShowIn", "").strip()
            if only_show:
                allowed = {item for item in only_show.rstrip(";").split(";") if item}
                current = set(env.get("XDG_CURRENT_DESKTOP", "").split(":"))
                if current and not (allowed & current):
                    continue
            found[desktop_id] = DesktopApplication(
                desktop_id=desktop_id,
                name=name,
                exec_argv=argv,
                source=str(path),
                dbus_activatable=values.get("DBusActivatable", "").lower() == "true",
                flatpak=_flatpak_id(argv),
            )
    return sorted(found.values(), key=lambda app: (app.name.casefold(), app.desktop_id.casefold()))


def filter_applications(applications: Iterable[DesktopApplication], prefix: str) -> list[DesktopApplication]:
    """Case-insensitive prefix filter over display name and desktop ID."""
    needle = prefix.strip().casefold()
    if not needle:
        return list(applications)
    return [
        app for app in applications
        if app.name.casefold().startswith(needle) or app.desktop_id.casefold().startswith(needle)
    ]



def build_scoped_application_command(
    application: DesktopApplication,
    *,
    systemd_run: str = "systemd-run",
) -> list[str]:
    """Build a safe scoped argv for an app that supports direct Exec launch.

    D-Bus-activatable applications are refused for now: a desktop/session-bus
    activation can reuse an already-running process outside the new scope.
    """
    if application.dbus_activatable:
        raise SplitTunnelError(
            "Приложение использует D-Bus activation. Его нельзя безопасно запускать "
            "в отдельном scope, пока не реализовано управление активацией."
        )
    return build_scoped_launch_command(
        application.exec_argv,
        application.desktop_id,
        systemd_run=systemd_run,
    )



def custom_application_from_path(executable: str) -> DesktopApplication:
    """Create a temporary catalog entry for an explicit executable path."""
    candidate = Path(executable).expanduser()
    if not candidate.is_absolute() or not candidate.is_file() or not os.access(candidate, os.X_OK):
        raise SplitTunnelError("Укажи существующий исполняемый файл по абсолютному пути.")
    normalized = str(candidate.resolve())
    safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "-", normalized).strip("-.")
    return DesktopApplication(
        desktop_id="custom-" + safe_id[:80],
        name=candidate.name,
        exec_argv=(normalized,),
        source=normalized,
        dbus_activatable=False,
        flatpak=False,
    )
