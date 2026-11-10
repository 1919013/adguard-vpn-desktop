"""Per-application VPN launchers using AdGuard VPN CLI SOCKS5 mode.

Linux VPN CLI does not provide a native per-process TUN selector. We create
separate desktop launchers for supported apps via proxychains-ng and the local
VPN SOCKS5 proxy. Original launchers and system routes remain untouched.
"""
from __future__ import annotations

import configparser
import json
import os
import re
import shlex
import shutil
import socket
import subprocess
from pathlib import Path

HOST, PORT = "127.0.0.1", 1080
FIELD_CODES = re.compile(r"%(?:[fFuUdDnNickvm]|%)")


def _data_dirs():
    home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    system = [Path(p) for p in os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":") if p]
    return [home, *system]


def _exec_tokens(value):
    return shlex.split(FIELD_CODES.sub("", value).strip(), posix=True)


def _resolve(tokens):
    if not tokens:
        return None, "Пустая команда запуска"
    if Path(tokens[0]).name in {"flatpak", "snap"}:
        return None, "Flatpak/Snap: proxychains не гарантирует перехват трафика внутри песочницы"
    executable = tokens[0]
    if executable == "env":
        return None, "Запуск через env с переменными окружения пока не поддерживается"
    resolved = executable if os.path.isabs(executable) else shutil.which(executable)
    if not resolved or not Path(resolved).is_file() or not os.access(resolved, os.X_OK):
        return None, f"Исполняемый файл не найден: {executable}"
    return [str(Path(resolved).resolve()), *tokens[1:]], ""


def discover_apps():
    """Find visible desktop applications in XDG application directories."""
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
                e = parser["Desktop Entry"]
                if e.get("Type", "Application") != "Application" or e.getboolean("Hidden", fallback=False) or e.getboolean("NoDisplay", fallback=False):
                    continue
                name = e.get(f"Name[{locale}]") or e.get(f"Name[{locale.split('_')[0]}]") or e.get("Name") or file.stem
                command = e.get("Exec", "").strip()
                if not command:
                    continue
                key = str(file)
                if key in seen:
                    continue
                seen.add(key)
                try:
                    resolved, reason = _resolve(_exec_tokens(command))
                except (ValueError, OSError) as exc:
                    resolved, reason = None, str(exc)
                apps.append({
                    "id": key, "name": name, "exec": command,
                    "icon": e.get("Icon", "network-vpn"),
                    "terminal": e.getboolean("Terminal", fallback=False),
                    "supported": resolved is not None, "reason": reason,
                })
            except (OSError, configparser.Error, ValueError):
                continue
    return sorted(apps, key=lambda a: (a["name"].casefold(), a["id"]))


def _state_file():
    return Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "adguard-vpn-desktop" / "routed-apps.json"


def load_selection():
    try:
        return set(json.loads(_state_file().read_text()).get("selected", []))
    except (OSError, ValueError, TypeError):
        return set()


def _vpn_ready():
    if not shutil.which("adguardvpn-cli"):
        return False, "Не найден adguardvpn-cli."
    if not shutil.which("proxychains4"):
        return False, "Не найден proxychains4. Установите пакет proxychains4."
    result = subprocess.run(["adguardvpn-cli", "config", "show"], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=15, check=False)
    if result.returncode:
        return False, result.stdout.strip() or "Не удалось прочитать конфигурацию VPN CLI."
    if not re.search(r"(?:vpn\s*)?mode\s*[:=]\s*(?:socks|socks5)\b", result.stdout, re.I):
        return False, "Требуется режим SOCKS5. Выполните: adguardvpn-cli config set-mode SOCKS, затем подключитесь заново."
    try:
        with socket.create_connection((HOST, PORT), timeout=2):
            pass
    except OSError:
        return False, f"SOCKS5 {HOST}:{PORT} не отвечает. Подключите AdGuard VPN CLI."
    return True, f"SOCKS5 доступен: {HOST}:{PORT}"


def _proxy_config():
    path = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "adguard-vpn-desktop" / "proxychains.conf"
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_text("strict_chain\nproxy_dns\nremote_dns_subnet 224\ntcp_read_time_out 15000\ntcp_connect_time_out 8000\n[ProxyList]\nsocks5 127.0.0.1 1080\n", encoding="utf-8")
    os.chmod(path, 0o600)
    return path


def _desktop_exec_quote(path):
    value = str(path).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{value}"'


def apply_routing(selected_ids, direct_paths=()):
    if not selected_ids and not direct_paths:
        return 0, "Ничего не выбрано. Существующие VPN-ярлыки не изменены."
    ready, message = _vpn_ready()
    if not ready:
        return 2, message
    apps = {a["id"]: a for a in discover_apps()}
    chosen = []
    for app_id in selected_ids:
        app = apps.get(app_id)
        if not app:
            return 2, f"Приложение не найдено: {app_id}. Обновите список."
        if not app["supported"]:
            return 2, f'{app["name"]}: {app["reason"]}'
        chosen.append((app["name"], app["exec"], app["icon"], app["terminal"]))
    for raw in direct_paths:
        p = Path(raw).expanduser()
        if not p.is_absolute() or not p.is_file() or not os.access(p, os.X_OK):
            return 2, f"Нужен полный путь к исполняемому файлу: {raw}"
        chosen.append((p.name, shlex.quote(str(p)), "application-x-executable", False))

    chosen.sort(key=lambda item: item[0].casefold())
    proxy = shutil.which("proxychains4")
    conf = _proxy_config()
    data = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    launcher_dir = data / "applications" / "adguard-vpn-routed"
    bin_dir = data / "adguard-vpn-desktop" / "bin"
    launcher_dir.mkdir(parents=True, exist_ok=True)
    bin_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Replace only files in the private directories owned by this feature.
    for directory in (launcher_dir, bin_dir):
        if directory.is_symlink():
            return 2, f"Каталог VPN-ярлыков является символической ссылкой: {directory}"
        for previous in directory.iterdir():
            if previous.is_file() and not previous.is_symlink():
                previous.unlink()
    created, errors = [], []
    for index, (name, command, icon, terminal) in enumerate(chosen):
        try:
            tokens = _exec_tokens(command)
            resolved, reason = _resolve(tokens)
            if not resolved:
                errors.append(f"{name}: {reason}")
                continue
            slug = re.sub(r"[^a-z0-9-]+", "-", name.casefold()).strip("-")[:36] or "app"
            wrapper = bin_dir / f"{slug}-{index}-vpn.sh"
            desktop = launcher_dir / f"{slug}-{index}-vpn.desktop"
            wrapper.write_text("#!/bin/sh\nexec " + shlex.quote(proxy) + " -f " + shlex.quote(str(conf)) + " -q " + " ".join(shlex.quote(x) for x in resolved) + ' "$@"\n', encoding="utf-8")
            os.chmod(wrapper, 0o700)
            desktop.write_text(
                "[Desktop Entry]\nType=Application\n"
                f"Name={name} (через AdGuard VPN)\n"
                f"Exec={_desktop_exec_quote(wrapper)} %U\n"
                f"Icon={icon}\nTerminal={'true' if terminal else 'false'}\n"
                "Categories=Network;\nStartupNotify=true\n",
                encoding="utf-8",
            )
            created.append(str(desktop))
        except (OSError, ValueError) as exc:
            errors.append(f"{name}: {exc}")
    state = _state_file()
    state.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    state.write_text(json.dumps({"selected": sorted(selected_ids)}, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(state, 0o600)
    update = shutil.which("update-desktop-database")
    if update:
        subprocess.run([update, str(data / "applications")], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    summary = [f"Создано VPN-ярлыков: {len(created)}.", *created]
    if errors:
        summary.extend(["", "Ошибки:", *errors])
    summary.extend(["", "Исходные ярлыки и системные маршруты не изменены.",
        "Ограничение: proxychains перехватывает поддерживаемые TCP-соединения; UDP/QUIC и часть приложений могут обходить прокси. Flatpak/Snap исключены."])
    return (0 if created else 1), "\n".join(summary)


def remove_routing():
    data = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    removed = 0
    for directory in (data / "applications" / "adguard-vpn-routed", data / "adguard-vpn-desktop" / "bin"):
        if directory.is_symlink():
            return 2, f"Символическая ссылка — удаление отменено: {directory}"
        if directory.is_dir():
            for item in directory.iterdir():
                if item.is_file() and not item.is_symlink():
                    item.unlink()
                    removed += 1
    update = shutil.which("update-desktop-database")
    if update:
        subprocess.run([update, str(data / "applications")], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    state = _state_file()
    if state.exists() and not state.is_symlink():
        state.unlink()
    return 0, f"Удалено созданных VPN-файлов: {removed}. Оригинальные приложения не затронуты."


def build_applications_tab():
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk, GLib
    import threading

    root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    root.set_border_width(12)
    intro = Gtk.Label(label="Выберите приложения из меню GNOME или добавьте исполняемый файл вручную. Для работы нужны AdGuard VPN CLI в режиме SOCKS5 и пакет proxychains4 (Debian: sudo apt install proxychains4). Будут созданы отдельные ярлыки; исходные ярлыки не меняются.", xalign=0)
    intro.set_line_wrap(True)
    root.pack_start(intro, False, False, 0)
    status = Gtk.Label(label="Загрузка приложений…", xalign=0)
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
    direct.set_placeholder_text("Полный путь, например /opt/app/bin/app")
    root.pack_start(direct, False, False, 0)
    add_path = Gtk.Button(label="Добавить путь")
    root.pack_start(add_path, False, False, 0)
    row = Gtk.Box(spacing=6)
    root.pack_start(row, False, False, 0)
    all_btn, none_btn, apply_btn, remove_btn = [Gtk.Button(label=x) for x in ("Выбрать все", "Очистить все", "Применить", "Удалить VPN-ярлыки")]
    for b in (all_btn, none_btn, apply_btn, remove_btn):
        row.pack_start(b, False, False, 0)

    apps = discover_apps()
    checks = {}
    saved = load_selection()
    direct_paths = []

    for app in apps:
        check = Gtk.CheckButton(label=app["name"] + ("" if app["supported"] else " — недоступно"))
        check.set_tooltip_text(app["reason"] or app["id"])
        check.set_sensitive(app["supported"])
        check.set_active(app["id"] in saved)
        checks[app["id"]] = check
        listbox.add(check)
    listbox.show_all()
    status.set_text(f"Найдено приложений: {len(apps)}; поддерживается: {sum(a['supported'] for a in apps)}.")

    def filter_apps(*_):
        prefix = search.get_text().strip().casefold()
        for app in apps:
            checks[app["id"]].set_visible(not prefix or app["name"].casefold().startswith(prefix))
    search.connect("changed", filter_apps)

    def add_direct(*_):
        value = direct.get_text().strip()
        p = Path(value).expanduser()
        if not p.is_absolute() or not p.is_file() or not os.access(p, os.X_OK):
            status.set_text("Укажите полный путь к существующему исполняемому файлу.")
            return
        resolved = str(p.resolve())
        if resolved not in direct_paths:
            direct_paths.append(resolved)
        direct.set_text("")
        status.set_text("Добавлен путь: " + resolved)
    add_path.connect("clicked", add_direct)

    def select_all(*_):
        for widget in checks.values():
            if widget.get_sensitive():
                widget.set_active(True)
    all_btn.connect("clicked", select_all)
    none_btn.connect("clicked", lambda *_: [w.set_active(False) for w in checks.values()])

    def finish(result):
        code, output = result
        status.set_text(output)
        for b in (all_btn, none_btn, apply_btn, remove_btn):
            b.set_sensitive(True)
        return False

    def apply(*_):
        selected = {key for key, widget in checks.items() if widget.get_active()}
        for b in (all_btn, none_btn, apply_btn, remove_btn):
            b.set_sensitive(False)
        status.set_text("Проверка SOCKS5 и создание ярлыков…")
        def worker():
            try:
                result = apply_routing(selected, direct_paths)
            except Exception as exc:
                result = (1, str(exc))
            GLib.idle_add(finish, result)
        threading.Thread(target=worker, daemon=True).start()
    apply_btn.connect("clicked", apply)

    def remove(*_):
        dialog = Gtk.MessageDialog(transient_for=root.get_toplevel() if isinstance(root.get_toplevel(), Gtk.Window) else None, flags=Gtk.DialogFlags.MODAL, message_type=Gtk.MessageType.WARNING, buttons=Gtk.ButtonsType.CANCEL, text="Удалить созданные VPN-ярлыки?")
        dialog.format_secondary_text("Удалятся только ярлыки и скрипты этой вкладки. Исходные приложения останутся.")
        dialog.add_button("Удалить", Gtk.ResponseType.OK)
        answer = dialog.run()
        dialog.destroy()
        if answer == Gtk.ResponseType.OK:
            for b in (all_btn, none_btn, apply_btn, remove_btn):
                b.set_sensitive(False)
            def worker():
                GLib.idle_add(finish, remove_routing())
            threading.Thread(target=worker, daemon=True).start()
    remove_btn.connect("clicked", remove)
    return root
