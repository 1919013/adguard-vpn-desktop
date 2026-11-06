"""Application settings tab."""
from __future__ import annotations

from services.autostart import AutostartManager


def build_settings_tab():
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk

    manager = AutostartManager()
    root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    root.set_border_width(16)

    title = Gtk.Label()
    title.set_markup("<b>Настройки приложения</b>")
    title.set_xalign(0)
    root.pack_start(title, False, False, 0)

    description = Gtk.Label(
        label="Автозагрузка относится только к ADGuard VPN Desktop. "
              "Она не создаёт системную службу и не запускает VPN без отдельной команды."
    )
    description.set_xalign(0)
    description.set_line_wrap(True)
    root.pack_start(description, False, False, 0)

    state = Gtk.Label()
    state.set_xalign(0)
    root.pack_start(state, False, False, 0)

    def refresh():
        state.set_text(
            "Автозагрузка графической оболочки: "
            + ("включена" if manager.enabled() else "выключена")
        )

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

    row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    root.pack_start(row, False, False, 0)

    enable = Gtk.Button(label="Добавить в автозагрузку")
    disable = Gtk.Button(label="Удалить из автозагрузки")
    row.pack_start(enable, False, False, 0)
    row.pack_start(disable, False, False, 0)

    def do_enable(_button):
        try:
            manager.enable()
            refresh()
        except Exception as exc:
            report_error(exc)

    def do_disable(_button):
        try:
            manager.disable()
            refresh()
        except Exception as exc:
            report_error(exc)

    enable.connect("clicked", do_enable)
    disable.connect("clicked", do_disable)
    refresh()
    return root
