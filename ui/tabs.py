"""Notebook tab assembly."""
from modules.connection import build_connection_tab
from modules.applications import build_applications_tab
from modules.site_exclusions import build_site_exclusions_tab
from modules.dns import build_dns_tab
from modules.interfaces import build_interfaces_tab
from modules.help import build_help_tab
from modules.adguard_info import build_adguard_info_tab


def build_tabs(notebook):
    """Populate the GTK notebook with feature modules."""
    from gi.repository import Gtk

    notebook.append_page(build_connection_tab(), Gtk.Label(label="Подключение"))
    notebook.append_page(build_adguard_info_tab(), Gtk.Label(label="Инфо ADGuard"))
    notebook.append_page(build_applications_tab(), Gtk.Label(label="Приложения"))
    notebook.append_page(build_site_exclusions_tab(), Gtk.Label(label="Исключения сайтов"))
    notebook.append_page(build_interfaces_tab(), Gtk.Label(label="Сетевые интерфейсы"))
    notebook.append_page(build_dns_tab(), Gtk.Label(label="DNS и защита"))
    notebook.append_page(build_help_tab(), Gtk.Label(label="Справка"))
    return notebook
