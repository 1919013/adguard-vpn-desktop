"""Application and VPN CLI autostart settings."""
from __future__ import annotations

from services.autostart import AutostartManager, VPNCLIAutostartManager


def build_settings_tab():
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk

    gui_manager = AutostartManager()
    vpn_manager = VPNCLIAutostartManager()
    root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
    root.set_border_width(16)

    title = Gtk.Label()
    title.set_markup("<b>Настройки приложения и VPN</b>")
    title.set_xalign(0)
    root.pack_start(title, False, False, 0)

    gui_heading = Gtk.Label()
    gui_heading.set_markup("<b>Автозагрузка графической оболочки</b>")
    gui_heading.set_xalign(0)
    root.pack_start(gui_heading, False, False, 0)
    gui_note = Gtk.Label(
        label="Запускает только ADGuard VPN Desktop при входе в графический сеанс."
    )
    gui_note.set_xalign(0)
    gui_note.set_line_wrap(True)
    root.pack_start(gui_note, False, False, 0)
    gui_state = Gtk.Label()
    gui_state.set_xalign(0)
    root.pack_start(gui_state, False, False, 0)

    gui_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    root.pack_start(gui_row, False, False, 0)
    gui_enable = Gtk.Button(label="Добавить GUI в автозагрузку")
    gui_disable = Gtk.Button(label="Удалить GUI из автозагрузки")
    gui_row.pack_start(gui_enable, False, False, 0)
    gui_row.pack_start(gui_disable, False, False, 0)

    separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
    root.pack_start(separator, False, False, 2)

    vpn_heading = Gtk.Label()
    vpn_heading.set_markup("<b>Автоподключение AdGuard VPN CLI</b>")
    vpn_heading.set_xalign(0)
    root.pack_start(vpn_heading, False, False, 0)
    vpn_note = Gtk.Label(
        label="Создаёт отдельную пользовательскую запись автозагрузки, которая "
              "запускает «adguardvpn-cli connect --boot» при входе в систему. "
              "Параметр --boot включает повторное подключение при обрыве туннеля. "
              "Для этого необходимы установленный CLI и выполненный вход в аккаунт."
    )
    vpn_note.set_xalign(0)
    vpn_note.set_line_wrap(True)
    root.pack_start(vpn_note, False, False, 0)
    vpn_state = Gtk.Label()
    vpn_state.set_xalign(0)
    root.pack_start(vpn_state, False, False, 0)

    vpn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    root.pack_start(vpn_row, False, False, 0)
    vpn_enable = Gtk.Button(label="Включить автоподключение VPN")
    vpn_disable = Gtk.Button(label="Отключить автоподключение VPN")
    vpn_row.pack_start(vpn_enable, False, False, 0)
    vpn_row.pack_start(vpn_disable, False, False, 0)

    note = Gtk.Label(
        label="Эти настройки относятся к пользовательскому графическому сеансу, "
              "а не к системной службе systemd. Отключение автозагрузки удаляет "
              "только соответствующий файл .desktop; настройки VPN и учётная запись не удаляются."
    )
    note.set_xalign(0)
    note.set_line_wrap(True)
    root.pack_start(note, False, False, 0)

    def report_error(error):
        dialog = Gtk.MessageDialog(
            transient_for=root.get_toplevel() if isinstance(root.get_toplevel(), Gtk.Window) else None,
            flags=Gtk.DialogFlags.MODAL,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.CLOSE,
            text="Не удалось изменить автозагрузку",
        )
        dialog.format_secondary_text(str(error))
        dialog.run()
        dialog.destroy()

    def refresh():
        gui_state.set_text(
            "Автозагрузка GUI: " + ("включена" if gui_manager.enabled() else "выключена")
        )
        vpn_state.set_text(
            "Автоподключение VPN CLI: " + ("включено" if vpn_manager.enabled() else "выключено")
        )

    def enable_gui(_button):
        try:
            gui_manager.enable()
            refresh()
        except Exception as exc:
            report_error(exc)

    def disable_gui(_button):
        try:
            gui_manager.disable()
            refresh()
        except Exception as exc:
            report_error(exc)

    def enable_vpn(_button):
        try:
            vpn_manager.enable()
            refresh()
        except Exception as exc:
            report_error(exc)

    def disable_vpn(_button):
        try:
            vpn_manager.disable()
            refresh()
        except Exception as exc:
            report_error(exc)

    gui_enable.connect("clicked", enable_gui)
    gui_disable.connect("clicked", disable_gui)
    vpn_enable.connect("clicked", enable_vpn)
    vpn_disable.connect("clicked", disable_vpn)
    refresh()
    return root
