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
        ("Приложения", "Текущие ярлыки «через AdGuard VPN» используют SOCKS5 и proxychains4. Это вспомогательный способ запуска, а не полноценная маршрутизация процессов: UDP/QUIC и часть приложений могут обходить прокси; Flatpak и Snap пока не поддерживаются. В разработке — экспериментальная маршрутизация TUN через cgroup v2, nftables и systemd. Она пока не активируется автоматически и требует отдельной проверки на Debian."),
        ("Исключения сайтов", "Списки сайтов управляются штатной командой adguardvpn-cli site-exclusions. CLI использует один список сайтов и один активный режим. General: сайты из списка идут напрямую, вне VPN. Selective: через VPN идут только сайты из списка. Список сайтов независим от выбора приложений. Если браузер исключён из VPN целиком, правила сайтов не могут выборочно вернуть его трафик в туннель."),
        ("Сетевые интерфейсы", "Список сетевых устройств обнаруживается динамически. Привязка исходящего VPN-трафика настраивается средствами AdGuard VPN CLI. Одновременно поддерживается один интерфейс."),
        ("DNS и защита", "DNS-вкладка текущей версии работает в ограниченном тестовом режиме и разрешает операции только с явно указанными тестовыми профилями. Она не изменяет рабочие подключения NetworkManager."),
        ("Безопасность", "Это независимый проект, не разработанный и не поддерживаемый AdGuard. Не передавайте приложению пароли и токены. Экспериментальная маршрутизация приложений не включается без явного действия пользователя; не применяйте её к рабочему сетевому подключению до проверки на вашей системе."),
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
<footer><p>Параметры CLI и совместимость сверяйте с официальной документацией AdGuard.</p></footer>
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
