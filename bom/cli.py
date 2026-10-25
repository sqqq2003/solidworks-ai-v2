"""CLI for BOM generation.

  python -m bom.cli assembly.json --out-dir out
  python -m bom.cli assembly.json --out-dir out --dependency-report precheck.json

Writes out/bom.json + out/bom.csv (UTF-8-SIG, Excel-readable) +
out/bom_table.txt. Exit codes: 0 = BOM ok; 1 = pending
(documents still written); 2 = input error. Input files are never
modified.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .bom import BomError, build_bom, render_csv, render_table


def _load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("document must be a JSON object")
    return data


def run(input_path: str, out_dir: str,
        dependency_path: str | None = None) -> int:
    try:
        assembly = _load_json(input_path)
        report = (
            _load_json(dependency_path)
            if dependency_path is not None
            else None
        )
    except (OSError, ValueError) as exc:
        print("input error: %s" % exc, file=sys.stderr)
        return 2
    try:
        result = build_bom(assembly, report)
    except BomError as exc:
        print("input error: %s" % exc, file=sys.stderr)
        return 2
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "bom.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (out / "bom.csv").write_text(
        render_csv(result), encoding="utf-8-sig"
    )
    (out / "bom_table.txt").write_text(
        render_table(result), encoding="utf-8"
    )
    if result["status"] == "ok":
        print(
            "ok: BOM for %s, %d rows"
            % (result["assembly_name"], len(result["rows"]))
        )
        return 0
    print(
        "BOM pending: %s" % "; ".join(result["pending"]),
        file=sys.stderr,
    )
    return 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="BOM generation.")
    parser.add_argument("input", help="assembly JSON")
    parser.add_argument("--out-dir", required=True,
                        help="output directory")
    parser.add_argument("--dependency-report",
                        help="optional dependency_engine precheck JSON")
    args = parser.parse_args(argv)
    return run(args.input, args.out_dir, args.dependency_report)


if __name__ == "__main__":
    raise SystemExit(main())
