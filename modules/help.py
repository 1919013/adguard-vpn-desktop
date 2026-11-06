"""Open bundled HTML help in the user's default browser."""
from __future__ import annotations

import webbrowser
from pathlib import Path


def help_file(language: str = "ru") -> Path:
    language = "en" if language.lower().startswith("en") else "ru"
    return Path(__file__).resolve().parents[1] / "docs" / language / "index.html"


def open_help(language: str = "ru") -> bool:
    target = help_file(language)
    if not target.is_file():
        return False
    return bool(webbrowser.open(target.as_uri()))


def build_help_tab():
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk

    root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    root.set_border_width(16)
    title = Gtk.Label()
    title.set_markup("<b>Справка</b>")
    title.set_xalign(0)
    root.pack_start(title, False, False, 0)
    note = Gtk.Label(
        label="Полное руководство открывается в браузере по умолчанию. "
              "В нём описаны назначение программы, ограничения и безопасное использование."
    )
    note.set_xalign(0)
    note.set_line_wrap(True)
    root.pack_start(note, False, False, 0)

    row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    root.pack_start(row, False, False, 0)
    button_ru = Gtk.Button(label="Открыть справку (русский)")
    button_en = Gtk.Button(label="Open help (English)")
    row.pack_start(button_ru, False, False, 0)
    row.pack_start(button_en, False, False, 0)
    status = Gtk.Label()
    status.set_xalign(0)
    root.pack_start(status, False, False, 0)

    def open_language(language):
        if open_help(language):
            status.set_text("Справка передана браузеру.")
        else:
            status.set_text("Файл справки не найден. Переустановите или обновите приложение.")

    button_ru.connect("clicked", lambda _button: open_language("ru"))
    button_en.connect("clicked", lambda _button: open_language("en"))
    return root
