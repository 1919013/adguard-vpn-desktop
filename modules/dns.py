"""DNS and protection tab.

The GTK view is deliberately thin: all NetworkManager changes are delegated to
services.dns_manager.DNSManager, which enforces the test-profile allowlist.
"""
from __future__ import annotations

import threading
import traceback
from typing import Callable

from services.dns_manager import DNSManager, DNSManagerError, TEST_PROFILES


class DNSController:
    """Small UI-independent facade, convenient to test and reuse."""

    def __init__(self, manager: DNSManager | None = None):
        self.manager = manager or DNSManager()

    def get_status(self) -> dict:
        return self.manager.status()

    def get_dry_run(self) -> dict:
        return self.manager.dry_run()

    def create_backup(self):
        return self.manager.create_backup()

    def apply(self) -> None:
        self.manager.apply_adguard_dns()

    def validate_backup(self) -> dict:
        return self.manager.validate_backup()

    def restore(self) -> None:
        self.manager.restore()


def build_dns_tab(manager: DNSManager | None = None):
    """Build and return a GTK 3 DNS tab widget.

    GTK is imported lazily so the controller remains importable in headless
    test environments. Long-running operations execute on worker threads.
    """
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk, GLib

    controller = DNSController(manager)
    root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    root.set_border_width(14)

    title = Gtk.Label()
    title.set_markup("<b>DNS и защита</b>")
    title.set_xalign(0)
    root.pack_start(title, False, False, 0)

    warning = Gtk.Label()
    warning.set_xalign(0)
    warning.set_line_wrap(True)
    warning.set_markup(
        "<b>Безопасный тестовый режим.</b> Изменения разрешены только для "
        + ", ".join(TEST_PROFILES)
        + ". Рабочие профили Wired connection 1 и DOD недоступны."
    )
    root.pack_start(warning, False, False, 0)

    profile_label = Gtk.Label(label="DNS AdGuard: 46.243.231.30, 46.243.231.31")
    profile_label.set_xalign(0)
    root.pack_start(profile_label, False, False, 0)

    status_view = Gtk.TextView()
    status_view.set_editable(False)
    status_view.set_cursor_visible(False)
    status_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
    status_view.get_buffer().set_text(
        "Нажмите «Проверить состояние», чтобы прочитать настройки. "
        "До этого момента сетевые параметры не меняются."
    )
    scroller = Gtk.ScrolledWindow()
    scroller.set_hexpand(True)
    scroller.set_vexpand(True)
    scroller.add(status_view)
    root.pack_start(scroller, True, True, 0)

    action_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    root.pack_start(action_row, False, False, 0)
    action_row2 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    root.pack_start(action_row2, False, False, 0)

    buttons = []

    def set_text(value: str):
        status_view.get_buffer().set_text(value)

    def show_error(exc: Exception):
        set_text("ОШИБКА\n\n" + str(exc))

    def run_async(label: str, operation: Callable, formatter: Callable = str):
        for button in buttons:
            button.set_sensitive(False)
        set_text(label + "\n\nВыполняется…")

        def worker():
            try:
                result = operation()
                message = formatter(result)
                GLib.idle_add(finish, message, None)
            except Exception as exc:
                GLib.idle_add(finish, None, exc)

        def finish(message, error):
            for button in buttons:
                button.set_sensitive(True)
            if error is not None:
                show_error(error)
            else:
                set_text(message)
            return False

        threading.Thread(target=worker, daemon=True).start()

    def format_status(data: dict) -> str:
        lines = [
            "СОСТОЯНИЕ DNS",
            "",
            "VPN TUN: " + ("подтверждён" if data["vpn_connected_tun"] else "не подтверждён"),
            "",
            "Ответ AdGuard VPN CLI:",
            data["vpn_output"] or "Нет данных",
            "",
            "ТЕСТОВЫЕ ПРОФИЛИ NETWORKMANAGER",
        ]
        for profile, details in data["profiles"].items():
            lines.extend(["", f"[{profile}]"])
            if "error" in details:
                lines.append("Ошибка: " + details["error"])
            else:
                lines.append("Активное устройство: " + str(details["active_device"] or "нет"))
                for key, value in details["settings"].items():
                    lines.append(f"{key}: {value}")
        lines.extend([
            "",
            "Примечание: чтение конфигурации не является полноценным DNS leak test.",
        ])
        return "\n".join(lines)

    def format_dry_run(data: dict) -> str:
        lines = [
            "ПРЕДВАРИТЕЛЬНЫЙ ПЛАН — DRY RUN",
            "Изменения запрещены.",
            "VPN TUN: " + ("да" if data["vpn_connected_tun"] else "нет"),
            "",
        ]
        for profile, details in data["profiles"].items():
            lines.append(profile)
            lines.append("Активное устройство: " + str(details["active_device"] or "нет"))
            lines.append(
                "Планируемый DNS: "
                + (", ".join(details["planned_dns"]) if details["planned_dns"] else "не применяется: профиль не активен")
            )
            lines.append("")
        lines.append("Сетевые настройки не изменялись.")
        return "\n".join(lines)

    def confirm(message: str, callback: Callable):
        dialog = Gtk.MessageDialog(
            transient_for=root.get_toplevel() if isinstance(root.get_toplevel(), Gtk.Window) else None,
            flags=Gtk.DialogFlags.MODAL,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.CANCEL,
            text="Подтвердите операцию",
        )
        dialog.format_secondary_text(message)
        dialog.add_button("Продолжить", Gtk.ResponseType.OK)
        response = dialog.run()
        dialog.destroy()
        if response == Gtk.ResponseType.OK:
            callback()

    def add_button(parent, label, tooltip, callback):
        button = Gtk.Button(label=label)
        button.set_tooltip_text(tooltip)
        button.connect("clicked", lambda _button: callback())
        parent.pack_start(button, False, False, 0)
        buttons.append(button)
        return button

    add_button(
        action_row, "Проверить состояние",
        "Прочитать статус VPN и настройки тестовых профилей",
        lambda: run_async("Чтение состояния", controller.get_status, format_status),
    )
    add_button(
        action_row, "Пробный план",
        "Показать план без изменения настроек",
        lambda: run_async("Подготовка плана", controller.get_dry_run, format_dry_run),
    )
    add_button(
        action_row, "Создать резервную копию",
        "Сохранить исходные настройки; существующая копия не перезаписывается",
        lambda: run_async(
            "Создание резервной копии", controller.create_backup,
            lambda path: "Резервная копия создана:\n" + str(path)
        ),
    )
    add_button(
        action_row2, "Проверить копию",
        "Проверить структуру, владельца и права резервной копии",
        lambda: run_async(
            "Проверка резервной копии", controller.validate_backup,
            lambda data: (
                "РЕЗЕРВНАЯ КОПИЯ КОРРЕКТНА\n"
                + "Создана: " + data["created"] + "\n"
                + "Профили: " + ", ".join(data["profiles"])
            ),
        ),
    )
    add_button(
        action_row2, "Применить AdGuard DNS",
        "Изменить только разрешённые неактивные тестовые профили",
        lambda: confirm(
            "Будут изменены DNS-параметры только тестовых профилей. "
            "Перед применением убедитесь, что резервная копия создана. "
            "Рабочие профили не затрагиваются.",
            lambda: run_async("Применение AdGuard DNS", controller.apply,
                              lambda _result: "AdGuard DNS применён. IPv6-параметры сохранены."),
        ),
    )
    add_button(
        action_row2, "Восстановить из копии",
        "Восстановить DNS-параметры тестовых профилей из проверенной копии",
        lambda: confirm(
            "Будут восстановлены DNS-параметры тестовых профилей из резервной копии. "
            "Сначала будет проверена копия; при ошибке выполняется откат.",
            lambda: run_async("Восстановление DNS", controller.restore,
                              lambda _result: "Исходные DNS-параметры восстановлены и проверены."),
        ),
    )

    return root
