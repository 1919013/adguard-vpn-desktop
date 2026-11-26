"""VPN connection feature: responsive GTK tab with offline location catalogue."""
from __future__ import annotations

import re
import threading
from datetime import datetime

from core.vpn import VPNService
from core.servers import find_locations, load_refresh_interval, save_refresh_interval


class ConnectionController:
    """UI-independent controller used by the GTK connection tab."""

    def __init__(self, service: VPNService | None = None):
        self.service = service or VPNService()

    def get_status(self):
        return self.service.status()

    def get_cached_locations(self):
        return self.service.cached_locations()

    def get_locations(self):
        return self.service.list_locations()

    def connect(self, city: str | None = None):
        return self.service.connect(city)

    def disconnect(self):
        return self.service.disconnect()


def _clean_cli_output(value: str) -> str:
    value = re.sub(r"(?:\x1b|\x9b)?\[[0-?]*[ -/]*[@-~]", "", value or "")
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", value)


def _format_timestamp(value: str | None) -> str:
    if not value:
        return "время неизвестно"
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone()
        return stamp.strftime("%d.%m.%Y %H:%M")
    except (TypeError, ValueError):
        return value


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
    refresh_in_progress = False
    refresh_timer_id = None

    from ui.dialogs import show_scrolled_message

    def show_message(title, body):
        parent = root.get_toplevel()
        if not isinstance(parent, Gtk.Window):
            parent = None
        show_scrolled_message(parent, title, body)

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

    def render_locations(found: list[dict]):
        nonlocal locations
        previous_city = None
        active = location_combo.get_active()
        if active > 0 and active - 1 < len(locations):
            previous_city = locations[active - 1].get("city")
        previous_text = entry.get_text()
        locations = found
        location_combo.remove_all()
        location_combo.append_text("Автоматически / последний сервер")
        selected = 0
        for index, item in enumerate(locations, start=1):
            location_combo.append_text(item["label"])
            if previous_city and item.get("city") == previous_city:
                selected = index
        location_combo.set_active(selected)
        if selected == 0 and previous_text and active < 0:
            entry.set_text(previous_text)

    def update_locations(result):
        nonlocal refresh_in_progress
        refresh_in_progress = False
        if len(result) == 5:
            code, output, found, from_cache, updated_at = result
        else:
            code, output = result
            found, from_cache, updated_at = [], False, None

        if found:
            render_locations(found)
            if from_cache:
                location_info.set_text(
                    f"⚠ Не удалось обновить список. Используется сохранённая версия "
                    f"({len(found)} локаций; обновлена {_format_timestamp(updated_at)})."
                )
            else:
                location_info.set_text(
                    f"Список обновлён: {len(found)} локаций · {_format_timestamp(updated_at)}"
                )
        elif code != 0:
            location_info.set_text(
                "Список пока недоступен. При первом запуске без сохранённой копии "
                "повторите попытку позже."
            )
        else:
            location_info.set_text("CLI не вернул корректный список локаций.")

    def load_locations(*_):
        nonlocal refresh_in_progress
        if refresh_in_progress:
            return
        refresh_in_progress = True
        if not locations:
            location_info.set_text("Обновление списка в фоне…")
        run_async(controller.get_locations, update_locations)

    def schedule_refresh(minutes: int):
        nonlocal refresh_timer_id
        if refresh_timer_id is not None:
            GLib.source_remove(refresh_timer_id)
            refresh_timer_id = None
        if minutes:
            refresh_timer_id = GLib.timeout_add_seconds(minutes * 60, periodic_refresh)

    def periodic_refresh():
        load_locations()
        return True

    def on_interval_changed(widget):
        value = widget.get_active_id()
        try:
            minutes = int(value)
        except (TypeError, ValueError):
            return
        if save_refresh_interval(minutes):
            schedule_refresh(minutes)
            interval_info.set_text(
                "Автообновление отключено." if minutes == 0
                else f"Список будет проверяться каждые {minutes} мин."
            )

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
    load_button = Gtk.Button(label="Обновить список")
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

    location_info = Gtk.Label(label="", xalign=0)
    location_info.set_line_wrap(True)
    root.pack_start(location_info, False, False, 0)

    interval_line = Gtk.Box(spacing=8)
    interval_line.pack_start(Gtk.Label(label="Проверять список:"), False, False, 0)
    interval_combo = Gtk.ComboBoxText()
    interval_combo.append("30", "Каждые 30 минут")
    interval_combo.append("60", "Каждый час")
    interval_combo.append("0", "Вручную")
    interval_combo.set_active_id(str(load_refresh_interval()))
    interval_combo.connect("changed", on_interval_changed)
    interval_line.pack_start(interval_combo, False, False, 0)
    root.pack_start(interval_line, False, False, 0)
    interval_info = Gtk.Label(label="", xalign=0)
    interval_info.set_line_wrap(True)
    root.pack_start(interval_info, False, False, 0)

    hint = Gtk.Label(
        label="Список хранится локально. Если AdGuard VPN CLI временно недоступен, "
              "оболочка продолжает показывать последнюю успешно сохранённую версию. "
              "Доступность выбранного сервера проверяется самим CLI при подключении.",
        xalign=0,
    )
    hint.set_line_wrap(True)
    root.pack_start(hint, False, False, 0)

    # Render disk cache before any network operation, so the selector is usable
    # immediately even when the CLI control plane is offline.
    cached, cached_at = controller.get_cached_locations()
    if cached:
        render_locations(cached)
        location_info.set_text(
            f"Сохранённый список: {len(cached)} локаций · {_format_timestamp(cached_at)}. "
            "Проверяем обновления в фоне…"
        )
    else:
        location_info.set_text("Локальной копии пока нет; первая загрузка выполняется в фоне.")

    interval = load_refresh_interval()
    interval_info.set_text(
        "Автообновление отключено." if interval == 0
        else f"Список будет проверяться каждые {interval} мин."
    )
    schedule_refresh(interval)
    refresh_status()
    load_locations()
    return root
