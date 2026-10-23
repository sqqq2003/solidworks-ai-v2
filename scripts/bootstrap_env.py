"""Bootstrap a project-local Python venv so tests do not depend on hard-coded paths.

Creates .venv/ in the repo root, installs the platform-appropriate requirements
file, and verifies that ezdxf and the local generators are importable.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENV = ROOT / ".venv"
REQUIREMENTS = (
    ROOT / "requirements-offline.lock.txt"
    if platform.system() == "Windows"
    else ROOT / "requirements-cloud.txt"
)


def _python_in_venv() -> Path:
    if platform.system() == "Windows":
        return VENV / "Scripts" / "python.exe"
    return VENV / "bin" / "python"


def _pip_in_venv() -> Path:
    if platform.system() == "Windows":
        return VENV / "Scripts" / "pip.exe"
    return VENV / "bin" / "pip"


def create_venv(base_python: str | None = None) -> Path:
    base = Path(base_python) if base_python else Path(sys.executable)
    if VENV.exists():
        print(f"Using existing venv: {VENV}")
    else:
        print(f"Creating venv at {VENV} using {base}")
        subprocess.run([str(base), "-m", "venv", str(VENV)], check=True)
    return _python_in_venv()


def install_requirements() -> None:
    pip = _pip_in_venv()
    if not REQUIREMENTS.exists():
        raise FileNotFoundError(f"Requirements file not found: {REQUIREMENTS}")
    print(f"Installing from {REQUIREMENTS.name}")
    subprocess.run(
        [str(pip), "install", "--upgrade", "pip"],
        check=False,
    )
    subprocess.run(
        [str(pip), "install", "-r", str(REQUIREMENTS)],
        check=True,
    )


def verify_imports(python: Path) -> dict[str, bool]:
    root = ROOT.as_posix()
    probe = "\n".join(
        [
            "import importlib.util, sys",
            f"sys.path[:0] = [{root!r}, {root + '/src'!r}]",
            "mods = ['ezdxf']",
            "for m in mods:",
            "    print(m, importlib.util.find_spec(m) is not None)",
            "try:",
            "    import solidworks_generator",
            "    print('solidworks_generator', True)",
            "except Exception as exc:",
            "    print('solidworks_generator', False, str(exc))",
        ]
    )
    result = subprocess.run(
        [str(python), "-c", probe],
        capture_output=True,
        text=True,
        check=False,
    )
    print(result.stdout, end="")
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
    ok = "solidworks_generator True" in result.stdout and "ezdxf True" in result.stdout
    return {"ok": ok, "stdout": result.stdout, "stderr": result.stderr}


def main() -> int:
    base_python = os.environ.get("PROJECT_PYTHON") or (
        sys.argv[1] if len(sys.argv) > 1 else None
    )
    try:
        python = create_venv(base_python)
        install_requirements()
        report = verify_imports(python)
        if not report["ok"]:
            print("Import verification failed.", file=sys.stderr)
            return 1
        print(f"\nProject venv ready: {python}")
        print(f"Run tests with: {sys.executable} scripts/run_tests.py")
        return 0
    except subprocess.CalledProcessError as exc:
        print(f"Bootstrap failed: {exc}", file=sys.stderr)
        return 1
    except FileNotFoundError as exc:
        print(f"Bootstrap failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
