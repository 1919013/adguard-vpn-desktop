"""AdGuard VPN CLI information and maintenance controls."""
from __future__ import annotations

import shutil
import subprocess
import threading

from core.vpn import VPNService


INSTALL_COMMAND = (
    "curl -fSsL "
    "https://raw.githubusercontent.com/AdguardTeam/AdGuardVPNCLI/HEAD/scripts/release/install.sh "
    "| sh -s -- -v"
)


def _terminal():
    return (
        shutil.which("x-terminal-emulator")
        or shutil.which("gnome-terminal")
        or shutil.which("xfce4-terminal")
        or shutil.which("konsole")
        or shutil.which("xterm")
    )


def _launch_interactive(command: str) -> tuple[bool, str]:
    terminal = _terminal()
    if not terminal:
        return False, "Не найден эмулятор терминала. Запустите официальную команду вручную."
    shell_command = command + "; printf '\\nОперация завершена. Нажмите Enter для закрытия.'; read -r"
    try:
        subprocess.Popen([terminal, "-e", "sh", "-lc", shell_command],
                         start_new_session=True, close_fds=True)
        return True, "Команда запущена в отдельном терминале. При необходимости введите пароль администратора там."
    except OSError as exc:
        return False, str(exc)


def launch_official_installer() -> tuple[bool, str]:
    """Open the official release installer in a terminal for interactive sudo."""
    return _launch_interactive(INSTALL_COMMAND)


def launch_cli_updater() -> tuple[bool, str]:
    """Run the CLI's built-in updater in a terminal so sudo prompts stay visible."""
    return _launch_interactive("adguardvpn-cli update -v")


def build_info_tab(vpn: VPNService | None = None):
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk, GLib

    vpn = vpn or VPNService()
    root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    root.set_border_width(14)

    title = Gtk.Label()
    title.set_markup("<b>Инфо ADGuard VPN CLI</b>")
    title.set_xalign(0)
    root.pack_start(title, False, False, 0)

    note = Gtk.Label(
        label="Этот раздел управляет именно официальным AdGuard VPN CLI, "
              "а не AdGuard для блокировки рекламы. Подключение и отключение VPN "
              "доступны на вкладке «Подключение»."
    )
    note.set_xalign(0)
    note.set_line_wrap(True)
    root.pack_start(note, False, False, 0)

    output = Gtk.TextView()
    output.set_editable(False)
    output.set_cursor_visible(False)
    output.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
    output.get_buffer().set_text("Проверьте установленную версию CLI.")
    scroll = Gtk.ScrolledWindow()
    scroll.set_vexpand(True)
    scroll.add(output)
    root.pack_start(scroll, True, True, 0)

    row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    root.pack_start(row, False, False, 0)
    check = Gtk.Button(label="Проверить версию и обновления")
    update = Gtk.Button(label="Обновить AdGuard VPN CLI")
    install = Gtk.Button(label="Установить официальный CLI")
    row.pack_start(check, False, False, 0)
    row.pack_start(update, False, False, 0)
    row.pack_start(install, False, False, 0)
    cli_installed = shutil.which("adguardvpn-cli") is not None
    update.set_sensitive(cli_installed)
    install.set_sensitive(not cli_installed)

    warning = Gtk.Label(
        label="Очистка кэша и удаление пользовательских данных не предлагаются: "
              "для VPN CLI не подтверждена безопасная универсальная команда очистки. "
              "Не удаляйте каталог данных вручную — там могут находиться настройки и учётные данные."
    )
    warning.set_xalign(0)
    warning.set_line_wrap(True)
    root.pack_start(warning, False, False, 0)

    def set_output(text):
        output.get_buffer().set_text(text)

    def run_async(label, operation):
        for button in (check, update, install):
            button.set_sensitive(False)
        set_output(label + "…")
        def worker():
            try:
                result = operation()
            except Exception as exc:
                result = str(exc)
            GLib.idle_add(finish, result)
        def finish(result):
            set_output(str(result))
            check.set_sensitive(True)
            installed_now = shutil.which("adguardvpn-cli") is not None
            update.set_sensitive(installed_now)
            install.set_sensitive(not installed_now)
            return False
        threading.Thread(target=worker, daemon=True).start()

    def do_check(_button):
        def operation():
            path = shutil.which("adguardvpn-cli")
            if not path:
                return "AdGuard VPN CLI не найден в PATH.\nИспользуйте кнопку установки."
            code, version = vpn.version()
            lines = [f"Исполняемый файл: {path}", f"Версия (код {code}):", version]
            update_code, update_output = vpn.check_update()
            lines.extend(["", f"Проверка обновлений (код {update_code}):", update_output])
            return "\n".join(lines)
        run_async("Проверка AdGuard VPN CLI", operation)

    def do_update(_button):
        dialog = Gtk.MessageDialog(
            transient_for=root.get_toplevel() if isinstance(root.get_toplevel(), Gtk.Window) else None,
            flags=Gtk.DialogFlags.MODAL,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.CANCEL,
            text="Обновить AdGuard VPN CLI?",
        )
        dialog.format_secondary_text(
            "Откроется отдельный терминал с официальной командой "
            "adguardvpn-cli update -v. Там будут видны запросы пароля и ход обновления."
        )
        dialog.add_button("Обновить", Gtk.ResponseType.OK)
        response = dialog.run()
        dialog.destroy()
        if response == Gtk.ResponseType.OK:
            ok, message = launch_cli_updater()
            set_output(message)

    def do_install(_button):
        dialog = Gtk.MessageDialog(
            transient_for=root.get_toplevel() if isinstance(root.get_toplevel(), Gtk.Window) else None,
            flags=Gtk.DialogFlags.MODAL,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.CANCEL,
            text="Запустить официальный установщик?",
        )
        dialog.format_secondary_text(
            "Откроется терминал с установочным скриптом из официального репозитория "
            "AdguardTeam/AdGuardVPNCLI. Установщик может запросить пароль администратора."
        )
        dialog.add_button("Запустить", Gtk.ResponseType.OK)
        response = dialog.run()
        dialog.destroy()
        if response == Gtk.ResponseType.OK:
            ok, message = launch_official_installer()
            set_output(message)

    check.connect("clicked", do_check)
    update.connect("clicked", do_update)
    install.connect("clicked", do_install)
    return root
