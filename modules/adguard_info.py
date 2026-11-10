"""Management panel for the separate AdGuard CLI ad blocker (adguard-cli).

This module deliberately does not call adguardvpn-cli: the two products have
different executables and responsibilities.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import threading
import urllib.request
from pathlib import Path

INSTALLER_URL = "https://raw.githubusercontent.com/AdguardTeam/AdGuardCLI/release/install.sh"


def run_adguard(args: list[str], timeout: int = 90) -> tuple[int, str]:
    try:
        result = subprocess.run(
            ["adguard-cli", *args], text=True, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, timeout=timeout, check=False,
        )
        return result.returncode, result.stdout.strip()
    except FileNotFoundError:
        return 127, "Команда adguard-cli не найдена. AdGuard CLI не установлен."
    except subprocess.TimeoutExpired:
        return 124, "Операция превысила допустимое время ожидания."
    except OSError as exc:
        return 1, str(exc)


def installed() -> bool:
    return shutil.which("adguard-cli") is not None


def get_status() -> str:
    if not installed():
        return "AdGuard CLI не обнаружен (исполняемый файл adguard-cli отсутствует)."
    version_code, version = run_adguard(["--version"], timeout=10)
    status_code, status = run_adguard(["status"], timeout=20)
    return "\n".join([
        "AdGuard CLI (блокировщик рекламы)",
        "Версия: " + (version if version_code == 0 else "не удалось определить"),
        "Состояние:",
        status if status else ("Код завершения: " + str(status_code)),
    ])


def install_or_update() -> tuple[int, str]:
    """Download the official release installer over HTTPS, then invoke via polkit."""
    try:
        request = urllib.request.Request(
            INSTALLER_URL, headers={"User-Agent": "ADGuard-VPN-Desktop"}
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            if response.status != 200:
                return 1, f"Сервер установки вернул HTTP {response.status}."
            script = response.read(2_000_001)
        if len(script) > 2_000_000:
            return 1, "Скрипт установки неожиданно велик; выполнение отменено."
        if not script.startswith(b"#!") or b"AdGuard" not in script[:200_000]:
            return 1, "Полученный файл не похож на официальный скрипт AdGuard; выполнение отменено."
        with tempfile.NamedTemporaryFile(prefix="adguard-cli-install-", suffix=".sh", delete=False) as stream:
            stream.write(script)
            script_path = Path(stream.name)
        try:
            result = subprocess.run(
                ["pkexec", "sh", str(script_path), "-v"],
                text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                timeout=900, check=False,
            )
            return result.returncode, result.stdout.strip()
        finally:
            script_path.unlink(missing_ok=True)
    except FileNotFoundError:
        return 127, "Не найден pkexec. Установите AdGuard CLI вручную по официальной инструкции."
    except Exception as exc:
        return 1, str(exc)


def clear_cache() -> tuple[int, str]:
    cache_home = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    target = cache_home / "adguard-cli"
    if not target.exists():
        return 0, f"Каталог кэша не найден: {target}\nНечего очищать."
    if not target.is_dir() or target.is_symlink():
        return 2, f"Ожидался обычный каталог кэша; операция отменена: {target}"
    shutil.rmtree(target)
    return 0, f"Кэш удалён: {target}"


def clear_user_data() -> tuple[int, str]:
    """Remove only XDG-scoped per-user AdGuard CLI data/config directories."""
    data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    targets = [data_home / "adguard-cli", config_home / "adguard-cli"]
    removed = []
    for target in targets:
        if target.is_symlink():
            return 2, f"Обнаружена символическая ссылка; удаление отменено: {target}"
        if target.exists():
            if not target.is_dir():
                return 2, f"Ожидался каталог; удаление отменено: {target}"
            shutil.rmtree(target)
            removed.append(str(target))
    if not removed:
        return 0, "Пользовательские каталоги AdGuard CLI не найдены."
    return 0, "Удалены пользовательские данные:\n" + "\n".join(removed)


def set_service_autostart(enabled: bool) -> tuple[int, str]:
    return run_adguard(["install-service"] + ([] if enabled else ["-u"]), timeout=120)


def build_adguard_info_tab():
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk, GLib

    root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    root.set_border_width(14)

    heading = Gtk.Label()
    heading.set_markup("<b>Инфо ADGuard</b>")
    heading.set_xalign(0)
    root.pack_start(heading, False, False, 0)

    note = Gtk.Label(
        label=("Здесь управляется отдельный AdGuard CLI (adguard-cli) — блокировщик "
               "рекламы. Это не AdGuard VPN CLI (adguardvpn-cli), которым управляет "
               "вкладка «Подключение». Автоматическая фильтрация AdGuard CLI может "
               "конфликтовать с VPN CLI в режиме TUN."),
        xalign=0,
    )
    note.set_line_wrap(True)
    root.pack_start(note, False, False, 0)

    status = Gtk.TextView()
    status.set_editable(False)
    status.set_cursor_visible(False)
    status.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
    status.get_buffer().set_text("Проверка наличия AdGuard CLI…")
    scroller = Gtk.ScrolledWindow()
    scroller.set_vexpand(True)
    scroller.set_min_content_height(180)
    scroller.add(status)
    root.pack_start(scroller, True, True, 0)

    buttons: list[Gtk.Widget] = []

    def show_result(text: str):
        status.get_buffer().set_text(text)

    def finish(result, title):
        for button in buttons:
            button.set_sensitive(True)
        code, output = result
        show_result(f"{title}\n\nКод завершения: {code}\n{output or 'Команда выполнена без дополнительного вывода.'}")
        return False

    def run_async(title, operation):
        for button in buttons:
            button.set_sensitive(False)
        show_result(title + "\n\nВыполняется…")
        def worker():
            try:
                result = operation()
            except Exception as exc:
                result = (1, str(exc))
            GLib.idle_add(finish, result, title)
        threading.Thread(target=worker, daemon=True).start()

    def confirm(title, body, operation):
        dialog = Gtk.MessageDialog(
            transient_for=root.get_toplevel() if isinstance(root.get_toplevel(), Gtk.Window) else None,
            flags=Gtk.DialogFlags.MODAL, message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.CANCEL, text=title,
        )
        dialog.format_secondary_text(body)
        dialog.add_button("Продолжить", Gtk.ResponseType.OK)
        response = dialog.run()
        dialog.destroy()
        if response == Gtk.ResponseType.OK:
            run_async(title, operation)

    def add(parent, label, tooltip, callback):
        button = Gtk.Button(label=label)
        button.set_tooltip_text(tooltip)
        button.connect("clicked", lambda *_: callback())
        parent.pack_start(button, False, False, 0)
        buttons.append(button)

    row1 = Gtk.Box(spacing=6)
    row2 = Gtk.Box(spacing=6)
    row3 = Gtk.Box(spacing=6)
    for row in (row1, row2, row3):
        root.pack_start(row, False, False, 0)

    add(row1, "Проверить установку", "Проверить наличие и версию adguard-cli", lambda: run_async("Состояние AdGuard CLI", lambda: (0, get_status())))
    add(row1, "Установить / обновить", "Загрузить официальный скрипт AdGuard и запустить его через polkit", lambda: confirm("Установка или обновление AdGuard CLI", "Будет загружен официальный release-скрипт из репозитория AdguardTeam/AdGuardCLI и запущен с правами администратора.", install_or_update))
    add(row1, "Проверить обновления", "Выполнить adguard-cli check-update", lambda: run_async("Проверка обновлений", lambda: run_adguard(["check-update"], 180)))

    add(row2, "Запустить", "Включить защиту AdGuard CLI", lambda: run_async("Запуск AdGuard CLI", lambda: run_adguard(["start"])))
    add(row2, "Остановить", "Остановить защиту AdGuard CLI", lambda: run_async("Остановка AdGuard CLI", lambda: run_adguard(["stop"])))
    add(row2, "Обновить", "Выполнить adguard-cli update", lambda: confirm("Обновить AdGuard CLI", "Будут обновлены приложение и его компоненты.", lambda: run_adguard(["update", "-v"], 600)))

    add(row3, "Включить автозапуск", "Установить системную службу AdGuard CLI", lambda: confirm("Включить автозапуск", "AdGuard CLI будет установлен как системная служба и сможет запускаться при загрузке системы.", lambda: set_service_autostart(True)))
    add(row3, "Отключить автозапуск", "Удалить системную службу AdGuard CLI", lambda: confirm("Отключить автозапуск", "Системная служба AdGuard CLI будет удалена. Само приложение останется установленным.", lambda: set_service_autostart(False)))
    add(row3, "Очистить кэш", "Удалить только XDG-каталог кэша adguard-cli", lambda: confirm("Очистить кэш", "Будет удалён только каталог ~/.cache/adguard-cli (или XDG_CACHE_HOME/adguard-cli). Настройки и лицензия не затрагиваются.", clear_cache))
    add(row3, "Удалить данные пользователя", "Удалить XDG-каталоги конфигурации и данных AdGuard CLI", lambda: confirm("Удалить все пользовательские данные AdGuard CLI?", "Будут удалены только XDG_DATA_HOME/adguard-cli и XDG_CONFIG_HOME/adguard-cli. Это может удалить конфигурацию и локальные данные. Приложение в /opt не удаляется.", clear_user_data))

    run_async("Проверка установки", lambda: (0, get_status()))
    return root
