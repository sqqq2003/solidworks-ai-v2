"""CLI for the simulated A01 parametric redesign.

    python -m src.a01_parametric.cli --length 1800 --width 900 --height 1500 --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.a01_next.drawing_export import drawing_export_skeleton
from src.a01_next.mate_check import check_mates
from src.a01_next.sheet_metal_hook import sheet_metal_hook
from src.a01_parametric.config import DEFAULT_ENVELOPE_MM
from src.a01_parametric.solver import solve_spec
from src.sw_api.apply import dry_run_apply


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="A01 参数化改型（云端为模拟 dry-run，不连接 SolidWorks）")
    parser.add_argument("--length", type=float, default=DEFAULT_ENVELOPE_MM["length"])
    parser.add_argument("--width", type=float, default=DEFAULT_ENVELOPE_MM["width"])
    parser.add_argument("--height", type=float, default=DEFAULT_ENVELOPE_MM["height"])
    parser.add_argument("--spec", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--live", action="store_true", help="Windows only. SaveAs a work copy; never overwrite the source.")
    parser.add_argument("--assembly", type=Path, default=None)
    parser.add_argument("--save-as", type=Path, default=None)
    return parser


def _default_trace(length: float, width: float, height: float) -> Path:
    folder = ROOT / "runtime" / "a01-parametric"
    name = f"A01-{length:g}x{width:g}x{height:g}.dry-run.json"
    return folder / name


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.live and args.dry_run:
        print(json.dumps({"status": "failed", "error": "choose either --dry-run or --live"}, ensure_ascii=False))
        return 1
    try:
        plan = solve_spec(args.spec, length=args.length, width=args.width, height=args.height)
        report: dict = {
            "plan": plan,
            "dry_run": None,
            "live": None,
            "next_track": {
                "mate_check": check_mates(plan),
                "sheet_metal": sheet_metal_hook(plan),
                "drawing": drawing_export_skeleton(plan),
            },
        }
        if args.dry_run:
            destination = args.save_as or _default_trace(args.length, args.width, args.height)
            if destination.suffix.lower() != ".json":
                destination = destination.with_suffix(destination.suffix + ".dry-run.json")
            report["dry_run"] = dry_run_apply(plan, destination, source=args.assembly)
        elif args.live:
            if args.assembly is None or args.save_as is None:
                raise ValueError("--live requires --assembly and --save-as work-copy paths")
            from src.sw_api.win32com_backend import apply_live

            report["live"] = apply_live(plan, args.assembly, args.save_as)
        payload = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)
    except (OSError, KeyError, TypeError, ValueError, RuntimeError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc), "sw_live": "not_applicable_on_linux"}, ensure_ascii=False))
        text = str(exc)
        if "not_applicable_on_linux" in text or "COM is unavailable" in text:
            return 2
        return 1
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    if args.dry_run or args.live:
        return 0
    return 3 if plan["status"] == "review_required" else 0


if __name__ == "__main__":
    raise SystemExit(main())
