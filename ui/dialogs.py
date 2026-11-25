"""Reusable GTK dialogs with scrollable, selectable long messages."""
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk


def show_scrolled_message(parent, title, body, message_type=Gtk.MessageType.INFO):
    """Show a movable, resizable dialog whose long body is always scrollable."""
    dialog = Gtk.Dialog(title=title, transient_for=parent, flags=Gtk.DialogFlags.MODAL)
    dialog.set_modal(True)
    dialog.set_resizable(True)
    dialog.set_decorated(True)
    dialog.set_default_size(680, 420)
    dialog.set_position(Gtk.WindowPosition.CENTER_ON_PARENT)
    dialog.add_button("Закрыть", Gtk.ResponseType.CLOSE)

    content = dialog.get_content_area()
    content.set_spacing(8)
    content.set_border_width(12)

    heading = Gtk.Label()
    heading.set_xalign(0)
    heading.set_line_wrap(True)
    heading.set_markup("<b>" + GLib.markup_escape_text(str(title)) + "</b>")
    content.pack_start(heading, False, False, 0)

    view = Gtk.TextView()
    view.set_editable(False)
    view.set_cursor_visible(True)
    view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
    view.set_monospace(True)
    view.set_left_margin(8)
    view.set_right_margin(8)
    view.get_buffer().set_text(str(body or "Нет дополнительной информации."))
    scroll = Gtk.ScrolledWindow()
    scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
    scroll.set_min_content_width(480)
    scroll.set_min_content_height(220)
    scroll.set_hexpand(True)
    scroll.set_vexpand(True)
    scroll.add(view)
    content.pack_start(scroll, True, True, 0)

    dialog.show_all()
    response = dialog.run()
    dialog.destroy()
    return response


from gi.repository import GLib
