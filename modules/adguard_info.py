"""AdGuard VPN CLI management (not the separate AdGuard ad blocker CLI)."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import urllib.request
from pathlib import Path

INSTALLER_URL = "https://raw.githubusercontent.com/AdguardTeam/AdGuardVPNCLI/HEAD/scripts/release/install.sh"
AUTOSTART_NAME = "adguardvpn-cli.desktop"


def run_vpn(args: list[str], timeout: int = 90) -> tuple[int, str]:
    try:
        result = subprocess.run(
            ["adguardvpn-cli", *args], text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            timeout=timeout, check=False,
        )
        return result.returncode, result.stdout.strip()
    except FileNotFoundError:
        return 127, "Команда adguardvpn-cli не найдена. Установите официальный AdGuard VPN CLI."
    except subprocess.TimeoutExpired:
        return 124, "Операция превысила допустимое время ожидания."
    except OSError as exc:
        return 1, str(exc)


def installed() -> bool:
    return shutil.which("adguardvpn-cli") is not None


def get_status() -> str:
    if not installed():
        return "AdGuard VPN CLI не обнаружен (adguardvpn-cli отсутствует в PATH)."
    version_code, version = run_vpn(["--version"], timeout=10)
    status_code, status = run_vpn(["status"], timeout=20)
    return "\n".join([
        "AdGuard VPN CLI",
        "Версия: " + (version if version_code == 0 else "не удалось определить"),
        "Состояние:",
        status if status else f"Команда status завершилась с кодом {status_code}",
    ])


def install_official() -> tuple[int, str]:
    """Fetch the official release installer over HTTPS and run it as the user.

    The official script requests elevation itself when required. It is not
    piped to a shell, and the downloaded temporary file is removed afterwards.
    """
    try:
        request = urllib.request.Request(INSTALLER_URL, headers={"User-Agent": "ADGuard-VPN-Desktop"})
        with urllib.request.urlopen(request, timeout=30) as response:
            if response.status != 200:
                return 1, f"Сервер установки вернул HTTP {response.status}."
            script = response.read(2_000_001)
        if len(script) > 2_000_000 or not script.startswith(b"#!"):
            return 1, "Получен некорректный или слишком большой скрипт установки."
        with tempfile.NamedTemporaryFile(prefix="adguardvpn-cli-install-", suffix=".sh", delete=False) as stream:
            stream.write(script)
            path = Path(stream.name)
        try:
            result = subprocess.run(["sh", str(path), "-v"], text=True, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, timeout=900, check=False)
            return result.returncode, result.stdout.strip()
        finally:
            path.unlink(missing_ok=True)
    except Exception as exc:
        return 1, str(exc)


def check_update() -> tuple[int, str]:
    return run_vpn(["check-update"], timeout=180)


def update_vpn() -> tuple[int, str]:
    return run_vpn(["update", "-v", "-y"], timeout=900)


def connect_vpn() -> tuple[int, str]:
    # --boot makes the CLI wait for network availability during startup.
    return run_vpn(["connect", "--boot"], timeout=300)


def disconnect_vpn() -> tuple[int, str]:
    return run_vpn(["disconnect"], timeout=90)


def _xdg_path(variable: str, fallback: str) -> Path:
    return Path(os.environ.get(variable, Path.home() / fallback)).expanduser()


def clear_cache() -> tuple[int, str]:
    target = _xdg_path("XDG_CACHE_HOME", ".cache") / "adguardvpn-cli"
    if target.is_symlink():
        return 2, f"Кэш является символической ссылкой; удаление отменено: {target}"
    if not target.exists():
        return 0, f"Каталог кэша не найден: {target}. Нечего очищать."
    if not target.is_dir():
        return 2, f"Ожидался каталог кэша; удаление отменено: {target}"
    shutil.rmtree(target)
    return 0, f"Кэш AdGuard VPN CLI очищен: {target}"


def clear_user_data() -> tuple[int, str]:
    """Delete only standard per-user XDG state/config/cache locations."""
    targets = [
        _xdg_path("XDG_DATA_HOME", ".local/share") / "adguardvpn-cli",
        _xdg_path("XDG_CONFIG_HOME", ".config") / "adguardvpn-cli",
        _xdg_path("XDG_CACHE_HOME", ".cache") / "adguardvpn-cli",
    ]
    for target in targets:
        if target.is_symlink():
            return 2, f"Обнаружена символическая ссылка; операция отменена: {target}"
        if target.exists() and not target.is_dir():
            return 2, f"Ожидался каталог; операция отменена: {target}"
    removed = []
    for target in targets:
        if target.is_dir():
            shutil.rmtree(target)
            removed.append(str(target))
    if not removed:
        return 0, "Пользовательские данные AdGuard VPN CLI не найдены."
    return 0, "Удалены каталоги пользовательских данных:\n" + "\n".join(removed)


def _desktop_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def autostart_path() -> Path:
    return _xdg_path("XDG_CONFIG_HOME", ".config") / "autostart" / AUTOSTART_NAME


def enable_autostart() -> tuple[int, str]:
    binary = shutil.which("adguardvpn-cli")
    if not binary:
        return 127, "Не найден adguardvpn-cli."
    target = autostart_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    content = (
        "[Desktop Entry]\nType=Application\n"
        "Name=AdGuard VPN CLI\nComment=Connect AdGuard VPN when the desktop session starts\n"
        f"Exec={_desktop_quote(binary)} connect --boot\n"
        "Terminal=false\nX-GNOME-Autostart-enabled=true\n"
    )
    temporary = target.with_suffix(".tmp")
    temporary.write_text(content, encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(target)
    return 0, f"Автозапуск включён для входа в графическую сессию: {target}"


def disable_autostart() -> tuple[int, str]:
    target = autostart_path()
    if target.is_symlink():
        return 2, f"Файл автозапуска является символической ссылкой; удаление отменено: {target}"
    if target.exists():
        target.unlink()
        return 0, f"Автозапуск AdGuard VPN CLI отключён: {target}"
    return 0, "Автозапуск AdGuard VPN CLI уже отключён."


def build_adguard_info_tab():
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk, GLib
    import threading

    root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=9)
    root.set_border_width(14)
    title = Gtk.Label()
    title.set_markup("<b>Инфо ADGuard</b>")
    title.set_xalign(0)
    root.pack_start(title, False, False, 0)

    note = Gtk.Label(
        label=("Управление официальным AdGuard VPN CLI (adguardvpn-cli), "
               "которым пользуется эта графическая оболочка. Это не отдельный "
               "AdGuard CLI — блокировщик рекламы."),
        xalign=0,
    )
    note.set_line_wrap(True)
    root.pack_start(note, False, False, 0)

    view = Gtk.TextView()
    view.set_editable(False)
    view.set_cursor_visible(False)
    view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
    view.get_buffer().set_text("Проверка наличия AdGuard VPN CLI…")
    scroll = Gtk.ScrolledWindow()
    scroll.set_vexpand(True)
    scroll.set_min_content_height(160)
    scroll.add(view)
    root.pack_start(scroll, True, True, 0)

    buttons = []

    def show(text):
        view.get_buffer().set_text(text)

    def finish(result, label):
        code, output = result
        for button in buttons:
            button.set_sensitive(True)
        show(f"{label}\n\nКод завершения: {code}\n{output or 'Команда выполнена без дополнительного вывода.'}")
        return False

    def run_async(label, operation):
        for button in buttons:
            button.set_sensitive(False)
        show(label + "\n\nВыполняется…")
        def worker():
            try:
                result = operation()
            except Exception as exc:
                result = (1, str(exc))
            GLib.idle_add(finish, result, label)
        threading.Thread(target=worker, daemon=True).start()

    def confirm(label, description, operation):
        dialog = Gtk.MessageDialog(
            transient_for=root.get_toplevel() if isinstance(root.get_toplevel(), Gtk.Window) else None,
            flags=Gtk.DialogFlags.MODAL, message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.CANCEL, text=label,
        )
        dialog.format_secondary_text(description)
        dialog.add_button("Продолжить", Gtk.ResponseType.OK)
        answer = dialog.run()
        dialog.destroy()
        if answer == Gtk.ResponseType.OK:
            run_async(label, operation)

    def add(row, label, tooltip, callback):
        button = Gtk.Button(label=label)
        button.set_tooltip_text(tooltip)
        button.connect("clicked", lambda *_: callback())
        row.pack_start(button, False, False, 0)
        buttons.append(button)

    for _ in range(4):
        row = Gtk.Box(spacing=6)
        root.pack_start(row, False, False, 0)
        if _ == 0:
            add(row, "Проверить установку", "Версия и состояние VPN", lambda: run_async("Состояние AdGuard VPN CLI", lambda: (0, get_status())))
            add(row, "Установить / переустановить", "Официальный установщик AdGuard VPN CLI", lambda: confirm("Установить AdGuard VPN CLI", "Будет загружен официальный release-скрипт из репозитория AdguardTeam/AdGuardVPNCLI по HTTPS. Скрипт сам запросит необходимые права.", install_official))
            add(row, "Проверить обновления", "adguardvpn-cli check-update", lambda: run_async("Проверка обновлений", check_update))
        elif _ == 1:
            add(row, "Обновить VPN CLI", "Официальная команда обновления", lambda: confirm("Обновить AdGuard VPN CLI", "Будет выполнена официальная команда adguardvpn-cli update.", update_vpn))
            add(row, "Подключить", "Подключиться к последней или быстрой локации", lambda: run_async("Подключение AdGuard VPN", connect_vpn))
            add(row, "Отключить", "Отключить VPN", lambda: run_async("Отключение AdGuard VPN", disconnect_vpn))
        elif _ == 2:
            add(row, "Включить автозапуск", "Подключать VPN при входе в графическую сессию", lambda: run_async("Включение автозапуска", enable_autostart))
            add(row, "Отключить автозапуск", "Удалить созданный ярлык автозапуска", lambda: run_async("Отключение автозапуска", disable_autostart))
            add(row, "Очистить кэш", "Удалить только ~/.cache/adguardvpn-cli", lambda: confirm("Очистить кэш AdGuard VPN CLI", "Будет удалён только XDG-каталог кэша adguardvpn-cli. Настройки и данные авторизации не затрагиваются.", clear_cache))
        else:
            add(row, "Удалить все данные пользователя", "Удалить пользовательские данные, конфигурацию и кэш", lambda: confirm("Удалить все данные AdGuard VPN CLI?", "Будут удалены только пользовательские XDG-каталоги adguardvpn-cli: данные, конфигурация и кэш. Это может удалить авторизацию и настройки. Сам исполняемый файл не удаляется.", clear_user_data))

    run_async("Проверка установки", lambda: (0, get_status()))
    return root
