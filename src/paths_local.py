# -*- coding: utf-8 -*-
"""本机钣金导入/导出目录约定（Windows）。"""

from __future__ import annotations

from pathlib import Path
import os

ROOT = Path(os.environ.get("SW_AI_WORKSPACE", str(Path(__file__).resolve().parents[1] / "runtime"))).expanduser().resolve()
SELFTEST = ROOT / "自测"
BACKUP = ROOT / "备份"
TEMP = ROOT / "临时"
EXPORT = ROOT / "导出"


def ensure_dirs() -> None:
    for path in (ROOT, SELFTEST, BACKUP, TEMP, EXPORT):
        path.mkdir(parents=True, exist_ok=True)


def export_dir_for(drawing_name: str) -> Path:
    ensure_dirs()
    safe = "".join(ch if ch not in '<>:"/\\|?*' else "_" for ch in drawing_name).strip() or "未命名"
    path = EXPORT / safe
    path.mkdir(parents=True, exist_ok=True)
    return path


def temp_dxf_dir() -> Path:
    ensure_dirs()
    path = TEMP / "dxf"
    path.mkdir(parents=True, exist_ok=True)
    return path
