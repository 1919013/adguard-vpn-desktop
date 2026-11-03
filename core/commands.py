"""Safe command execution for the AdGuard VPN CLI."""
from __future__ import annotations

import subprocess
from collections.abc import Sequence

CLI = "adguardvpn-cli"


def run_cli(args: Sequence[str], timeout: int = 25) -> tuple[int, str]:
    """Run the CLI without a shell and return (exit_code, combined_output)."""
    if isinstance(args, (str, bytes)) or not all(isinstance(arg, str) for arg in args):
        return 2, "Аргументы команды должны быть последовательностью строк."
    try:
        result = subprocess.run(
            [CLI, *args],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
        return result.returncode, result.stdout.strip()
    except FileNotFoundError:
        return 127, "Не найден adguardvpn-cli. Установите официальный AdGuard VPN CLI."
    except subprocess.TimeoutExpired:
        return 124, "Команда выполняется слишком долго."
    except Exception as error:
        return 1, str(error)
