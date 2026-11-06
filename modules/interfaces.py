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
    root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    root.set_border_width(14)

    title = Gtk.Label()
    title.set_markup("<b>Сетевые интерфейсы</b>")
    title.set_xalign(0)
    root.pack_start(title, False, False, 0)

    note = Gtk.Label(
        label="Устройства обнаруживаются автоматически. AdGuard VPN CLI поддерживает "
              "привязку исходящего VPN-соединения к одному сетевому интерфейсу. "
              "Это настройка CLI, а не изменение профиля NetworkManager."
    )
    note.set_xalign(0)
    note.set_line_wrap(True)
    root.pack_start(note, False, False, 0)

    combo = Gtk.ComboBoxText()
    combo.set_hexpand(True)
    root.pack_start(combo, False, False, 0)

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

    def show_error(title_text: str, detail: str):
        dialog = Gtk.MessageDialog(
            transient_for=root.get_toplevel() if isinstance(root.get_toplevel(), Gtk.Window) else None,
            flags=Gtk.DialogFlags.MODAL,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.CLOSE,
            text=title_text,
        )
        dialog.format_secondary_text(detail)
        dialog.run()
        dialog.destroy()

    def refresh_list(_button=None):
        refresh.set_sensitive(False)
        apply.set_sensitive(False)
        status.set_text("Обнаружение устройств NetworkManager…")
        def worker():
            try:
                devices = network.devices()
                error = None
            except Exception as exc:
                devices, error = [], str(exc)
            GLib.idle_add(finish_refresh, devices, error)
        def finish_refresh(devices, error):
            combo.remove_all()
            for item in devices:
                label = f"{item['name']} — {item['type']} ({item['state']})"
                combo.append(item["name"], label)
            if devices:
                combo.set_active(0)
            status.set_text(error or f"Обнаружено интерфейсов: {len(devices)}")
            refresh.set_sensitive(True)
            apply.set_sensitive(bool(devices))
            return False
        threading.Thread(target=worker, daemon=True).start()

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

    def do_apply():
        selected = combo.get_active_id()
        if not selected:
            return
        confirm(
            f"AdGuard VPN CLI будет настроен использовать интерфейс {selected} "
            "для исходящего VPN-соединения. Настройки NetworkManager не изменяются. "
            "При недоступности выбранного интерфейса VPN может не подключиться.",
            lambda: run_command(
                f"Привязка к {selected}",
                lambda: vpn.set_bound_interface(selected),
            ),
        )

    def do_clear():
        confirm(
            "Будет очищено значение bound-if-override. AdGuard VPN CLI снова сможет "
            "выбирать исходящий интерфейс автоматически.",
            lambda: run_command("Снятие привязки", vpn.clear_bound_interface),
        )

    refresh.connect("clicked", refresh_list)
    apply.connect("clicked", lambda _button: do_apply())
    clear.connect("clicked", lambda _button: do_clear())
    clear.set_sensitive(True)
    refresh_list()
    return root
