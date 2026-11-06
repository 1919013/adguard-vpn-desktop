"""Dynamic network interface discovery and AdGuard VPN CLI binding."""
from __future__ import annotations

import threading

from core.vpn import VPNService
from services.network_manager import NetworkManagerService


def build_interfaces_tab(network: NetworkManagerService | None = None,
                         vpn: VPNService | None = None):
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk, GLib

    network = network or NetworkManagerService()
    vpn = vpn or VPNService()
    root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=7)
    root.set_border_width(14)

    title = Gtk.Label()
    title.set_markup("<b>Сетевые интерфейсы</b>")
    title.set_xalign(0)
    root.pack_start(title, False, False, 0)

    note = Gtk.Label(
        label="Устройства и профили обнаруживаются автоматически. AdGuard VPN CLI "
              "поддерживает привязку исходящего VPN-соединения к одному интерфейсу. "
              "Виртуальные VPN-туннели не предлагаются как исходящие интерфейсы."
    )
    note.set_xalign(0)
    note.set_line_wrap(True)
    root.pack_start(note, False, False, 0)

    devices_store = Gtk.ListStore(str, str, str, str)
    profiles_store = Gtk.ListStore(str, str, str)
    combo = Gtk.ComboBoxText()
    combo.set_hexpand(True)
    root.pack_start(combo, False, False, 0)

    def add_table(parent, heading, store, columns):
        label = Gtk.Label()
        label.set_markup(f"<b>{heading}</b>")
        label.set_xalign(0)
        parent.pack_start(label, False, False, 0)
        view = Gtk.TreeView(model=store)
        for index, column_title in enumerate(columns):
            renderer = Gtk.CellRendererText()
            column = Gtk.TreeViewColumn(column_title, renderer, text=index)
            column.set_resizable(True)
            view.append_column(column)
        scroll = Gtk.ScrolledWindow()
        scroll.set_min_content_height(105)
        scroll.set_vexpand(True)
        scroll.add(view)
        parent.pack_start(scroll, True, True, 0)

    add_table(root, "Обнаруженные устройства", devices_store,
              ("Интерфейс", "Тип", "Состояние", "Активный профиль"))
    add_table(root, "Профили NetworkManager", profiles_store,
              ("Профиль", "Тип", "Активное устройство"))

    status = Gtk.Label(label="Нажмите «Обновить список».")
    status.set_xalign(0)
    status.set_line_wrap(True)
    root.pack_start(status, False, False, 0)

    buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    root.pack_start(buttons, False, False, 0)
    refresh = Gtk.Button(label="Обновить список")
    apply = Gtk.Button(label="Привязать VPN к интерфейсу")
    clear = Gtk.Button(label="Снять привязку")
    buttons.pack_start(refresh, False, False, 0)
    buttons.pack_start(apply, False, False, 0)
    buttons.pack_start(clear, False, False, 0)

    def confirm(message: str, action):
        dialog = Gtk.MessageDialog(
            transient_for=root.get_toplevel() if isinstance(root.get_toplevel(), Gtk.Window) else None,
            flags=Gtk.DialogFlags.MODAL,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.CANCEL,
            text="Подтвердите изменение конфигурации VPN",
        )
        dialog.format_secondary_text(message)
        dialog.add_button("Продолжить", Gtk.ResponseType.OK)
        response = dialog.run()
        dialog.destroy()
        if response == Gtk.ResponseType.OK:
            action()

    def refresh_list(_button=None):
        refresh.set_sensitive(False)
        apply.set_sensitive(False)
        status.set_text("Обнаружение устройств и профилей NetworkManager…")
        def worker():
            try:
                snapshot = network.snapshot()
                binding_code, binding, binding_output = vpn.bound_interface()
                error = None
            except Exception as exc:
                snapshot, binding_code, binding, binding_output = (
                    {"devices": [], "profiles": []}, 1, "", ""
                )
                error = str(exc)
            GLib.idle_add(finish_refresh, snapshot, binding_code, binding, binding_output, error)
        def finish_refresh(snapshot, binding_code, binding, binding_output, error):
            devices_store.clear()
            profiles_store.clear()
            combo.remove_all()
            candidates = []
            for item in snapshot["devices"]:
                devices_store.append([
                    item["name"], item["type"], item["state"], item["connection"]
                ])
                kind = item["type"].lower()
                if kind not in {"tun", "wireguard", "loopback", "vpn"}:
                    candidates.append(item)
            for item in candidates:
                combo.append(item["name"],
                             f"{item['name']} — {item['type']} ({item['state']})")
            for item in snapshot["profiles"]:
                profiles_store.append([
                    item["name"], item["type"], item["device"]
                ])
            if candidates:
                if binding_code == 0 and binding and any(
                    item["name"] == binding for item in candidates
                ):
                    combo.set_active_id(binding)
                else:
                    combo.set_active(0)
            binding_label = (
                f"Текущая привязка VPN: {binding}"
                if binding_code == 0 and binding
                else "Текущая привязка VPN: автоматический выбор"
                if binding_code == 0
                else "Текущую привязку VPN прочитать не удалось"
            )
            status.set_text(
                error or (
                    f"{binding_label}. Устройств: {len(snapshot['devices'])}; "
                    f"профилей: {len(snapshot['profiles'])}; "
                    f"кандидатов для привязки: {len(candidates)}"
                )
            )
            refresh.set_sensitive(True)
            apply.set_sensitive(bool(candidates))
            clear.set_sensitive(True)
            return False
        threading.Thread(target=worker, daemon=True).start()

    def run_command(label: str, command):
        for button in (refresh, apply, clear):
            button.set_sensitive(False)
        status.set_text(label + "…")
        def worker():
            try:
                code, output = command()
                message = f"{label}: {'успешно' if code == 0 else 'ошибка'}\n{output}"
            except Exception as exc:
                message = f"{label}: ошибка\n{exc}"
            GLib.idle_add(finish_command, message)
        def finish_command(message):
            status.set_text(message)
            refresh.set_sensitive(True)
            apply.set_sensitive(combo.get_active_id() is not None)
            clear.set_sensitive(True)
            return False
        threading.Thread(target=worker, daemon=True).start()

    def set_and_verify(selected: str):
        code, output = vpn.set_bound_interface(selected)
        if code:
            return code, output
        verify_code, actual, details = vpn.bound_interface()
        if verify_code or actual != selected:
            return 1, (
                "Команда завершилась, но проверка конфигурации не подтвердила "
                f"привязку к {selected}.\n{details}"
            )
        return 0, (output + "\nПроверено: исходящий интерфейс = " + actual).strip()

    def clear_and_verify():
        code, output = vpn.clear_bound_interface()
        if code:
            return code, output
        verify_code, actual, details = vpn.bound_interface()
        if verify_code or actual:
            return 1, "Не удалось подтвердить сброс привязки.\n" + details
        return 0, (output + "\nПроверено: автоматический выбор интерфейса.").strip()

    def do_apply():
        selected = combo.get_active_id()
        if not selected:
            return
        confirm(
            f"AdGuard VPN CLI будет настроен использовать интерфейс {selected} "
            "для исходящего VPN-соединения. Настройки NetworkManager не изменяются. "
            "Если интерфейс отключится, VPN может потерять соединение.",
            lambda: run_command(
                f"Привязка к {selected}",
                lambda: set_and_verify(selected),
            ),
        )

    def do_clear():
        confirm(
            "Будет очищено значение bound-if-override. AdGuard VPN CLI снова сможет "
            "выбирать исходящий интерфейс автоматически.",
            lambda: run_command("Снятие привязки", clear_and_verify),
        )

    refresh.connect("clicked", refresh_list)
    apply.connect("clicked", lambda _button: do_apply())
    clear.connect("clicked", lambda _button: do_clear())
    refresh_list()
    return root
