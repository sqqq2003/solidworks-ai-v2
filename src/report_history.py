"""Read-only listing of saved project queue reports; never reruns jobs or opens CAD."""
from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import re
import subprocess
import sys

REPORT_NAME = re.compile(r'^project-report-[0-9a-f]{32}\.json$')
MAX_REPORT_BYTES = 16 * 1024 * 1024


def load_report(path) -> dict:
    path = Path(path)
    if path.stat().st_size > MAX_REPORT_BYTES:
        raise ValueError('报告超过 16 MB，未读取')
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict) or not isinstance(data.get('results', []), list):
        raise ValueError('报告格式无效')
    return data


def summarize_report(path, mtime=None) -> dict:
    """One row per report; unreadable files are listed with the reason, not hidden."""
    path = Path(path)
    if mtime is None:
        mtime = path.stat().st_mtime
    entry = {'path': str(path), 'written_at': datetime.fromtimestamp(mtime).astimezone().isoformat(timespec='seconds'),
             'status': None, 'counts': {}, 'tasks': 0, 'names': [], 'artifacts': [], 'error': None}
    try:
        report = load_report(path)
    except (OSError, ValueError, UnicodeError) as exc:
        entry['error'] = str(exc)
        return entry
    results = [row for row in report.get('results', []) if isinstance(row, dict)]
    counts = report.get('counts')
    entry.update(status=report.get('status') if isinstance(report.get('status'), str) else None,
                 counts=counts if isinstance(counts, dict) else {},
                 tasks=len(results),
                 names=[str(row.get('name', row.get('kind', '任务'))) for row in results],
                 artifacts=[str(row['artifact']['path']) for row in results
                            if isinstance(row.get('artifact'), dict) and row['artifact'].get('path')])
    return entry


def list_reports(folder, *, limit: int = 100) -> list[dict]:
    """Newest first, by file modification time; a missing folder means no history."""
    if type(limit) is not int or limit < 1:
        raise ValueError('limit must be a positive integer')
    try:
        candidates = [path for path in Path(folder).iterdir() if REPORT_NAME.match(path.name)]
    except OSError:
        return []
    stamped = []
    for path in candidates:
        try:
            if path.is_file():
                stamped.append((path.stat().st_mtime, path))
        except OSError:
            continue
    stamped.sort(key=lambda item: item[0], reverse=True)
    return [summarize_report(path, mtime) for mtime, path in stamped[:limit]]


def open_folder(path) -> None:
    """Show a folder in the system file browser; never opens files inside it."""
    folder = Path(path)
    if not folder.is_dir():
        raise FileNotFoundError(f'文件夹不存在：{folder}')
    if sys.platform == 'win32':
        os.startfile(str(folder))
    elif sys.platform == 'darwin':
        subprocess.Popen(['open', str(folder)])
    else:
        subprocess.Popen(['xdg-open', str(folder)])
