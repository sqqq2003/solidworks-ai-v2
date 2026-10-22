"""用户偏好持久化：板厚等参数、窗口位置、最近文件。

存放在 ``%LOCALAPPDATA%\\CadSheetMetalTool\\settings.json``（与日志同目录）。
读写都不允许影响主流程：任何异常都退化成默认值。
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from logging_setup import APP_FOLDER_NAME

SETTINGS_FILE_NAME = "settings.json"
MAX_RECENT_FILES = 8

# 钣金参数的默认值，同时也是界面上「恢复默认」按钮的依据。
DEFAULT_SHEET = {
    "thickness": "",
    "radius": "",
    "angle": "90",
    "material": "软钢/冷轧",
    "mode": "折弯扣除",
    "k_factor": "",
    "auto_bend": False,
    "flip": False,
}


def settings_directory() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    root = Path(base) if base else Path(__file__).resolve().parent
    return root / APP_FOLDER_NAME


def settings_path() -> Path:
    return settings_directory() / SETTINGS_FILE_NAME


def load_settings() -> dict[str, Any]:
    """读取设置；文件缺失或损坏时返回空字典。"""

    path = settings_path()
    try:
        # utf-8-sig：记事本 / PowerShell 写出的 JSON 常带 BOM，不能当成损坏文件。
        with path.open("r", encoding="utf-8-sig") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def save_settings(data: dict[str, Any]) -> bool:
    """原子写入设置；失败返回 False，绝不抛异常。"""

    path = settings_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=str(path.parent),
            prefix="settings-",
            suffix=".tmp",
            delete=False,
        )
        try:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        finally:
            handle.close()
        os.replace(handle.name, path)
        return True
    except OSError:
        return False


def sheet_defaults(stored: dict[str, Any] | None) -> dict[str, Any]:
    """把读取到的钣金参数与默认值合并，过滤掉类型不对的键。"""

    merged = dict(DEFAULT_SHEET)
    if not isinstance(stored, dict):
        return merged
    for key, fallback in DEFAULT_SHEET.items():
        value = stored.get(key, fallback)
        if isinstance(fallback, bool):
            merged[key] = bool(value)
        elif isinstance(value, str):
            merged[key] = value
    return merged


def update_recent(stored: dict[str, Any] | None, path: str | Path) -> list[str]:
    """把 path 提到最近文件列表最前，返回新列表。"""

    text = str(path)
    existing: list[str] = []
    if isinstance(stored, dict):
        raw = stored.get("recent_files")
        if isinstance(raw, list):
            existing = [item for item in raw if isinstance(item, str)]
    ordered = [text] + [item for item in existing if item != text]
    return ordered[:MAX_RECENT_FILES]


def recent_files(stored: dict[str, Any] | None) -> list[str]:
    """返回仍然存在于磁盘上的最近文件。"""

    if not isinstance(stored, dict):
        return []
    raw = stored.get("recent_files")
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, str) and Path(item).is_file()]
