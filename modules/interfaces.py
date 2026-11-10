"""Discover and configure the outbound interface used by AdGuard VPN CLI.

Interface names are discovered at runtime; no machine-specific connection names
or interface identifiers are embedded in the application.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class NetworkInterface:
    name: str
    kind: str
    state: str
    connection: str = ""


def _run(args: list[str], timeout: int = 12) -> tuple[int, str]:
    try:
        result = subprocess.run(
            args, text=True, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, timeout=timeout, check=False,
        )
        return result.returncode, result.stdout.strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)


def discover_interfaces() -> list[NetworkInterface]:
    """Return currently present physical/virtual network devices.

    Loopback and AdGuard's own TUN device are excluded. Connection profile
    names are informational only and are never used as identifiers.
    """
    code, output = _run(["ip", "-j", "-details", "link", "show"])
    if code:
        raise RuntimeError("Не удалось получить список интерфейсов через ip: " + output)

    try:
        links = json.loads(output or "[]")
    except json.JSONDecodeError as exc:
        raise RuntimeError("Система вернула некорректный список сетевых интерфейсов") from exc

    nm_code, nm_output = _run([
        "nmcli", "--colors", "no", "--terse", "--escape", "yes",
        "--fields", "DEVICE,TYPE,STATE,CONNECTION", "device", "status",
    ])
    nm_by_device: dict[str, tuple[str, str, str]] = {}
    if nm_code == 0:
        for line in nm_output.splitlines():
            fields = line.split(":")
            if len(fields) >= 4:
                device = fields[0].replace(r"\:", ":")
                nm_by_device[device] = (
                    fields[1].replace(r"\:", ":"),
                    fields[2].replace(r"\:", ":"),
                    fields[3].replace(r"\:", ":"),
                )

    found: list[NetworkInterface] = []
    for link in links:
        name = str(link.get("ifname", ""))
        if not name or name == "lo" or name.startswith(("tun", "tap", "wg")):
            continue
        if link.get("link_type") == "loopback":
            continue
        nm_type, nm_state, connection = nm_by_device.get(
            name, (str(link.get("link_type", "network")), "не управляется NetworkManager", "")
        )
        state = nm_state or ("UP" if "UP" in link.get("flags", []) else "DOWN")
        found.append(NetworkInterface(name, nm_type, state, connection))

    return sorted(found, key=lambda item: item.name.casefold())


def get_bound_interface() -> tuple[int, str]:
    """Read the current AdGuard VPN CLI interface override."""
    return _run(["adguardvpn-cli", "config", "show"])


def bind_interface(name: str | None) -> tuple[int, str]:
    """Bind VPN outbound traffic to one detected interface, or clear override."""
    if name is not None:
        if not isinstance(name, str) or not name.strip() or name.startswith("-"):
            return 2, "Некорректное имя сетевого интерфейса."
        available = {item.name for item in discover_interfaces()}
        if name not in available:
            return 2, "Интерфейс больше не обнаружен. Обновите список."
        value = name
    else:
        value = ""
    return _run(["adguardvpn-cli", "config", "set-bound-if-override", value])


def build_interfaces_tab():
    """GTK tab for discovering interfaces and selecting the VPN outbound link."""
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk, GLib
    import threading

    root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    root.set_border_width(14)

    heading = Gtk.Label()
    heading.set_markup("<b>Сетевые интерфейсы</b>")
    heading.set_xalign(0)
    root.pack_start(heading, False, False, 0)

    note = Gtk.Label(
        label=("Интерфейсы обнаруживаются автоматически. AdGuard VPN CLI "
               "поддерживает привязку исходящего VPN-трафика к одному интерфейсу. "
               "Выбор не меняет профили NetworkManager и не отключает другие сети."),
        xalign=0,
    )
    note.set_line_wrap(True)
    root.pack_start(note, False, False, 0)

    status = Gtk.Label(label="Нажмите «Обновить список».", xalign=0)
    status.set_line_wrap(True)
    root.pack_start(status, False, False, 0)

    list_box = Gtk.ListBox()
    list_box.set_selection_mode(Gtk.SelectionMode.NONE)
    scroller = Gtk.ScrolledWindow()
    scroller.set_min_content_height(220)
    scroller.set_vexpand(True)
    scroller.add(list_box)
    root.pack_start(scroller, True, True, 0)

    selected: dict[str, Gtk.CheckButton] = {}
    buttons: list[Gtk.Widget] = []

    def set_busy(value: bool):
        for button in buttons:
            button.set_sensitive(not value)

    def finish_discovery(result):
        code, payload = result
        set_busy(False)
        for child in list_box.get_children():
            list_box.remove(child)
        selected.clear()
        if code:
            status.set_text(payload)
            return
        items = payload
        if not items:
            status.set_text("Сетевые интерфейсы не обнаружены.")
            return
        status.set_text(f"Обнаружено интерфейсов: {len(items)}. Выберите один для исходящего VPN-трафика.")
        for item in items:
            label = f"{item.name} — {item.kind}; {item.state}"
            if item.connection:
                label += f"; профиль: {item.connection}"
            check = Gtk.CheckButton(label=label)
            check.connect("toggled", on_toggle, item.name)
            selected[item.name] = check
            list_box.add(check)
        list_box.show_all()

    def on_toggle(widget, name):
        if widget.get_active():
            for other_name, other in selected.items():
                if other_name != name:
                    other.set_active(False)

    def refresh(*_):
        set_busy(True)
        status.set_text("Обнаружение интерфейсов…")
        def worker():
            try:
                result = (0, discover_interfaces())
            except Exception as exc:
                result = (1, str(exc))
            GLib.idle_add(finish_discovery, result)
        threading.Thread(target=worker, daemon=True).start()

    def apply(*_):
        chosen = [name for name, widget in selected.items() if widget.get_active()]
        name = chosen[0] if chosen else None
        set_busy(True)
        status.set_text("Применение настройки AdGuard VPN CLI…")
        def worker():
            result = bind_interface(name)
            GLib.idle_add(finish_apply, result, name)
        threading.Thread(target=worker, daemon=True).start()

    def finish_apply(result, name):
        set_busy(False)
        code, output = result
        status.set_text(
            ("Настройка применена: " + (name or "автоматический выбор интерфейса") + "\n" + output)
            if code == 0 else ("Не удалось применить настройку:\n" + output)
        )

    row = Gtk.Box(spacing=8)
    root.pack_start(row, False, False, 0)
    refresh_button = Gtk.Button(label="Обновить список")
    refresh_button.connect("clicked", refresh)
    row.pack_start(refresh_button, False, False, 0)
    apply_button = Gtk.Button(label="Применить выбор")
    apply_button.connect("clicked", apply)
    row.pack_start(apply_button, False, False, 0)
    clear_button = Gtk.Button(label="Автоматический выбор")
    clear_button.connect("clicked", lambda *_: clear_selection())
    row.pack_start(clear_button, False, False, 0)
    buttons.extend([refresh_button, apply_button, clear_button])

    def clear_selection():
        for widget in selected.values():
            widget.set_active(False)
        apply()

    refresh()
    return root
