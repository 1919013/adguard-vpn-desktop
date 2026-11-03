"""Notebook tab assembly."""
from modules.dns import build_dns_tab


def build_tabs(notebook):
    """Populate the main notebook and return it."""
    from gi.repository import Gtk

    placeholders = (
        ("Подключение", "Управление подключением VPN будет подключено следующим этапом."),
        ("Приложения", "Настройка маршрутизации отдельных приложений пока не реализована."),
        ("Настройки", "Настройки приложения будут добавлены следующим этапом."),
    )
    for title, message in placeholders:
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        page.set_border_width(16)
        label = Gtk.Label(label=message)
        label.set_xalign(0)
        label.set_line_wrap(True)
        page.pack_start(label, False, False, 0)
        notebook.append_page(page, Gtk.Label(label=title))

    notebook.append_page(build_dns_tab(), Gtk.Label(label="DNS и защита"))
    return notebook
