"""One-shot real-machine smoke for the live path. Run on an operator PC only.

    SW_LIVE_SMOKE_CONFIRM=1 SW_EXE="C:\\Program Files\\SOLIDWORKS\\SLDWORKS.exe" \
    python work/smoke_live_once.py \
        --assembly "D:\\...\\test.SLDASM" \
        --save-as  "D:\\...\\test-copy.SLDASM" \
        --mapping  runtime\\live-smoke-mapping.json \
        --out      results\\windows\\live_smoke.json

Gates (every one must pass before anything is executed):

1. ``SW_LIVE_SMOKE_CONFIRM=1`` must be set explicitly — this script never
   runs by accident.
2. The assembly must exist and end in ``.SLDASM``; the destination must be a
   different path, also ``.SLDASM`` (the source is never overwritten).
3. ``SLDWORKS.exe`` must exist and be named exactly ``SLDWORKS.exe``.
4. COM (pywin32) must be importable.
5. The mapping payload must exist and every value must be confirmed.

If any gate fails the script prints a refusal report and exits 2 without
touching SolidWorks. When all gates pass it calls the existing
``sw_api.win32com_backend.apply_live`` and writes the evidence JSON.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

CONFIRM_ENV = "SW_LIVE_SMOKE_CONFIRM"
SW_EXE_ENV = "SW_EXE"


def _gates(args: argparse.Namespace) -> list[dict]:
    rows: list[dict] = []
    rows.append(
        {
            "gate": "explicit_confirm",
            "ok": os.environ.get(CONFIRM_ENV) == "1",
            "detail": f"set {CONFIRM_ENV}=1 to acknowledge this opens SolidWorks once",
        }
    )
    assembly = Path(args.assembly).expanduser()
    save_as = Path(args.save_as).expanduser()
    rows.append({"gate": "assembly_exists", "ok": assembly.is_file(), "detail": str(assembly)})
    rows.append(
        {
            "gate": "work_copy_rules",
            "ok": (
                assembly.suffix.lower() == ".sldasm"
                and save_as.suffix.lower() == ".sldasm"
                and assembly.resolve() != save_as.resolve()
            ),
            "detail": "source and destination must both be .SLDASM and different paths",
        }
    )
    sw_exe = Path(os.environ.get(SW_EXE_ENV, args.sw_exe or "")).expanduser()
    rows.append(
        {
            "gate": "sldworks_installed",
            "ok": sw_exe.is_file() and sw_exe.name.casefold() == "sldworks.exe",
            "detail": f"{sw_exe} (from ${SW_EXE_ENV} or --sw-exe)",
        }
    )
    from src.sw_api.win32com_backend import com_available

    rows.append({"gate": "com_available", "ok": com_available(), "detail": "pythoncom importable"})
    mapping = None
    mapping_ok = False
    mapping_detail = "mapping file missing"
    try:
        mapping = json.loads(Path(args.mapping).read_text(encoding="utf-8"))
        values = mapping.get("values", mapping)
        unconfirmed = [key for key, row in values.items() if isinstance(row, dict) and row.get("confirmed") is not True]
        mapping_ok = bool(values) and not unconfirmed
        mapping_detail = "all values confirmed" if mapping_ok else f"unconfirmed: {unconfirmed}"
    except (OSError, json.JSONDecodeError) as exc:
        mapping_detail = f"mapping unreadable: {exc}"
    rows.append({"gate": "mapping_confirmed", "ok": mapping_ok, "detail": mapping_detail})
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="one-shot live smoke (operator PC only)")
    parser.add_argument("--assembly", required=True)
    parser.add_argument("--save-as", required=True)
    parser.add_argument("--mapping", required=True)
    parser.add_argument("--sw-exe", default=None)
    parser.add_argument("--out", default=str(ROOT / "results" / "windows" / "live_smoke.json"))
    args = parser.parse_args(argv)

    rows = _gates(args)
    report = {
        "module": "live-smoke-once",
        "gates": rows,
        "cad_executed": False,
        "sw_live": "not_executed",
    }
    if not all(row["ok"] for row in rows):
        report["status"] = "refused"
        report["refused_gates"] = [row["gate"] for row in rows if not row["ok"]]
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 2

    from src.a01_parametric.solver import solve_spec
    from src.sw_api.windows_execution import WindowsExecutionPort
    from src.sw_api.win32com_backend import apply_live

    plan = solve_spec()
    report["status"] = "executing"
    try:
        result = apply_live(
            plan,
            Path(args.assembly).expanduser(),
            Path(args.save_as).expanduser(),
            mapping_payload=json.loads(Path(args.mapping).read_text(encoding="utf-8")),
            driver=WindowsExecutionPort(None),
        )
        report["status"] = "live_executed"
        report["cad_executed"] = True
        report["result"] = result
    except Exception as exc:  # reported, not hidden
        report["status"] = "failed"
        report["error"] = str(exc)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "live_executed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
