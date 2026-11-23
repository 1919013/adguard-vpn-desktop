"""GTK application catalog for the split-tunneling workflow.

This view is deliberately transparent: it discovers apps and keeps a temporary
selection, but does not yet claim to route them through the VPN.
"""
from __future__ import annotations

from services.desktop_applications import (\n    custom_application_from_path, discover_applications, filter_applications,\n)


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
    note = Gtk.Label(
        label=("Каталог программ Debian и Flatpak. Отметки пока являются предварительным "
               "выбором: раздельная маршрутизация будет включена после завершения проверок "
               "DNS, polkit и запуска приложений в отдельных systemd scope."),
        xalign=0,
    )
    note.set_line_wrap(True)
    root.pack_start(note, False, False, 0)
    search = Gtk.SearchEntry()
    search.set_placeholder_text("Поиск по началу названия: например, tel")
    root.pack_start(search, False, False, 0)

    custom_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    custom_path = Gtk.Entry()
    custom_path.set_placeholder_text("Полный путь к программе, например /opt/app/bin/app")
    custom_row.pack_start(custom_path, True, True, 0)
    add_custom = Gtk.Button(label="Добавить путь")
    custom_row.pack_start(add_custom, False, False, 0)
    root.pack_start(custom_row, False, False, 0)

    actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    select_all = Gtk.Button(label="Выбрать все")
    clear_button = Gtk.Button(label="Снять все")
    refresh = Gtk.Button(label="Обновить список")
    for button in (select_all, clear_button, refresh):
        actions.pack_start(button, False, False, 0)
    root.pack_start(actions, False, False, 0)
    scroller = Gtk.ScrolledWindow()
    scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
    scroller.set_vexpand(True)
    root.pack_start(scroller, True, True, 0)
    rows = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
    rows.set_border_width(5)
    scroller.add(rows)
    summary = Gtk.Label(label="Загрузка каталога приложений…", xalign=0)
    root.pack_start(summary, False, False, 0)
    applications = []
    selected = set()

    def on_toggle(widget, desktop_id):
        if widget.get_active():
            selected.add(desktop_id)
        else:
            selected.discard(desktop_id)
        summary.set_text(f"Найдено: {len(applications)} · Выбрано: {len(selected)}")

    def render(*_):
        for child in rows.get_children():
            rows.remove(child)
        visible = filter_applications(applications, search.get_text())
        for app in visible:
            details = "Flatpak" if app.flatpak else "Системное приложение"
            if app.dbus_activatable:
                details += " · D-Bus activation (нужно перезапустить приложение)"
            check = Gtk.CheckButton(label=f"{app.name} — {details}\n{app.desktop_id}")
            check.set_active(app.desktop_id in selected)
            check.connect("toggled", on_toggle, app.desktop_id)
            rows.pack_start(check, False, False, 0)
        if not visible:
            rows.pack_start(Gtk.Label(label="Приложения не найдены.", xalign=0), False, False, 0)
        rows.show_all()
        summary.set_text(f"Найдено: {len(applications)} · Показано: {len(visible)} · Выбрано: {len(selected)}")

    def load(*_):
        nonlocal applications
        try:
            applications = discover_applications()
            selected.intersection_update({app.desktop_id for app in applications})
            render()
        except Exception as exc:
            summary.set_text("Не удалось прочитать каталог приложений: " + str(exc))

    def add_custom_path(*_):
        try:
            app = custom_application_from_path(custom_path.get_text())
            applications = [item for item in applications if item.desktop_id != app.desktop_id]
            applications.append(app)
            applications.sort(key=lambda item: (item.name.casefold(), item.desktop_id.casefold()))
            selected.add(app.desktop_id)
            custom_path.set_text("")
            render()
        except Exception as exc:
            summary.set_text("Не удалось добавить приложение: " + str(exc))

    def choose_all(*_):
        selected.update(app.desktop_id for app in filter_applications(applications, search.get_text()))
        render()

    def clear_selection(*_):
        selected.clear()
        render()

    search.connect("search-changed", render)
    add_custom.connect("clicked", add_custom_path)\n    select_all.connect("clicked", choose_all)
    clear_button.connect("clicked", clear_selection)
    refresh.connect("clicked", load)
    load()
    return root
