"""Persist the user's application split-tunnel selection (without applying routes).

The file lives in the user's XDG config directory and is written atomically.
This stores intent only; it does not create nftables or ip rules.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Iterable

APP_CONFIG_DIR = "adguard-vpn-desktop"
SELECTION_FILE = "applications.json"
SCHEMA_VERSION = 2


def selection_path(environ=None) -> Path:
    env = os.environ if environ is None else environ
    base = env.get("XDG_CONFIG_HOME")
    if base:
        return Path(base).expanduser() / APP_CONFIG_DIR / SELECTION_FILE
    return Path.home() / ".config" / APP_CONFIG_DIR / SELECTION_FILE


def load_selection(path: Path | None = None) -> dict:
    """Load persisted selection; missing files produce an empty selection."""
    target = Path(path) if path is not None else selection_path()
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"selected_ids": [], "custom_paths": [], "mode": "selected"}
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Не удалось прочитать сохранённый выбор приложений: {exc}") from exc

    if not isinstance(raw, dict) or raw.get("schema_version") not in (1, SCHEMA_VERSION):
        raise ValueError("Неизвестный формат сохранённого выбора приложений.")
    selected = raw.get("selected_ids", [])
    custom = raw.get("custom_paths", [])
    if not isinstance(selected, list) or not all(isinstance(x, str) and x for x in selected):
        raise ValueError("Повреждён список выбранных приложений.")
    if not isinstance(custom, list) or not all(isinstance(x, str) and x.startswith("/") for x in custom):
        raise ValueError("Повреждён список пользовательских путей.")
    mode = raw.get("mode", "selected")
    if mode not in ("all", "selected"):
        raise ValueError("Недопустимый режим маршрутизации приложений.")
    return {
        "selected_ids": sorted(set(selected)),
        "custom_paths": sorted(set(custom)),
        "mode": mode,
    }


def save_selection(
    selected_ids: Iterable[str],
    custom_paths: Iterable[str],
    path: Path | None = None,
    *,
    mode: str = "selected",
) -> Path:
    """Atomically save IDs and absolute custom executable paths."""
    target = Path(path) if path is not None else selection_path()
    if mode not in ("all", "selected"):
        raise ValueError("Недопустимый режим маршрутизации приложений.")
    ids = sorted({item for item in selected_ids if isinstance(item, str) and item})
    paths = sorted({
        str(Path(item).expanduser().resolve())
        for item in custom_paths
        if isinstance(item, str) and item.startswith("/")
    })
    payload = {
        "schema_version": SCHEMA_VERSION,
        "mode": mode,
        "selected_ids": ids,
        "custom_paths": paths,
    }
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".applications-", dir=target.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, sort_keys=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        os.chmod(target, 0o600)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
    return target
