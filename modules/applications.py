"""GTK app selector for genuine per-process AdGuard VPN TUN routing."""
from __future__ import annotations

import configparser
import json
import os
import re
import shlex
import shutil
import subprocess
import threading
from pathlib import Path

from services import app_routing

FIELD_CODES = re.compile(r"%(?:[fFuUdDnNickvm]|%)")


def _data_dirs():
    home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    system = [Path(p) for p in os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":") if p]
    return [home, *system]


def _exec_tokens(value):
    return shlex.split(FIELD_CODES.sub("", value).strip(), posix=True)


def _resolve(tokens):
    if not tokens:
        return None, "Пустая команда запуска."
    if Path(tokens[0]).name in {"flatpak", "snap"}:
        return None, "Flatpak/Snap пока не поддерживаются: запуск внутри отдельной cgroup не гарантирован."
    if tokens[0] == "env":
        return None, "Exec через env пока не поддерживается."
    executable = tokens[0]
    resolved = executable if os.path.isabs(executable) else shutil.which(executable)
    if not resolved or not Path(resolved).is_file() or not os.access(resolved, os.X_OK):
        return None, f"Исполняемый файл не найден: {executable}"
    return [str(Path(resolved).resolve()), *tokens[1:]], ""


def discover_apps():
    """Discover launchable desktop entries from XDG application directories."""
    locale = os.environ.get("LANG", "ru_RU").split(".")[0].replace("-", "_")
    apps, seen = [], set()
    generated = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "applications" / "adguard-vpn-routed"
    for data_dir in _data_dirs():
        app_dir = data_dir / "applications"
        if not app_dir.is_dir():
            continue
        for file in app_dir.rglob("*.desktop"):
            if generated in file.parents:
                continue
            try:
                parser = configparser.ConfigParser(interpolation=None, strict=False)
                parser.optionxform = str
                parser.read(file, encoding="utf-8")
                if "Desktop Entry" not in parser:
                    continue
                entry = parser["Desktop Entry"]
                if (entry.get("Type", "Application") != "Application"
                        or entry.getboolean("Hidden", fallback=False)
                        or entry.getboolean("NoDisplay", fallback=False)):
                    continue
                name = (entry.get(f"Name[{locale}]")
                        or entry.get(f"Name[{locale.split('_')[0]}]")
                        or entry.get("Name") or file.stem)
                command = entry.get("Exec", "").strip()
                if not command or str(file) in seen:
                    continue
                seen.add(str(file))
                try:
                    resolved, reason = _resolve(_exec_tokens(command))
                except (ValueError, OSError) as exc:
                    resolved, reason = None, str(exc)
                apps.append({
                    "id": str(file), "name": name, "exec": command,
                    "icon": entry.get("Icon", "network-vpn"),
                    "terminal": entry.getboolean("Terminal", fallback=False),
                    "supported": resolved is not None, "reason": reason,
                })
            except (OSError, configparser.Error, ValueError):
                continue
    return sorted(apps, key=lambda item: (item["name"].casefold(), item["id"]))


def _state_file():
    state = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))
    return state / "adguard-vpn-desktop" / "routed-apps.json"


def load_selection():
    try:
        payload = json.loads(_state_file().read_text(encoding="utf-8"))
        return set(payload.get("selected", [])), list(payload.get("direct_paths", [])), payload.get("mode", "selected")
    except (OSError, ValueError, TypeError):
        return set(), [], "selected"


def _desktop_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _remove_generated_files() -> tuple[int, str]:
    data = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    directories = (
        data / "applications" / "adguard-vpn-routed",
        data / "adguard-vpn-desktop" / "bin",
    )
    for directory in directories:
        if directory.is_symlink():
            return 2, f"Символическая ссылка — операция отменена: {directory}"
    removed = 0
    for directory in directories:
        if directory.is_dir():
            for item in directory.iterdir():
                if item.is_file() and not item.is_symlink():
                    item.unlink()
                    removed += 1
    update = shutil.which("update-desktop-database")
    if update:
        subprocess.run([update, str(data / "applications")], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, check=False)
    return 0, f"Обновлено. Удалено старых VPN-ярлыков и скриптов: {removed}."


def apply_selection(mode: str, selected_ids, direct_paths=()):
    """Configure TUN policy and create alternate launchers in the managed cgroup."""
    if mode not in app_routing.VALID_MODES:
        return 2, "Неизвестный режим."
    apps = {app["id"]: app for app in discover_apps()}
    chosen = []
    for app_id in selected_ids:
        app = apps.get(app_id)
        if not app:
            return 2, f"Приложение не найдено: {app_id}. Обновите список."
        if not app["supported"]:
            return 2, f'{app["name"]}: {app["reason"]}'
        tokens, reason = _resolve(_exec_tokens(app["exec"]))
        if not tokens:
            return 2, f'{app["name"]}: {reason}'
        chosen.append((app["id"], app["name"], tokens, app["icon"], app["terminal"]))
    for raw in direct_paths:
        path = Path(raw).expanduser()
        if not path.is_absolute() or not path.is_file() or not os.access(path, os.X_OK):
            return 2, f"Нужен полный путь к исполняемому файлу: {raw}"
        resolved = str(path.resolve())
        chosen.append((resolved, path.name, [resolved], "application-x-executable", False))

    # Install or update the reversible AdGuard route hook before publishing
    # launchers. If this fails, the current set of launchers remains untouched.
    code, output = app_routing.reconfigure(mode)
    if code:
        return code, output

    data = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    launcher_dir = data / "applications" / "adguard-vpn-routed"
    bin_dir = data / "adguard-vpn-desktop" / "bin"
    for directory in (launcher_dir, bin_dir):
        if directory.is_symlink():
            return 2, f"Каталог является символической ссылкой: {directory}"
    launcher_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    bin_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    _remove_generated_files()
    launcher_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    bin_dir.mkdir(parents=True, exist_ok=True, mode=0o700)

    systemd_run = shutil.which("systemd-run")
    if not systemd_run:
        return 2, "Не найдена команда systemd-run."
    created, errors = [], []
    for index, (app_id, name, tokens, icon, terminal) in enumerate(chosen):
        try:
            slug = re.sub(r"[^a-z0-9-]+", "-", name.casefold()).strip("-")[:36] or "app"
            wrapper = bin_dir / f"{slug}-{index}-split.sh"
            unit = app_routing.scope_command(tokens, app_id)[4].split("=", 1)[1]
            command = [systemd_run, "--user", "--scope",
                       f"--slice={app_routing.APP_SLICE}", f"--unit={unit}", "--", *tokens]
            wrapper.write_text("#!/bin/sh\nexec " + " ".join(shlex.quote(part) for part in command) + ' "$@"\n',
                               encoding="utf-8")
            os.chmod(wrapper, 0o700)
            label = "через VPN" if mode == "selected" else "напрямую"
            desktop = launcher_dir / f"{slug}-{index}-split.desktop"
            desktop.write_text(
                "[Desktop Entry]\nType=Application\n"
                f"Name={name} ({label})\n"
                f"Exec={_desktop_quote(str(wrapper))} %U\n"
                f"Icon={icon}\nTerminal={'true' if terminal else 'false'}\n"
                "DBusActivatable=false\nCategories=Network;\nStartupNotify=true\n",
                encoding="utf-8",
            )
            created.append(str(desktop))
        except (OSError, ValueError) as exc:
            errors.append(f"{name}: {exc}")

    state = _state_file()
    state.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    state.write_text(json.dumps({
        "mode": mode, "selected": sorted(selected_ids),
        "direct_paths": sorted(set(str(Path(p).expanduser().resolve()) for p in direct_paths)),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(state, 0o600)
    update = shutil.which("update-desktop-database")
    if update:
        subprocess.run([update, str(data / "applications")], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, check=False)
    description = (
        "Только выбранные приложения запускаются через TUN; остальные идут напрямую."
        if mode == "selected" else
        "Приложения пользователя идут через TUN, кроме выбранных в созданных ярлыках."
    )
    lines = [description, f"Создано альтернативных ярлыков: {len(created)}.", *created]
    if errors:
        lines.extend(["Ошибки:", *errors])
    lines.extend([
        "Закройте уже запущенные приложения и запускайте их через новые ярлыки.",
        "После настройки переподключите AdGuard VPN, чтобы CLI применил route script.",
        "Flatpak/Snap пока не поддерживаются. Системный DNS общий для системы, а не изолирован по процессам.",
    ])
    return (0 if created or not chosen else 1), "\n".join(lines)


def remove_routing():
    code, output = app_routing.disable()
    if code:
        return code, output
    _remove_generated_files()
    state = _state_file()
    if state.exists() and not state.is_symlink():
        state.unlink()
    return 0, output + "\nСозданные альтернативные ярлыки удалены; оригинальные ярлыки не затронуты."


def build_applications_tab():
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk, GLib

    root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    root.set_border_width(12)
    intro = Gtk.Label(
        label=("Раздельное туннелирование TUN через systemd/cgroup v2 и nftables. "
               "«Только выбранные» отправляет в VPN приложения из созданных ярлыков. "
               "«Все, кроме выбранных» отправляет через VPN приложения пользовательской сессии, "
               "а выбранные запускает напрямую. Это не SOCKS5 и не proxychains."),
        xalign=0,
    )
    intro.set_line_wrap(True)
    root.pack_start(intro, False, False, 0)

    mode = Gtk.ComboBoxText()
    mode.append("selected", "Только выбранные приложения через VPN")
    mode.append("all_except_selected", "Все приложения через VPN, кроме выбранных")
    selected, saved_paths, saved_mode = load_selection()
    mode.set_active_id(saved_mode if saved_mode in app_routing.VALID_MODES else "selected")
    root.pack_start(mode, False, False, 0)

    status = Gtk.Label(label="Проверка системных возможностей…", xalign=0)
    status.set_line_wrap(True)
    root.pack_start(status, False, False, 0)

    search = Gtk.Entry()
    search.set_placeholder_text("Фильтр по началу названия, например tel")
    root.pack_start(search, False, False, 0)
    listbox = Gtk.ListBox()
    listbox.set_selection_mode(Gtk.SelectionMode.NONE)
    scroll = Gtk.ScrolledWindow()
    scroll.set_min_content_height(220)
    scroll.set_vexpand(True)
    scroll.add(listbox)
    root.pack_start(scroll, True, True, 0)

    direct = Gtk.Entry()
    direct.set_placeholder_text("Полный путь к приложению, например /opt/app/bin/app")
    root.pack_start(direct, False, False, 0)
    direct_paths = list(saved_paths)
    path_row = Gtk.Box(spacing=6)
    root.pack_start(path_row, False, False, 0)
    add_path = Gtk.Button(label="Добавить путь")
    path_row.pack_start(add_path, False, False, 0)
    paths_label = Gtk.Label(label="Дополнительные пути: " + (", ".join(direct_paths) if direct_paths else "нет"), xalign=0)
    paths_label.set_line_wrap(True)
    path_row.pack_start(paths_label, True, True, 0)

    apps = discover_apps()
    checks = {}
    for app in apps:
        check = Gtk.CheckButton(label=app["name"] + ("" if app["supported"] else " — не поддерживается"))
        check.set_tooltip_text(app["reason"] or app["id"])
        check.set_sensitive(app["supported"])
        check.set_active(app["id"] in selected)
        checks[app["id"]] = check
        listbox.add(check)
    listbox.show_all()

    def filter_apps(*_):
        prefix = search.get_text().strip().casefold()
        for app in apps:
            checks[app["id"]].set_visible(not prefix or app["name"].casefold().startswith(prefix))
    search.connect("changed", filter_apps)

    def add_direct_path(*_):
        raw = direct.get_text().strip()
        path = Path(raw).expanduser()
        if not path.is_absolute() or not path.is_file() or not os.access(path, os.X_OK):
            status.set_text("Укажите полный путь к существующему исполняемому файлу.")
            return
        value = str(path.resolve())
        if value not in direct_paths:
            direct_paths.append(value)
        direct.set_text("")
        paths_label.set_text("Дополнительные пути: " + ", ".join(direct_paths))
    add_path.connect("clicked", add_direct_path)

    row = Gtk.Box(spacing=6)
    root.pack_start(row, False, False, 0)
    all_btn, none_btn, apply_btn, disable_btn = [
        Gtk.Button(label=label) for label in
        ("Выбрать все", "Очистить все", "Применить", "Отключить раздельное туннелирование")
    ]
    for button in (all_btn, none_btn, apply_btn, disable_btn):
        row.pack_start(button, False, False, 0)

    def set_busy(value):
        for button in (all_btn, none_btn, apply_btn, disable_btn, add_path, mode, search):
            button.set_sensitive(not value)

    def finish(result):
        code, message = result
        status.set_text(message)
        set_busy(False)
        return False

    def apply(*_):
        chosen = {key for key, widget in checks.items() if widget.get_active()}
        chosen_mode = mode.get_active_id()
        set_busy(True)
        status.set_text("Настройка TUN/SCRIPT и создание ярлыков…")
        def worker():
            try:
                result = apply_selection(chosen_mode, chosen, direct_paths)
            except Exception as exc:
                result = (1, str(exc))
            GLib.idle_add(finish, result)
        threading.Thread(target=worker, daemon=True).start()
    apply_btn.connect("clicked", apply)

    def disable(*_):
        dialog = Gtk.MessageDialog(
            transient_for=root.get_toplevel() if isinstance(root.get_toplevel(), Gtk.Window) else None,
            flags=Gtk.DialogFlags.MODAL, message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.CANCEL, text="Отключить раздельное туннелирование?",
        )
        dialog.format_secondary_text(
            "Будут удалены только выделенные правила маршрутизации, восстановлены прежний route script "
            "и настройки AdGuard VPN CLI. Перед отключением рекомендуется разорвать VPN-соединение."
        )
        dialog.add_button("Отключить", Gtk.ResponseType.OK)
        answer = dialog.run()
        dialog.destroy()
        if answer != Gtk.ResponseType.OK:
            return
        set_busy(True)
        status.set_text("Очистка выделенных правил и восстановление настроек…")
        def worker():
            try:
                result = remove_routing()
            except Exception as exc:
                result = (1, str(exc))
            GLib.idle_add(finish, result)
        threading.Thread(target=worker, daemon=True).start()
    disable_btn.connect("clicked", disable)

    all_btn.connect("clicked", lambda *_: [widget.set_active(True) for widget in checks.values() if widget.get_sensitive()])
    none_btn.connect("clicked", lambda *_: [widget.set_active(False) for widget in checks.values()])
    ok, problems = app_routing.check_capabilities()
    status.set_text(
        f"Найдено приложений: {len(apps)}; поддерживается: {sum(a['supported'] for a in apps)}. "
        + ("Системные требования выполнены." if ok else "Требуется: " + "; ".join(problems))
    )
    return root
