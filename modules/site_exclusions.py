"""Native AdGuard VPN CLI website exclusions (independent from app routing)."""
from __future__ import annotations

import re
import shutil
import subprocess
from typing import Iterable

VALID_MODES = {"general", "selective"}
DOMAIN_RE = re.compile(r"^(?:\*\.)?(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}$")


class SiteExclusionError(RuntimeError):
    pass


def validate_domains(value: str | Iterable[str]) -> list[str]:
    """Validate domains and wildcard domains accepted by the CLI."""
    raw = value.split() if isinstance(value, str) else list(value)
    domains = []
    for item in raw:
        domain = str(item).strip().rstrip(".")
        if not domain or not DOMAIN_RE.fullmatch(domain):
            raise ValueError(f"Некорректный домен или шаблон: {item}")
        if domain.casefold() not in {x.casefold() for x in domains}:
            domains.append(domain)
    return domains


def command(*args: str) -> list[str]:
    return ["adguardvpn-cli", "site-exclusions", *args]


def run_cli(*args: str) -> tuple[int, str]:
    if not shutil.which("adguardvpn-cli"):
        return 127, "Не найден adguardvpn-cli."
    try:
        result = subprocess.run(
            command(*args), text=True, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, timeout=20, check=False,
        )
        return result.returncode, result.stdout.strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)


def get_mode() -> tuple[int, str]:
    return run_cli("mode")


def set_mode(mode: str) -> tuple[int, str]:
    if mode not in VALID_MODES:
        raise ValueError("Режим должен быть general или selective.")
    return run_cli("mode", mode)


def show_exclusions() -> tuple[int, str]:
    return run_cli("show")


def add_exclusions(domains: str | Iterable[str], mode: str) -> tuple[int, str]:
    if mode not in VALID_MODES:
        raise ValueError("Неизвестный режим исключений.")
    values = validate_domains(domains)
    if not values:
        return 0, "Список доменов пуст."
    code, output = set_mode(mode)
    if code:
        return code, output
    return run_cli("add", *values)


def remove_exclusions(domains: str | Iterable[str], mode: str) -> tuple[int, str]:
    if mode not in VALID_MODES:
        raise ValueError("Неизвестный режим исключений.")
    values = validate_domains(domains)
    if not values:
        return 0, "Список доменов пуст."
    code, output = set_mode(mode)
    if code:
        return code, output
    return run_cli("remove", *values)


def clear_exclusions(mode: str) -> tuple[int, str]:
    if mode not in VALID_MODES:
        raise ValueError("Неизвестный режим исключений.")
    code, output = set_mode(mode)
    if code:
        return code, output
    return run_cli("clear")


def build_site_exclusions_tab():
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk, GLib
    import threading

    root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    root.set_border_width(12)
    intro = Gtk.Label(
        label="Списки сайтов управляются штатной командой AdGuard VPN CLI. "
              "Режимы сайтов независимы от выбора приложений: General — указанные сайты идут напрямую; "
              "Selective — через VPN идут только указанные сайты.",
        xalign=0,
    )
    intro.set_line_wrap(True)
    root.pack_start(intro, False, False, 0)

    mode_row = Gtk.Box(spacing=8)
    mode_row.pack_start(Gtk.Label(label="Режим списка:"), False, False, 0)
    mode = Gtk.ComboBoxText()
    mode.append("general", "General — исключить из VPN")
    mode.append("selective", "Selective — только через VPN")
    mode.set_active_id("general")
    mode_row.pack_start(mode, True, True, 0)
    root.pack_start(mode_row, False, False, 0)

    domains = Gtk.Entry()
    domains.set_placeholder_text("example.org *.example.net — домены через пробел")
    root.pack_start(domains, False, False, 0)

    status = Gtk.Label(label="Списки сайтов хранятся в настройках AdGuard VPN CLI.", xalign=0)
    status.set_line_wrap(True)
    root.pack_start(status, False, False, 0)

    output = Gtk.TextView()
    output.set_editable(False)
    output.set_cursor_visible(False)
    output.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
    scroll = Gtk.ScrolledWindow()
    scroll.set_min_content_height(150)
    scroll.set_vexpand(True)
    scroll.add(output)
    root.pack_start(scroll, True, True, 0)

    buttons = Gtk.Box(spacing=6)
    root.pack_start(buttons, False, False, 0)
    actions = [
        ("Показать список", "show"),
        ("Добавить", "add"),
        ("Удалить выбранные домены", "remove"),
        ("Очистить список", "clear"),
    ]
    widgets = {}
    for label, key in actions:
        button = Gtk.Button(label=label)
        buttons.pack_start(button, False, False, 0)
        widgets[key] = button

    def selected_mode():
        return mode.get_active_id() or "general"

    def render(result):
        code, text = result
        status.set_text("Готово." if code == 0 else "Ошибка выполнения команды.")
        output.get_buffer().set_text(text or ("Команда выполнена." if code == 0 else "Нет вывода CLI."))
        for button in widgets.values():
            button.set_sensitive(True)
        return False

    def run_action(action):
        value = domains.get_text().strip()
        chosen_mode = selected_mode()
        if action in {"add", "remove"}:
            try:
                validate_domains(value)
            except ValueError as exc:
                status.set_text(str(exc))
                return
        if action == "clear":
            dialog = Gtk.MessageDialog(
                transient_for=root.get_toplevel() if isinstance(root.get_toplevel(), Gtk.Window) else None,
                flags=Gtk.DialogFlags.MODAL, message_type=Gtk.MessageType.WARNING,
                buttons=Gtk.ButtonsType.CANCEL, text="Очистить список сайтов?",
            )
            dialog.format_secondary_text("Будет очищен только список выбранного режима AdGuard VPN CLI.")
            dialog.add_button("Очистить", Gtk.ResponseType.OK)
            answer = dialog.run()
            dialog.destroy()
            if answer != Gtk.ResponseType.OK:
                return
        for button in widgets.values():
            button.set_sensitive(False)
        status.set_text("Выполняется команда AdGuard VPN CLI…")
        def worker():
            try:
                if action == "show":
                    result = set_mode(chosen_mode)
                    if result[0] == 0:
                        result = show_exclusions()
                elif action == "add":
                    result = add_exclusions(value, chosen_mode)
                elif action == "remove":
                    result = remove_exclusions(value, chosen_mode)
                else:
                    result = clear_exclusions(chosen_mode)
                GLib.idle_add(render, result)
            except Exception as exc:
                GLib.idle_add(render, (1, str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    for key, button in widgets.items():
        button.connect("clicked", lambda _button, action=key: run_action(action))
    return root
