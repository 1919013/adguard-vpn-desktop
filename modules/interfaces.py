"""Dynamic, read-only network interface tab."""
from __future__ import annotations

import threading

from services.network_manager import NetworkManagerService


def build_interfaces_tab(service: NetworkManagerService | None = None):
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk, GLib

    service = service or NetworkManagerService()
    root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    root.set_border_width(14)
    title = Gtk.Label()
    title.set_markup("<b>Сетевые интерфейсы</b>")
    title.set_xalign(0)
    root.pack_start(title, False, False, 0)
    note = Gtk.Label(
        label="Список обнаруживается автоматически на этом компьютере. "
              "Просмотр не меняет маршруты и профили NetworkManager."
    )
    note.set_xalign(0)
    note.set_line_wrap(True)
    root.pack_start(note, False, False, 0)
    store = Gtk.ListStore(str, str, str, str)
    view = Gtk.TreeView(model=store)
    for index, heading in enumerate(("Интерфейс", "Тип", "Состояние", "Профиль")):
        renderer = Gtk.CellRendererText()
        column = Gtk.TreeViewColumn(heading, renderer, text=index)
        column.set_resizable(True)
        view.append_column(column)
    scroll = Gtk.ScrolledWindow()
    scroll.set_vexpand(True)
    scroll.add(view)
    root.pack_start(scroll, True, True, 0)
    status = Gtk.Label()
    status.set_xalign(0)
    root.pack_start(status, False, False, 0)
    refresh = Gtk.Button(label="Обновить список")
    root.pack_start(refresh, False, False, 0)

    def load(_button=None):
        refresh.set_sensitive(False)
        status.set_text("Обнаружение интерфейсов…")
        def worker():
            try:
                devices = service.devices()
                error = None
            except Exception as exc:
                devices, error = [], str(exc)
            GLib.idle_add(finish, devices, error)
        def finish(devices, error):
            store.clear()
            for item in devices:
                store.append([item["name"], item["type"], item["state"], item["connection"]])
            status.set_text(error or f"Обнаружено интерфейсов: {len(devices)}")
            refresh.set_sensitive(True)
            return False
        threading.Thread(target=worker, daemon=True).start()

    refresh.connect("clicked", load)
    load()
    return root
