"""Installed desktop application catalogue (read-only).

This catalogue does not claim to route selected applications. Per-process
routing remains disabled until a system-level implementation is verified.
"""
from __future__ import annotations

import os
from pathlib import Path


def _desktop_dirs() -> list[Path]:
    roots = [Path("/usr/share"), Path("/usr/local/share")]
    roots.extend(Path(p) for p in os.environ.get("XDG_DATA_DIRS", "").split(":") if p)
    roots.append(Path.home() / ".local/share")
    result = []
    seen = set()
    for root in roots:
        directory = root / "applications"
        key = str(directory)
        if key not in seen and directory.is_dir():
            result.append(directory)
            seen.add(key)
    return result


def discover_applications() -> list[dict[str, str]]:
    found: dict[str, dict[str, str]] = {}
    for directory in _desktop_dirs():
        try:
            paths = directory.rglob("*.desktop")
            for path in paths:
                try:
                    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
                except OSError:
                    continue
                in_entry = False
                name = ""
                executable = ""
                hidden = False
                for line in lines:
                    line = line.strip()
                    if line == "[Desktop Entry]":
                        in_entry = True
                        continue
                    if line.startswith("[") and line.endswith("]"):
                        if in_entry:
                            break
                    if not in_entry or "=" not in line:
                        continue
                    key, value = line.split("=", 1)
                    if key == "Name" and not name:
                        name = value.strip()
                    elif key == "Exec":
                        executable = value.strip()
                    elif key in ("NoDisplay", "Hidden") and value.strip().lower() == "true":
                        hidden = True
                if name and executable and not hidden:
                    found.setdefault(str(path), {
                        "name": name, "exec": executable, "desktop_file": str(path)
                    })
        except OSError:
            continue
    return sorted(found.values(), key=lambda item: item["name"].casefold())


def build_applications_tab():
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk

    root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    root.set_border_width(14)
    title = Gtk.Label()
    title.set_markup("<b>Приложения</b>")
    title.set_xalign(0)
    root.pack_start(title, False, False, 0)
    warning = Gtk.Label(
        label="Ниже показан каталог установленных графических приложений. "
              "Выбор приложений для VPN пока отключён: настоящая маршрутизация "
              "процессов ещё не реализована и не должна имитироваться."
    )
    warning.set_xalign(0)
    warning.set_line_wrap(True)
    root.pack_start(warning, False, False, 0)

    search = Gtk.Entry()
    search.set_placeholder_text("Поиск приложений (без учёта регистра)")
    root.pack_start(search, False, False, 0)
    store = Gtk.ListStore(str, str, str)
    filtered = Gtk.TreeModelFilter(model=store)
    filtered.set_visible_func(lambda model, iterator, _data: _matches(model, iterator, search.get_text()))
    view = Gtk.TreeView(model=filtered)
    for index, heading in enumerate(("Приложение", "Команда запуска", "Файл .desktop")):
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

    def refresh():
        store.clear()
        apps = discover_applications()
        for app in apps:
            store.append([app["name"], app["exec"], app["desktop_file"]])
        status.set_text(f"Найдено приложений: {len(apps)}")

    search.connect("changed", lambda _entry: filtered.refilter())
    refresh()
    return root


def _matches(model, iterator, query: str) -> bool:
    needle = query.casefold().strip()
    if not needle:
        return True
    return any(needle in str(model.get_value(iterator, column)).casefold()
               for column in (0, 1, 2))
