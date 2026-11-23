"""Reusable fixed-size, scrollable GTK dialogs.

Long command output stays inside a scroller; action buttons remain visible and
the main application window is never resized to fit the message.
"""


def _build_dialog(parent, title, message, message_type, accept_label=None):
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk

    dialog = Gtk.Dialog(
        title=title,
        transient_for=parent if isinstance(parent, Gtk.Window) else None,
        flags=Gtk.DialogFlags.MODAL,
    )
    dialog.set_default_size(620, 420)
    dialog.set_resizable(True)
    content = dialog.get_content_area()
    content.set_spacing(8)
    if message_type is not None:
        image = Gtk.Image.new_from_icon_name(
            {
                Gtk.MessageType.INFO: "dialog-information",
                Gtk.MessageType.WARNING: "dialog-warning",
                Gtk.MessageType.ERROR: "dialog-error",
                Gtk.MessageType.QUESTION: "dialog-question",
            }.get(message_type, "dialog-information"),
            Gtk.IconSize.DIALOG,
        )
        heading = Gtk.Label()
        heading.set_markup("<b>" + Gtk.utils_escape(title) + "</b>" if hasattr(Gtk, "utils_escape") else "")
        # Keep the title in the native window title; no markup is needed here.
        row = Gtk.Box(spacing=12)
        row.pack_start(image, False, False, 4)
        content.pack_start(row, False, False, 4)

    view = Gtk.TextView()
    view.set_editable(False)
    view.set_cursor_visible(False)
    view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
    view.set_left_margin(8)
    view.set_right_margin(8)
    view.set_top_margin(8)
    view.set_bottom_margin(8)
    view.get_buffer().set_text(str(message or "Нет дополнительной информации."))
    scroll = Gtk.ScrolledWindow()
    scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
    scroll.set_min_content_height(180)
    scroll.set_max_content_height(320)
    scroll.set_vexpand(True)
    scroll.add(view)
    content.pack_start(scroll, True, True, 0)

    if accept_label is None:
        dialog.add_button("Закрыть", Gtk.ResponseType.OK)
    else:
        dialog.add_button("Отмена", Gtk.ResponseType.CANCEL)
        dialog.add_button(accept_label, Gtk.ResponseType.OK)
        dialog.set_default_response(Gtk.ResponseType.CANCEL)
    dialog.show_all()
    return dialog


def show_message_dialog(parent, title, message, message_type=None):
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk

    dialog = _build_dialog(parent, title, message, message_type)
    response = dialog.run()
    dialog.destroy()
    return response


def confirm_dialog(parent, title, message, accept_label="Продолжить", message_type=None):
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk

    dialog = _build_dialog(parent, title, message, message_type or Gtk.MessageType.WARNING, accept_label)
    response = dialog.run()
    dialog.destroy()
    return response == Gtk.ResponseType.OK
