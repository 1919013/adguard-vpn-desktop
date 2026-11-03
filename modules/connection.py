"""VPN connection feature: controller and GTK tab."""
from __future__ import annotations

import re
import threading

from core.vpn import VPNService
from core.servers import find_locations


class ConnectionController:
    """UI-independent controller used by the GTK connection tab."""

    def __init__(self, service: VPNService | None = None):
        self.service = service or VPNService()

    def get_status(self):
        return self.service.status()

    def get_locations(self):
        return self.service.list_locations()

    def connect(self, city: str | None = None):
        return self.service.connect(city)

    def disconnect(self):
        return self.service.disconnect()


def _clean_cli_output(value: str) -> str:
    value = re.sub(r"(?:\x1b|\x9b)?\[[0-?]*[ -/]*[@-~]", "", value or "")
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", value)


def build_connection_tab():
    """Build the connection tab; GTK is imported lazily for headless tests."""
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk, GLib

    controller = ConnectionController()
    root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    root.set_border_width(12)

    status_label = Gtk.Label(label="Проверка состояния AdGuard VPN…", xalign=0)
    status_label.set_line_wrap(True)
    status_label.set_selectable(True)
    root.pack_start(status_label, False, False, 0)

    warning_label = Gtk.Label(label="", xalign=0)
    warning_label.set_line_wrap(True)
    warning_label.get_style_context().add_class("warning")
    root.pack_start(warning_label, False, False, 0)

    root.pack_start(Gtk.Label(label="Местоположение VPN-сервера", xalign=0), False, False, 0)
    location_line = Gtk.Box(spacing=8)
    root.pack_start(location_line, False, False, 0)
    location_combo = Gtk.ComboBoxText.new_with_entry()
    location_combo.set_hexpand(True)
    entry = location_combo.get_child()
    entry.set_placeholder_text("Поиск: например, Riga или Latvia")
    location_line.pack_start(location_combo, True, True, 0)

    locations: list[dict] = []

    def show_message(title, body):
        dialog = Gtk.MessageDialog(
            transient_for=root.get_toplevel() if isinstance(root.get_toplevel(), Gtk.Window) else None,
            flags=0,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text=title,
        )
        dialog.format_secondary_text((body or "Нет дополнительной информации.")[:7000])
        dialog.run()
        dialog.destroy()

    def run_async(operation, callback):
        def worker():
            try:
                result = operation()
            except Exception as error:
                result = (1, str(error))
            GLib.idle_add(callback, result)

        threading.Thread(target=worker, daemon=True).start()

    def update_status(result):
        code, output = result
        clean = _clean_cli_output(output)
        status_label.set_text(clean or "Статус не получен")
        lower = (output or "").casefold()
        has_dns_warning = "dns" in lower and (
            "could not" in lower or "bypass" in lower or "не удалось" in lower
        )
        warning_label.set_text(
            "⚠ AdGuard VPN сообщает о проблеме с системным DNS. DNS-запросы могут обходить VPN."
            if has_dns_warning else ""
        )
        if code != 0 and not clean:
            status_label.set_text("Не удалось получить состояние VPN.")

    def refresh_status():
        status_label.set_text("Проверка состояния AdGuard VPN…")
        run_async(controller.get_status, update_status)

    def update_locations(result):
        nonlocal locations
        code, output, found = result
        locations = found
        location_combo.remove_all()
        location_combo.append_text("Автоматически / последний сервер")
        for item in locations:
            location_combo.append_text(item["label"])
        location_combo.set_active(0)
        if code != 0:
            show_message("Не удалось получить список серверов", output)
        elif not locations:
            show_message("Список серверов пуст", "Не удалось распознать формат ответа AdGuard VPN CLI.")

    def load_locations(*_):
        location_combo.remove_all()
        location_combo.append_text("Загрузка списка…")
        location_combo.set_active(0)
        run_async(controller.get_locations, update_locations)

    def operation_done(result):
        code, output = result
        show_message("Результат операции", output or (
            "Команда выполнена." if code == 0 else "Команда завершилась с ошибкой."
        ))
        refresh_status()

    def connect_vpn(*_):
        index = location_combo.get_active()
        if index == 0:
            city = None
        elif index > 0:
            city = locations[index - 1]["city"] if index - 1 < len(locations) else None
        else:
            query = entry.get_text().strip()
            if not query:
                city = None
            else:
                matches = find_locations(query, locations)
                if len(matches) != 1:
                    show_message(
                        "Сервер не выбран",
                        "Уточните название города или страны либо выберите сервер из списка.",
                    )
                    return
                city = matches[0]["city"]

        status_label.set_text("Подключение…")
        run_async(lambda: controller.connect(city), operation_done)

    def disconnect_vpn(*_):
        status_label.set_text("Отключение…")
        run_async(controller.disconnect, operation_done)

    controls = Gtk.Box(spacing=8)
    root.pack_start(controls, False, False, 0)
    load_button = Gtk.Button(label="Загрузить список")
    load_button.connect("clicked", load_locations)
    controls.pack_start(load_button, False, False, 0)
    connect_button = Gtk.Button(label="Подключить")
    connect_button.connect("clicked", connect_vpn)
    controls.pack_start(connect_button, False, False, 0)
    disconnect_button = Gtk.Button(label="Отключить")
    disconnect_button.connect("clicked", disconnect_vpn)
    controls.pack_start(disconnect_button, False, False, 0)
    refresh_button = Gtk.Button(label="Обновить статус")
    refresh_button.connect("clicked", lambda *_: refresh_status())
    controls.pack_start(refresh_button, False, False, 0)

    hint = Gtk.Label(
        label="Для подключения передаётся только название города — формат AdGuard VPN CLI.",
        xalign=0,
    )
    hint.set_line_wrap(True)
    root.pack_start(hint, False, False, 0)

    refresh_status()
    load_locations()
    return root
