"""Command-line entry for the dependency precheck engine.

Usage:
    python -m dependency_engine.cli machine.json --out-dir out
    python -m dependency_engine.cli machine.json --out-dir out --change machine_width

Exit codes (same convention as modules 3 and 4):
    0 = precheck ok (no pending items, no errors);
    1 = report written but the machine is pending or conflicting;
    2 = input error (missing file, bad JSON, wrong format, duplicate
        name, dependency cycle, ambiguous value+formula, unknown
        formula op, or non-explicit unit).

The input file is never modified; only precheck.json is written under
--out-dir. The report is a static precheck: it never writes CAD files
and never talks to SolidWorks.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .engine import InputError, precheck


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Whole-machine dependency precheck")
    parser.add_argument("machine", help="machine JSON (dependency-engine/1)")
    parser.add_argument("--out-dir", required=True, help="directory for precheck.json")
    parser.add_argument(
        "--change",
        default=None,
        help="only print the confirm chain for this parameter (report still full)",
    )
    args = parser.parse_args(argv)
    machine_path = Path(args.machine)
    if not machine_path.is_file():
        print("input file not found: %s" % machine_path, file=sys.stderr)
        return 2
    try:
        data = json.loads(machine_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print("input is not readable JSON: %s" % exc, file=sys.stderr)
        return 2
    try:
        report = precheck(data)
    except InputError as exc:
        print("input error: %s" % exc, file=sys.stderr)
        return 2
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "precheck.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    if args.change is not None:
        chains = {c["change"]: c for c in report["confirm_chains"]}
        if args.change not in chains:
            print("unknown parameter: %s" % args.change, file=sys.stderr)
            return 2
        print(json.dumps(chains[args.change], indent=2, ensure_ascii=False))
    print(
        "status=%s pending=%d conflicts=%d (errors=%d, warnings=%d)"
        % (
            report["status"],
            len(report["pending_items"]),
            len(report["conflicts"]),
            sum(1 for c in report["conflicts"] if c["severity"] == "error"),
            sum(1 for c in report["conflicts"] if c["severity"] == "warning"),
        )
    )
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
