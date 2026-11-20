"""DNS and protection tab.

The GTK view is deliberately thin: NetworkManager inspection and all DNS changes
are delegated to services.dns_manager.DNSManager. Profile/interface discovery is
read-only; DNS writes remain restricted to the legacy test-profile allowlist.
"""
from __future__ import annotations

import threading
from typing import Callable

from ui.dialogs import confirm_dialog

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

    def apply(self, dns_servers=None) -> None:
        if dns_servers is not None:
            if dns_servers:
                self.manager.apply_dns_servers(dns_servers)
            else:
                self.manager.restore()
        else:
            self.manager.apply_adguard_dns()

    def validate_backup(self) -> dict:
        return self.manager.validate_backup()

    def restore(self) -> None:
        self.manager.restore()

    def discover_profiles(self):
        return self.manager.discover_profiles()

    def backup_selected(self, profile_uuid: str):
        return self.manager.backup_selected_profile(profile_uuid)

    def apply_selected(self, profile_uuid: str, dns_servers):
        self.manager.apply_selected_profile_dns(profile_uuid, dns_servers)

    def restore_selected(self, profile_uuid: str):
        self.manager.restore_selected_profile(profile_uuid)


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
        + ". Активные пользовательские профили не изменяются."
    )
    root.pack_start(warning, False, False, 0)

    providers = {
        "AdGuard DNS — блокировка рекламы": ("94.140.14.14", "94.140.15.15"),
        "AdGuard DNS — без фильтрации": ("94.140.14.140", "94.140.14.141"),
        "AdGuard DNS — семейный": ("94.140.14.15", "94.140.15.16"),
        "Cloudflare": ("1.1.1.1", "1.0.0.1"),
        "Cloudflare — вредоносные домены": ("1.1.1.2", "1.0.0.2"),
        "Google Public DNS": ("8.8.8.8", "8.8.4.4"),
        "OpenDNS": ("208.67.222.222", "208.67.220.220"),
        "Quad9": ("9.9.9.9", "149.112.112.112"),
        "Mullvad DNS": ("194.242.2.2", "194.242.2.3"),
        "Восстановить исходный DNS тестовых профилей": (),
        "Свой DNS": None,
    }
    provider = Gtk.ComboBoxText()
    for label in providers:
        provider.append_text(label)
    provider.set_active(0)
    root.pack_start(provider, False, False, 0)
    custom_dns = Gtk.Entry()
    custom_dns.set_placeholder_text("Свой DNS: IPv4/IPv6 через запятую")
    root.pack_start(custom_dns, False, False, 0)
    buttons = []
    profile_label = Gtk.Label(
        label=("Для обычного Ethernet/Wi-Fi профиля выбери его ниже, создай отдельную копию, "
               "затем примени DNS. Активные профили не изменяются. Старые кнопки тестового "
               "режима внизу по-прежнему затрагивают только два тестовых профиля.")
    )
    profile_label.set_xalign(0)
    profile_label.set_line_wrap(True)
    root.pack_start(profile_label, False, False, 0)

    selected_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    selected_profile = Gtk.ComboBoxText()
    selected_profile.set_hexpand(True)
    refresh_profiles = Gtk.Button(label="Обновить список профилей")
    selected_row.pack_start(selected_profile, True, True, 0)
    selected_row.pack_start(refresh_profiles, False, False, 0)
    root.pack_start(selected_row, False, False, 0)

    def refresh_profile_list():
        def display(items):
            selected_profile.remove_all()
            for item in items:
                label = item["name"] + " — " + item["type"] + " — " + (item["device"] or "без устройства")
                selected_profile.append(item["uuid"], label)
            if items:
                selected_profile.set_active(0)
            else:
                selected_profile.append("", "Ethernet/Wi-Fi профили не найдены")
                selected_profile.set_active(0)
            return "Список профилей обновлён."
        run_async("Обнаружение профилей (только чтение)", controller.discover_profiles, display)

    refresh_profiles.connect("clicked", lambda _button: refresh_profile_list())
    selected_actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    root.pack_start(selected_actions, False, False, 0)

    def selected_uuid():
        value = selected_profile.get_active_id()
        if not value:
            raise ValueError("Сначала обнови список и выбери профиль Ethernet/Wi-Fi.")
        return value

    def backup_selected():
        try:
            uuid = selected_uuid()
        except Exception as exc:
            show_error(exc)
            return
        run_async("Резервная копия выбранного профиля",
                  lambda: controller.backup_selected(uuid),
                  lambda path: "Резервная копия создана: " + str(path))

    def apply_selected():
        try:
            uuid = selected_uuid()
            servers = selected_dns()
        except Exception as exc:
            show_error(exc)
            return
        confirm(
            "Изменится только выбранный профиль. Он должен быть отключён; "
            "резервная копия обязательна, VPN TUN должен быть подтверждён.",
            lambda: run_async(
                "Применение DNS к выбранному профилю",
                lambda: controller.apply_selected(uuid, servers),
                lambda _result: "DNS применён и проверен."
            ),
        )

    def restore_selected():
        try:
            uuid = selected_uuid()
        except Exception as exc:
            show_error(exc)
            return
        confirm(
            "Восстановить исходные DNS-настройки выбранного профиля? "
            "Профиль должен быть отключён.",
            lambda: run_async(
                "Восстановление выбранного профиля",
                lambda: controller.restore_selected(uuid),
                lambda _result: "Исходные DNS-настройки восстановлены и проверены."
            ),
        )

    for label, callback in (
        ("Создать копию выбранного профиля", backup_selected),
        ("Применить DNS к выбранному", apply_selected),
        ("Восстановить выбранный профиль", restore_selected),
    ):
        button = Gtk.Button(label=label)
        button.connect("clicked", lambda _button, cb=callback: cb())
        selected_actions.pack_start(button, False, False, 0)
        buttons.append(button)

    def selected_dns():
        label = provider.get_active_text()
        servers = providers.get(label)
        if servers is None:
            import ipaddress
            raw = [part.strip() for part in custom_dns.get_text().replace(";", ",").split(",") if part.strip()]
            if not raw:
                raise ValueError("Введите хотя бы один адрес DNS.")
            try:
                return tuple(str(ipaddress.ip_address(value)) for value in raw)
            except ValueError as exc:
                raise ValueError("Введите корректные IPv4/IPv6-адреса.") from exc
        return servers

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
        lines.extend(["", "ОБНАРУЖЕННЫЕ ПРОФИЛИ NETWORKMANAGER (только чтение)"])
        discovered = data.get("discovered_profiles", [])
        if isinstance(discovered, dict) and "error" in discovered:
            lines.append("Ошибка обнаружения: " + discovered["error"])
        else:
            for item in discovered:
                lines.append(
                    f'{item["name"]} | {item["type"]} | '
                    f'{item["device"] or "устройство не назначено"} | '
                    f'{"активен" if item["active"] else "не активен"}'
                )
            if not discovered:
                lines.append("Обычные Ethernet/Wi-Fi профили не найдены.")

        lines.extend(["", "СЕТЕВЫЕ ИНТЕРФЕЙСЫ (только чтение)"])
        interfaces = data.get("network_interfaces", [])
        if isinstance(interfaces, dict) and "error" in interfaces:
            lines.append("Ошибка чтения интерфейсов: " + interfaces["error"])
        else:
            for item in interfaces:
                lines.append(
                    f'{item["device"]} | {item["type"]} | {item["state"]} | '
                    f'{item["connection"] or "без активного профиля"}'
                )
            if not interfaces:
                lines.append("Интерфейсы не обнаружены.")

        lines.extend([
            "",
            "Важно: обнаружение профилей и интерфейсов ничего не меняет. "
            "Применение DNS пока ограничено тестовыми профилями.",
            "Чтение конфигурации не является полноценным DNS leak test.",
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
        if confirm_dialog(
            root.get_toplevel(), "Подтвердите операцию", message,
            accept_label="Продолжить",
        ):
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
        "Применить выбранный DNS только к разрешённым неактивным тестовым профилям",
        lambda: confirm(
            "Будут изменены DNS-параметры только тестовых профилей. "
            "Перед применением убедитесь, что резервная копия создана. "
            "Рабочие профили не затрагиваются.",
            lambda: run_async("Применение выбранного DNS", lambda: controller.apply(selected_dns()),
                              lambda _result: "Выбранный DNS применён к тестовым профилям. IPv6-параметры сохранены."),
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
