"""Native AdGuard VPN CLI website exclusions (separate from app routing)."""
from __future__ import annotations

import re
import shutil
import subprocess
from typing import Iterable

VALID_MODES = {"general", "selective"}
DOMAIN_RE = re.compile(r"^(?:\*\.)?(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\\.)+[A-Za-z]{2,63}$")


class SiteExclusionError(RuntimeError):
    pass


def validate_domains(value: str | Iterable[str]) -> list[str]:
    """Validate domains and wildcard domains accepted by the CLI."""
    raw = value.split() if isinstance(value, str) else list(value)
    domains: list[str] = []
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
    """Read the active site-exclusion mode without changing it."""
    return run_cli("mode")


def set_mode(mode: str) -> tuple[int, str]:
    if mode not in VALID_MODES:
        raise ValueError("Режим должен быть general или selective.")
    return run_cli("mode", mode)


def show_exclusions() -> tuple[int, str]:
    return run_cli("show")


def add_exclusions(domains: str | Iterable[str]) -> tuple[int, str]:
    values = validate_domains(domains)
    if not values:
        return 0, "Список доменов пуст."
    return run_cli("add", *values)


def remove_exclusions(domains: str | Iterable[str]) -> tuple[int, str]:
    values = validate_domains(domains)
    if not values:
        return 0, "Список доменов пуст."
    return run_cli("remove", *values)


def clear_exclusions() -> tuple[int, str]:
    return run_cli("clear")


def build_site_exclusions_tab():
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk, GLib
    import threading

    root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    root.set_border_width(12)
    intro = Gtk.Label(
        label=("AdGuard VPN CLI использует один список сайтов и отдельный активный режим. "
               "General — сайты из списка идут напрямую, мимо VPN. "
               "Selective — через VPN идут только сайты из списка. "
               "Смена режима влияет на VPN сразу после применения."),
        xalign=0,
    )
    intro.set_line_wrap(True)
    root.pack_start(intro, False, False, 0)

    mode_row = Gtk.Box(spacing=8)
    mode_row.pack_start(Gtk.Label(label="Режим:"), False, False, 0)
    mode = Gtk.ComboBoxText()
    mode.append("general", "General — исключить сайты из VPN")
    mode.append("selective", "Selective — VPN только для сайтов списка")
    mode.set_active_id("general")
    mode_row.pack_start(mode, True, True, 0)
    apply_mode = Gtk.Button(label="Применить режим")
    mode_row.pack_start(apply_mode, False, False, 0)
    root.pack_start(mode_row, False, False, 0)

    domains = Gtk.Entry()
    domains.set_placeholder_text("example.org *.example.net — домены через пробел")
    root.pack_start(domains, False, False, 0)

    status = Gtk.Label(label="Чтение текущих настроек AdGuard VPN CLI…", xalign=0)
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
    actions = [("Показать список", "show"), ("Добавить", "add"),
               ("Удалить домены", "remove"), ("Очистить список", "clear")]
    widgets = {}
    for label, key in actions:
        button = Gtk.Button(label=label)
        buttons.pack_start(button, False, False, 0)
        widgets[key] = button

    def set_output(result, message=None):
        code, output_text = result
        status.set_text(message or ("Готово." if code == 0 else "Ошибка выполнения команды."))
        output.get_buffer().set_text(output_text or ("Команда выполнена." if code == 0 else "Нет вывода CLI."))
        for button in (*widgets.values(), apply_mode):
            button.set_sensitive(True)
        return False

    def run_worker(action):
        value = domains.get_text().strip()
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
            dialog.format_secondary_text("Будут удалены все домены из единственного списка исключений AdGuard VPN CLI.")
            dialog.add_button("Очистить", Gtk.ResponseType.OK)
            answer = dialog.run()
            dialog.destroy()
            if answer != Gtk.ResponseType.OK:
                return
        for button in (*widgets.values(), apply_mode):
            button.set_sensitive(False)
        status.set_text("Выполняется команда AdGuard VPN CLI…")

        def worker():
            try:
                if action == "show":
                    result = show_exclusions()
                elif action == "add":
                    result = add_exclusions(value)
                elif action == "remove":
                    result = remove_exclusions(value)
                else:
                    result = clear_exclusions()
                GLib.idle_add(set_output, result)
            except Exception as exc:
                GLib.idle_add(set_output, (1, str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def apply_selected_mode(*_):
        chosen = mode.get_active_id()
        if chosen not in VALID_MODES:
            status.set_text("Выберите допустимый режим.")
            return
        for button in (*widgets.values(), apply_mode):
            button.set_sensitive(False)
        status.set_text("Изменение активного режима VPN…")
        def worker():
            try:
                result = set_mode(chosen)
                GLib.idle_add(set_output, result, "Активный режим изменён." if result[0] == 0 else None)
            except Exception as exc:
                GLib.idle_add(set_output, (1, str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def load_current_mode():
        def worker():
            result = get_mode()
            def apply_result():
                code, text = result
                if code == 0:
                    normalized = text.casefold()
                    current = "selective" if "selective" in normalized else "general" if "general" in normalized else None
                    if current:
                        mode.set_active_id(current)
                        status.set_text("Текущий режим: " + current + ". Список сайтов можно просмотреть отдельно.")
                    else:
                        status.set_text("Не удалось распознать текущий режим. Проверьте вывод CLI.")
                    output.get_buffer().set_text(text)
                else:
                    status.set_text("Не удалось прочитать режим AdGuard VPN CLI.")
                    output.get_buffer().set_text(text)
                return False
            GLib.idle_add(apply_result)
        threading.Thread(target=worker, daemon=True).start()

    for key, button in widgets.items():
        button.connect("clicked", lambda _button, action=key: run_worker(action))
    apply_mode.connect("clicked", apply_selected_mode)
    load_current_mode()
    return root
