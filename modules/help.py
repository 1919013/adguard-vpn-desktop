"""Help tab and browser-openable local documentation."""
from __future__ import annotations

import webbrowser
from pathlib import Path

from config import APP_NAME


def _help_file() -> Path:
    return Path("/usr/share/doc/adguard-vpn-desktop/help.html")


def build_help_tab():
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk

    root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    root.set_border_width(16)

    title = Gtk.Label()
    title.set_markup("<b>Помощь</b>")
    title.set_xalign(0)
    root.pack_start(title, False, False, 0)

    intro = Gtk.Label(
        label=f"{APP_NAME} — сторонняя графическая оболочка для AdGuard VPN CLI. "
              "Это не официальное настольное приложение AdGuard и проект не связан с AdGuard.",
        xalign=0,
    )
    intro.set_line_wrap(True)
    intro.set_selectable(True)
    root.pack_start(intro, False, False, 0)

    content = Gtk.TextView()
    content.set_editable(False)
    content.set_cursor_visible(False)
    content.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
    content.get_buffer().set_text(
        "Краткое руководство\n\n"
        "Подключение — проверка состояния AdGuard VPN CLI, выбор сервера, подключение и отключение.\n\n"
        "Приложения — поиск установленных программ и безопасный запуск выбранного приложения через VPN. "
        "Раздельное туннелирование остаётся экспериментальной функцией: перед повседневным использованием "
        "необходимы испытания на конкретной системе.\n\n"
        "DNS и защита — просмотр статуса TUN и DNS, предварительный план и ограниченные операции "
        "только с разрешёнными тестовыми профилями NetworkManager. Отсутствующий профиль не означает "
        "повреждение системы. Чтение настроек не заменяет полноценный DNS leak test.\n\n"
        "Сетевые интерфейсы — просмотр обнаруженных устройств и интерфейса туннеля.\n\n"
        "Настройки — раздел будет расширяться в следующих версиях.\n\n"
        "Безопасность\n"
        "Не отключайте VPN во время защищённого запуска. Если проверка TUN, DNS или маршрутов не пройдена, "
        "запуск приложения через VPN должен быть заблокирован. Не вводите в отчёты пароли, токены и "
        "другие секреты.\n\n"
        "Лицензия: GPL-3.0-or-later."
    )
    scroll = Gtk.ScrolledWindow()
    scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
    scroll.set_vexpand(True)
    scroll.add(content)
    root.pack_start(scroll, True, True, 0)

    button = Gtk.Button(label="Открыть полную справку в браузере")
    def open_help(*_):
        path = _help_file()
        if path.is_file():
            webbrowser.open(path.as_uri())
        else:
            dialog = Gtk.MessageDialog(
                transient_for=root.get_toplevel(),
                flags=Gtk.DialogFlags.MODAL,
                message_type=Gtk.MessageType.WARNING,
                buttons=Gtk.ButtonsType.OK,
                text="Файл полной справки не найден",
            )
            dialog.format_secondary_text("Краткая справка доступна во вкладке. Проверьте установку пакета.")
            dialog.run()
            dialog.destroy()
    button.connect("clicked", open_help)
    root.pack_start(button, False, False, 0)
    return root
