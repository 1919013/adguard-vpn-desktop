"""Read-only diagnostics for AdGuard VPN CLI and NetworkManager."""
from __future__ import annotations

import shutil
import threading

from core.vpn import VPNService
from services.network_manager import NetworkManagerService


def collect_diagnostics(vpn: VPNService | None = None,
                        network: NetworkManagerService | None = None) -> str:
    vpn = vpn or VPNService()
    network = network or NetworkManagerService()
    lines = ["ДИАГНОСТИКА ADGUARD VPN DESKTOP", ""]
    executable = shutil.which("adguardvpn-cli")
    lines.append("AdGuard VPN CLI: " + (executable or "не найден в PATH"))
    code, status = vpn.status()
    lines.extend(["", f"Статус VPN (код {code}):", status or "Нет вывода"])
    try:
        snapshot = network.snapshot()
        lines.extend(["", "СЕТЕВЫЕ УСТРОЙСТВА"])
        for device in snapshot["devices"]:
            lines.append(
                f"{device['name']} — {device['type']}; {device['state']}; "
                f"профиль: {device['connection'] or 'не назначен'}"
            )
        lines.extend(["", "ПРОФИЛИ NETWORKMANAGER"])
        for profile in snapshot["profiles"]:
            lines.append(
                f"{profile['name']} — {profile['type']}; "
                f"устройство: {profile['device'] or 'не активно'}"
            )
    except Exception as exc:
        lines.extend(["", "Ошибка чтения NetworkManager:", str(exc)])
    lines.extend([
        "",
        "Проверка только читает состояние. Маршруты, DNS и firewall не изменялись.",
        "Это не полноценная проверка DNS/IPv4/IPv6-утечек.",
    ])
    return "\n".join(lines)


def build_diagnostics_tab():
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk, GLib

    root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    root.set_border_width(14)
    title = Gtk.Label()
    title.set_markup("<b>Диагностика</b>")
    title.set_xalign(0)
    root.pack_start(title, False, False, 0)

    output = Gtk.TextView()
    output.set_editable(False)
    output.set_cursor_visible(False)
    output.set_monospace(True)
    output.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
    output.get_buffer().set_text("Нажмите «Собрать диагностику».")
    scroll = Gtk.ScrolledWindow()
    scroll.set_hexpand(True)
    scroll.set_vexpand(True)
    scroll.add(output)
    root.pack_start(scroll, True, True, 0)

    button = Gtk.Button(label="Собрать диагностику")
    root.pack_start(button, False, False, 0)

    def run(_button):
        button.set_sensitive(False)
        output.get_buffer().set_text("Сбор диагностической информации…")

        def worker():
            try:
                result = collect_diagnostics()
            except Exception as exc:
                result = "Ошибка диагностики: " + str(exc)
            GLib.idle_add(finish, result)

        def finish(result):
            output.get_buffer().set_text(result)
            button.set_sensitive(True)
            return False

        threading.Thread(target=worker, daemon=True).start()

    button.connect("clicked", run)
    return root
