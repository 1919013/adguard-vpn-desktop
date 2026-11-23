"""Network interfaces tab with safe, read-only discovery."""
from __future__ import annotations

import threading

from services.interface_manager import InterfaceManager


def build_interfaces_tab(manager: InterfaceManager | None = None):
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk, GLib

    manager = manager or InterfaceManager()
    root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=9)
    root.set_border_width(14)

    title = Gtk.Label()
    title.set_markup("<b>Сетевые интерфейсы</b>")
    title.set_xalign(0)
    root.pack_start(title, False, False, 0)

    current = Gtk.Label(label="Текущий интерфейс AdGuard VPN: проверка…", xalign=0)
    current.set_line_wrap(True)
    current.set_selectable(True)
    root.pack_start(current, False, False, 0)

    note = Gtk.Label(
        label=("Отметьте интерфейсы для дальнейшей настройки. На этом этапе список "
               "только обнаруживает устройства: маршруты, DNS и настройки NetworkManager "
               "не изменяются."),
        xalign=0,
    )
    note.set_line_wrap(True)
    root.pack_start(note, False, False, 0)

    scroller = Gtk.ScrolledWindow()
    scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
    scroller.set_vexpand(True)
    root.pack_start(scroller, True, True, 0)
    list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    list_box.set_border_width(6)
    scroller.add(list_box)

    footer = Gtk.Label(label="Выбор действует только до закрытия окна; применение маршрутизации ещё не включено.", xalign=0)
    footer.set_line_wrap(True)
    root.pack_start(footer, False, False, 0)

    refresh = Gtk.Button(label="Обновить интерфейсы и статус")
    root.pack_start(refresh, False, False, 0)

    def refresh_data(*_):
        refresh.set_sensitive(False)
        current.set_text("Проверка текущего интерфейса AdGuard VPN…")
        for child in list_box.get_children():
            list_box.remove(child)
        list_box.pack_start(Gtk.Label(label="Обнаружение сетевых устройств…", xalign=0), False, False, 0)
        list_box.show_all()

        def worker():
            try:
                interfaces = manager.list_interfaces()
                path = manager.adguard_path()
                GLib.idle_add(show_data, interfaces, path, None)
            except Exception as exc:
                GLib.idle_add(show_data, [], None, str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def show_data(interfaces, path, error):
        refresh.set_sensitive(True)
        for child in list_box.get_children():
            list_box.remove(child)
        if error:
            current.set_text("Не удалось определить состояние сети: " + error)
        else:
            if path["connected"]:
                current.set_text("AdGuard VPN подключён. Туннельный интерфейс: " + path["interface"])
            else:
                current.set_text("AdGuard VPN не подтверждён как подключённый. " + path["detail"])
            if not interfaces:
                list_box.pack_start(Gtk.Label(label="Сетевые интерфейсы не обнаружены.", xalign=0), False, False, 0)
            for item in interfaces:
                addresses = ", ".join(item["addresses"]) if item["addresses"] else "IP-адреса не назначены"
                label = (
                    f'{item["name"]}  [{item["state"]}]  ·  {item["kind"]}\n'
                    f'{addresses}\nNetworkManager: {item["network_manager"]}'
                )
                check = Gtk.CheckButton(label=label)
                check.set_tooltip_text("Выбор устройства для будущей настройки маршрутизации")
                list_box.pack_start(check, False, False, 0)
        list_box.show_all()
        return False

    refresh.connect("clicked", refresh_data)
    refresh_data()
    return root
