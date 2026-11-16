"""Interactive help pages opened in the user's default browser."""
from __future__ import annotations

import html
import tempfile
import webbrowser
from pathlib import Path


def build_help_html() -> str:
    sections = [
        ("Подключение", "На вкладке «Подключение» загрузите список серверов, выберите местоположение и подключитесь. Состояние отображается по ответу adguardvpn-cli."),
        ("Инфо ADGuard", "Эта вкладка управляет официальным AdGuard VPN CLI (adguardvpn-cli): проверка версии и обновлений, установка, обновление, подключение/отключение, очистка пользовательского кэша и данных, автозапуск VPN CLI при входе в графическую сессию (connect --boot), а также установка и автозапуск самой графической оболочки. Это не отдельный AdGuard CLI — блокировщик рекламы."),
        ("Приложения", "Вкладка «Приложения» поддерживает два режима TUN/SCRIPT: «Только выбранные приложения через VPN» и «Все приложения через VPN, кроме выбранных». Вкладка реализует два режима TUN/SCRIPT. «Только выбранные» направляет через VPN приложения, запущенные из созданных ярлыков в отдельной systemd slice; «Все, кроме выбранных» направляет через VPN пользовательскую systemd-сессию, а выбранные ярлыки отправляет напрямую. nftables socket cgroupv2 помечает сокеты, а ip rule направляет помеченные пакеты через отдельную таблицу IPv4/IPv6. Основной маршрут по умолчанию не заменяется; частные, link-local, CGNAT и multicast-адреса остаются в основной таблице для локальной сети. Перед изменением или отключением разорвите VPN-соединение; после применения переподключитесь. Уже работающие приложения нужно закрыть и запустить через новые ярлыки. Flatpak/Snap и raw/ICMP пока не поддерживаются или не проверены. DNS не разделяется по приложениям: systemd-resolved направляется через VPN в обоих режимах. Фоновый наблюдатель очищает правила при удалении TUN-интерфейса, поскольку CLI не предоставляет отдельный teardown callback. Функция прошла автоматические тесты, но ещё требует проверки на Debian 13/Cinnamon."),
        ("Исключения сайтов", "Списки сайтов управляются штатной командой adguardvpn-cli site-exclusions. CLI использует один список сайтов и один активный режим. General: сайты из списка идут напрямую, вне VPN. Selective: через VPN идут только сайты из списка. Список сайтов независим от выбора приложений. Если браузер исключён из VPN целиком, правила сайтов не могут выборочно вернуть его трафик в туннель."),
        ("Сетевые интерфейсы", "Список физических устройств обнаруживается динамически. Информационная строка показывает TUN-интерфейс, который сообщает статус AdGuard VPN CLI. Привязка исходящего VPN-трафика выполняется средствами CLI; одновременно поддерживается один физический интерфейс."),
        ("DNS и защита", "Выбор DNS: AdGuard DNS с фильтрацией, без фильтрации или семейный; Cloudflare, Google Public DNS, OpenDNS, Quad9, Mullvad DNS, системный DNS или собственные IP-адреса. Применение в текущей сборке ограничено двумя явно разрешёнными тестовыми профилями NetworkManager; обычные активные подключения не меняются. DNS не разделяется по приложениям."),
        ("Безопасность и пароль администратора", "Это независимый GUI-wrapper для AdGuard VPN CLI, не официальный продукт AdGuard. При запросе административных прав обратите внимание на окно терминала или графической авторизации. В терминале символы пароля обычно не отображаются — это нормально; нажмите Enter. Не сообщайте пароль программе и не вставляйте его в её поля. pkexec может показать графический диалог вместо терминала; пароль не должен сохраняться приложением."),
        ("Применение настроек", "Нажмите «Применить» после изменения параметров. Если для активации требуется перезапуск VPN или компонента, сначала отключите VPN, примените изменения и подключитесь снова. Перезапускать системные службы следует только при реальной необходимости."),
        ("Авторство и репозиторий", "Идея проекта: Karpushin Viktor. Telegram: https://t.me/Karpuschin. Реализация подготовлена совместно с OpenAI ChatGPT (модель GPT-6) как ИИ-инструментом; требования, архитектурные решения, проверка и принятие результатов остаются ответственностью автора. GitHub: https://github.com/1919013/adguard-vpn-desktop. Это независимая оболочка для AdGuard VPN CLI, не официальный продукт AdGuard."),
    ]
    links = "".join(f'<li><a href="#s{i}">{html.escape(title)}</a></li>' for i, (title, _) in enumerate(sections))
    body = "".join(f'<section id="s{i}"><h2>{html.escape(title)}</h2><p>{html.escape(text)}</p></section>' for i, (title, text) in enumerate(sections))
    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Справка — ADGuard VPN Desktop</title>
<style>body{{font:16px/1.6 system-ui,sans-serif;max-width:850px;margin:3rem auto;padding:0 1.2rem;color:#20242a}}
h1,h2{{line-height:1.25}}nav,section{{padding:1rem 1.2rem;margin:1rem 0;background:#f3f5f7;border-radius:12px}}
a{{color:#075db5}}.disclaimer{{border-left:4px solid #c58a16;padding-left:1rem}}</style></head>
<body><h1>ADGuard VPN Desktop</h1>
<p class="disclaimer"><b>Важно:</b> независимая графическая оболочка для официального AdGuard VPN CLI. Не является продуктом AdGuard и не поддерживается AdGuard.</p>
<nav><h2>Содержание</h2><ul>{links}</ul></nav>{body}
<footer><p><a href="https://github.com/1919013/adguard-vpn-desktop">GitHub — репозиторий проекта</a> · Идея: Karpushin Viktor · <a href="https://t.me/Karpuschin">Telegram</a>.</p><p>ИИ-инструмент: OpenAI ChatGPT, GPT-6. Параметры CLI сверяйте с официальной документацией AdGuard.</p></footer>
</body></html>"""


def open_help() -> None:
    """Write a temporary help document and open it in the default browser."""
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".html", prefix="adguard-vpn-desktop-help-", delete=False) as stream:
        stream.write(build_help_html())
        path = Path(stream.name)
    if not webbrowser.open(path.as_uri()):
        raise RuntimeError("Не удалось открыть справку в браузере по умолчанию.")


def build_help_tab():
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk
    root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    root.set_border_width(16)
    label = Gtk.Label(label="Справка откроется в браузере по умолчанию как гипертекстовая страница.", xalign=0)
    label.set_line_wrap(True)
    root.pack_start(label, False, False, 0)
    button = Gtk.Button(label="Открыть справку в браузере")
    button.connect("clicked", lambda *_: open_help())
    root.pack_start(button, False, False, 0)
    return root
