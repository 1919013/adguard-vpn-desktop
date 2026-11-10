"""Notebook tab assembly."""
from modules.connection import build_connection_tab
from modules.dns import build_dns_tab
from modules.interfaces import build_interfaces_tab
from modules.help import build_help_tab


def build_tabs(notebook):
    """Populate all implemented feature tabs."""
    from gi.repository import Gtk

    notebook.append_page(build_connection_tab(), Gtk.Label(label="Подключение"))

    # These remain explicit placeholders until their feature blocks are implemented.
    for title, message in (
        ("Приложения", "Маршрутизация отдельных приложений будет доступна после проверки возможностей AdGuard VPN CLI."),
        ("Настройки", "Настройки приложения будут добавлены следующим этапом."),
    ):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        page.set_border_width(16)
        label = Gtk.Label(label=message)
        label.set_xalign(0)
        label.set_line_wrap(True)
        page.pack_start(label, False, False, 0)
        notebook.append_page(page, Gtk.Label(label=title))

    notebook.append_page(build_interfaces_tab(), Gtk.Label(label="Сетевые интерфейсы"))
    notebook.append_page(build_dns_tab(), Gtk.Label(label="DNS и защита"))
    notebook.append_page(build_help_tab(), Gtk.Label(label="Справка"))
    return notebook
