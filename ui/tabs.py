"""Notebook tab assembly."""
from modules.applications import build_applications_tab
from modules.connection import build_connection_tab
from modules.diagnostics import build_diagnostics_tab
from modules.dns import build_dns_tab
from modules.help import build_help_tab
from modules.interfaces import build_interfaces_tab
from modules.settings import build_settings_tab


def build_tabs(notebook):
    """Populate all currently available feature tabs."""
    from gi.repository import Gtk

    pages = (
        (build_connection_tab(), "Подключение"),
        (build_applications_tab(), "Приложения"),
        (build_interfaces_tab(), "Сетевые интерфейсы"),
        (build_dns_tab(), "DNS и защита"),
        (build_diagnostics_tab(), "Диагностика"),
        (build_settings_tab(), "Настройки"),
        (build_help_tab(), "Справка"),
    )
    for page, title in pages:
        notebook.append_page(page, Gtk.Label(label=title))
    return notebook
