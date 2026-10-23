"""CLI for the simulated QL-5050PX parametric preflight.

    python -m src.ql5050px.cli
    python -m src.ql5050px.cli --length 2000 --width 1000 --height 1600 --out plan.json

Every run stays offline: no SolidWorks connection, no CAD write. The plan is
always review_required while any dimension is unconfirmed or unmapped.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.ql5050px.config import DEFAULT_ENVELOPE_MM
from src.ql5050px.solver import solve_spec


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="QL-5050PX 参数化预检（离线模拟；不连接 SolidWorks，不写 CAD）"
    )
    parser.add_argument("--length", type=float, default=DEFAULT_ENVELOPE_MM["length"])
    parser.add_argument("--width", type=float, default=DEFAULT_ENVELOPE_MM["width"])
    parser.add_argument("--height", type=float, default=DEFAULT_ENVELOPE_MM["height"])
    parser.add_argument("--spec", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        plan = solve_spec(args.spec, length=args.length, width=args.width, height=args.height)
        payload = json.dumps(plan, ensure_ascii=False, indent=2, allow_nan=False)
    except (OSError, KeyError, TypeError, ValueError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False))
        return 1
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 3 if plan["status"] == "review_required" else 0


if __name__ == "__main__":
    raise SystemExit(main())
