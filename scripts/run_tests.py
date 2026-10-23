"""Run the cloud regression using the project venv if it exists.

Prefers .venv/Scripts/python.exe (Windows) or .venv/bin/python (Unix) so that
results are reproducible without remembering a hard-coded interpreter path.
Falls back to the interpreter that invoked this script.
"""
from __future__ import annotations

import json
import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def project_python() -> Path:
    if platform.system() == "Windows":
        candidate = ROOT / ".venv" / "Scripts" / "python.exe"
    else:
        candidate = ROOT / ".venv" / "bin" / "python"
    if candidate.exists():
        return candidate
    return Path(sys.executable)


def main() -> int:
    py = project_python()
    print(f"Running tests with: {py}")
    result = subprocess.run(
        [str(py), str(ROOT / "work" / "run_cloud_tests.py")],
        cwd=ROOT,
    )
    if result.returncode != 0:
        return result.returncode

    report_path = ROOT / "results" / "cloud" / "latest.json"
    if report_path.exists():
        report = json.loads(report_path.read_text(encoding="utf-8"))
        print(
            f"\nSummary: {report['tests_run']} ran / "
            f"{report['passed']} passed / {report['failures']} failed / "
            f"{len(report.get('skipped', []))} skipped"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
