"""GTK application catalog for the split-tunneling workflow.

The selected list is persisted locally, but is not yet applied to VPN routing.
"""
from __future__ import annotations

import threading

from services.application_selection import load_selection, save_selection
from services.split_tunnel_runtime import SplitTunnelRuntime
from services.desktop_applications import (
    custom_application_from_path,
    discover_applications,
    filter_applications,
)


def build_applications_tab():
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk, GLib

    root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    root.set_border_width(14)
    title = Gtk.Label()
    title.set_markup("<b>Приложения</b>")
    title.set_xalign(0)
    root.pack_start(title, False, False, 0)

    note = Gtk.Label(
        label=("Выбери режим маршрутизации. Режим «Все приложения» использует системный режим "
               "маршрутизации AdGuard VPN CLI. Режим «Избранные приложения» запускает выбранные "
               "программы в отдельных защищённых группах процессов."),
        xalign=0,
    )
    note.set_line_wrap(True)
    root.pack_start(note, False, False, 0)

    mode_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
    all_mode = Gtk.RadioButton.new_with_label_from_widget(None, "Все приложения через AdGuard")
    selected_mode = Gtk.RadioButton.new_with_label_from_widget(all_mode, "Избранные приложения через AdGuard")
    mode_box.pack_start(all_mode, False, False, 0)
    mode_box.pack_start(selected_mode, False, False, 0)
    root.pack_start(mode_box, False, False, 0)

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
    summary.set_line_wrap(True)
    summary.set_selectable(True)
    summary_scroll = Gtk.ScrolledWindow()
    summary_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
    summary_scroll.set_min_content_height(48)
    summary_scroll.set_max_content_height(100)
    summary_scroll.add(summary)
    root.pack_start(summary_scroll, False, False, 0)
    applications = []
    selected = set()
    custom_paths = set()
    runtime = SplitTunnelRuntime()
    launching = False
    active_app_id = None
    stop_requested = False
    launch_controls = {}
    routing_mode = "selected"

    def update_mode_visibility():
        show_selection = routing_mode == "selected"
        for widget in (search, custom_row, actions, scroller):
            widget.set_visible(show_selection)
        if routing_mode == "all":
            summary.set_text(
                "Режим «Все приложения через AdGuard» выбран. "
                "Для фактической маршрутизации всего трафика AdGuard VPN CLI должен работать "
                "в системном режиме маршрутизации AUTO. Этот интерфейс пока не переключает "
                "режим CLI автоматически."
            )
        else:
            summary.set_text(
                f"Режим «Избранные приложения через AdGuard». Выбрано: {len(selected)}"
            )

    def on_mode_toggled(widget):
        nonlocal routing_mode
        if not widget.get_active():
            return
        routing_mode = "all" if widget is all_mode else "selected"
        try:
            save_selection(selected, custom_paths, mode=routing_mode)
        except (OSError, ValueError) as exc:
            summary.set_text("Не удалось сохранить режим: " + str(exc))
            return
        update_mode_visibility()
        if routing_mode == "selected":
            render()

    all_mode.connect("toggled", on_mode_toggled)
    selected_mode.connect("toggled", on_mode_toggled)

    def refresh_launch_controls():
        for desktop_id, pair in launch_controls.items():
            launch_button, stop_button = pair
            launch_button.set_sensitive(not launching and desktop_id in selected)
            stop_button.set_sensitive(
                launching and desktop_id == active_app_id and not stop_requested
            )

    def launch_application(app):
        nonlocal launching, active_app_id, stop_requested
        if app.desktop_id not in selected:
            summary.set_text("Сначала отметь приложение флажком.")
            return
        if launching:
            summary.set_text("Дождись завершения текущего запуска: пока поддерживается один активный процесс.")
            return
        launching = True
        active_app_id = app.desktop_id
        stop_requested = False
        refresh_launch_controls()
        summary.set_text(f"Подготовка безопасного запуска {app.name}…")

        def worker():
            try:
                code = runtime.launch(app)
                message = f"{app.name}: завершено (код {code}). Правила маршрутизации очищены."
            except Exception as exc:
                message = f"{app.name}: запуск отменён. {exc}"
            GLib.idle_add(finish_launch, message)

        threading.Thread(target=worker, name="adguard-split-tunnel-launch", daemon=True).start()

    def finish_launch(message):
        nonlocal launching, active_app_id, stop_requested
        launching = False
        active_app_id = None
        stop_requested = False
        summary.set_text(message)
        refresh_launch_controls()
        return False

    def stop_application_routing(app):
        nonlocal stop_requested
        if not launching or active_app_id != app.desktop_id:
            summary.set_text("Для этого приложения сейчас нет активной VPN-маршрутизации.")
            return
        if stop_requested:
            return
        stop_requested = True
        refresh_launch_controls()
        summary.set_text(
            f"Отключение VPN-маршрутизации для {app.name}… "
            "Само приложение останется запущенным."
        )

        def worker():
            try:
                runtime.stop_routing()
                GLib.idle_add(
                    finish_stop_routing,
                    f"{app.name}: VPN-маршрутизация прекращена. Приложение продолжает работать."
                )
            except Exception as exc:
                GLib.idle_add(finish_stop_routing, f"Не удалось отключить VPN-маршрутизацию: {exc}", True)

        threading.Thread(target=worker, name="adguard-split-tunnel-stop", daemon=True).start()

    def finish_stop_routing(message, failed=False):
        nonlocal stop_requested
        if failed:
            stop_requested = False
        summary.set_text(message)
        refresh_launch_controls()
        return False

    def persist():
        try:
            save_selection(selected, custom_paths, mode=routing_mode)
        except (OSError, ValueError) as exc:
            summary.set_text("Не удалось сохранить выбор приложений: " + str(exc))

    def on_toggle(widget, desktop_id):
        if widget.get_active():
            selected.add(desktop_id)
        else:
            selected.discard(desktop_id)
        persist()
        refresh_launch_controls()
        summary.set_text(f"Найдено: {len(applications)} · Выбрано: {len(selected)}")

    def render(*_):
        launch_controls.clear()
        for child in rows.get_children():
            rows.remove(child)
        visible = filter_applications(applications, search.get_text())
        for app in visible:
            details = "Flatpak" if app.flatpak else "Системное приложение"
            if app.dbus_activatable:
                details += " · D-Bus activation (пока не поддерживается)"
            line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            check = Gtk.CheckButton(label=f"{app.name} — {details}\\n{app.desktop_id}")
            check.set_active(app.desktop_id in selected)
            check.connect("toggled", on_toggle, app.desktop_id)
            line.pack_start(check, True, True, 0)
            launch_button = Gtk.Button(label="Запустить через VPN")
            launch_button.connect("clicked", lambda _button, item=app: launch_application(item))
            launch_button.set_sensitive(app.desktop_id in selected and not launching and not app.dbus_activatable)
            if app.dbus_activatable:
                launch_button.set_tooltip_text("D-Bus activation пока не поддерживается")
            stop_button = Gtk.Button(label="Прекратить работу приложения через VPN")
            stop_button.set_tooltip_text(
                "Удалить правила VPN-маршрутизации, не завершая работу приложения"
            )
            stop_button.connect(
                "clicked", lambda _button, item=app: stop_application_routing(item)
            )
            stop_button.set_sensitive(
                launching and app.desktop_id == active_app_id and not stop_requested
            )
            launch_controls[app.desktop_id] = (launch_button, stop_button)
            line.pack_start(launch_button, False, False, 0)
            line.pack_start(stop_button, False, False, 0)
            rows.pack_start(line, False, False, 0)
        if not visible:
            rows.pack_start(Gtk.Label(label="Приложения не найдены.", xalign=0), False, False, 0)
        rows.show_all()
        summary.set_text(
            f"Найдено: {len(applications)} · Показано: {len(visible)} · Выбрано: {len(selected)}"
        )

    def load(*_):
        nonlocal applications
        try:
            saved = load_selection()
            custom_paths.clear()
            custom_paths.update(saved["custom_paths"])
            discovered = discover_applications()
            custom_apps = []
            valid_custom_paths = set()
            for path in sorted(custom_paths):
                try:
                    custom_apps.append(custom_application_from_path(path))
                    valid_custom_paths.add(path)
                except Exception:
                    continue
            custom_paths.intersection_update(valid_custom_paths)
            applications = discovered + custom_apps
            applications.sort(key=lambda item: (item.name.casefold(), item.desktop_id.casefold()))
            known_ids = {app.desktop_id for app in applications}
            selected.clear()
            selected.update(set(saved["selected_ids"]) & known_ids)
            nonlocal_mode = saved.get("mode", "selected")
            if nonlocal_mode not in ("all", "selected"):
                nonlocal_mode = "selected"
            nonlocal routing_mode
            routing_mode = nonlocal_mode
            all_mode.set_active(routing_mode == "all")
            selected_mode.set_active(routing_mode == "selected")
            update_mode_visibility()
            if custom_paths != set(saved["custom_paths"]):
                persist()
            render()
        except Exception as exc:
            summary.set_text("Не удалось загрузить каталог или сохранённый выбор: " + str(exc))

    def add_custom_path(*_):
        try:
            app = custom_application_from_path(custom_path.get_text())
            applications[:] = [item for item in applications if item.desktop_id != app.desktop_id]
            applications.append(app)
            applications.sort(key=lambda item: (item.name.casefold(), item.desktop_id.casefold()))
            custom_paths.add(app.source)
            selected.add(app.desktop_id)
            custom_path.set_text("")
            persist()
            render()
        except Exception as exc:
            summary.set_text("Не удалось добавить приложение: " + str(exc))

    def choose_all(*_):
        selected.update(app.desktop_id for app in filter_applications(applications, search.get_text()))
        persist()
        render()

    def clear_selection(*_):
        selected.clear()
        persist()
        render()

    search.connect("search-changed", render)
    add_custom.connect("clicked", add_custom_path)
    select_all.connect("clicked", choose_all)
    clear_button.connect("clicked", clear_selection)
    refresh.connect("clicked", load)
    load()
    return root
