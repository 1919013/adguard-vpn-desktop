"""Interactive help pages opened in the user's default browser."""
from __future__ import annotations

import html
import tempfile
import webbrowser
from pathlib import Path


def build_help_html() -> str:
    sections = [
        ("Назначение", "Приложение является независимой графической оболочкой для официального AdGuard VPN CLI. Оно не является продуктом AdGuard и не заменяет официальный клиент."),
        ("Подключение", "На вкладке «Подключение» загрузите список серверов, выберите местоположение и подключитесь. Состояние отображается по ответу adguardvpn-cli."),
        ("Сетевые интерфейсы", "Список сетевых устройств обнаруживается динамически. Привязка исходящего VPN-трафика настраивается средствами AdGuard VPN CLI. Одновременно поддерживается один интерфейс."),
        ("DNS и защита", "DNS-операции выполняйте только после проверки плана и резервной копии. Не применяйте изменения к рабочим профилям NetworkManager без отдельного подтверждения и проверенного механизма отката."),
        ("Безопасность", "Не передавайте приложению пароли и токены. Не удаляйте пользовательские данные, пока не проверили, какие именно каталоги и настройки будут затронуты."),
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
<p class="disclaimer"><b>Важно:</b> это независимая open-source графическая оболочка для AdGuard VPN CLI, не разработанная и не поддерживаемая AdGuard.</p>
<nav><h2>Содержание</h2><ul>{links}</ul></nav>{body}
<footer><p>Используйте официальную документацию AdGuard VPN CLI для уточнения поддерживаемых команд и параметров.</p></footer>
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
