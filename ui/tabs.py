"""Notebook tab assembly."""
from modules.applications import build_applications_tab
from modules.connection import build_connection_tab
from modules.dns import build_dns_tab
from modules.interfaces import build_interfaces_tab


def build_tabs(notebook):
    """Populate the main notebook and return it."""
    from gi.repository import Gtk

    notebook.append_page(build_connection_tab(), Gtk.Label(label="Подключение"))

    notebook.append_page(build_applications_tab(), Gtk.Label(label="Приложения"))

    page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    page.set_border_width(16)
    label = Gtk.Label(label="Настройки приложения будут добавлены следующим этапом.")
    label.set_xalign(0)
    label.set_line_wrap(True)
    page.pack_start(label, False, False, 0)
    notebook.append_page(page, Gtk.Label(label="Настройки"))

    notebook.append_page(build_dns_tab(), Gtk.Label(label="DNS и защита"))
    notebook.append_page(build_interfaces_tab(), Gtk.Label(label="Сетевые интерфейсы"))
    return notebook
