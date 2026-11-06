"""Main GTK application window."""
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from ui.tabs import build_tabs


class MainWindow(Gtk.Window):
    def __init__(self):
        super().__init__(title="ADGuard VPN Desktop")
        self.set_default_size(900, 620)
        self.set_size_request(640, 460)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.connect("destroy", Gtk.main_quit)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        outer.set_border_width(10)
        self.add(outer)

        heading = Gtk.Label()
        heading.set_markup("<b>ADGuard VPN Desktop</b>")
        heading.set_xalign(0)
        outer.pack_start(heading, False, False, 0)

        disclaimer = Gtk.Label(
            label="Независимая графическая оболочка для официального AdGuard VPN CLI. "
                  "Не является продуктом AdGuard."
        )
        disclaimer.set_xalign(0)
        disclaimer.set_line_wrap(True)
        outer.pack_start(disclaimer, False, False, 0)

        notebook = Gtk.Notebook()
        notebook.set_scrollable(True)
        outer.pack_start(notebook, True, True, 0)
        build_tabs(notebook)


def run():
    window = MainWindow()
    window.show_all()
    Gtk.main()
