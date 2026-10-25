"""CLI for drawing template + mock render.

  python -m drawing_gen.cli drawing.json --out-dir out

Writes out/drawing.json. Exit codes: 0 = template ok; 1 = pending
(drawing.json still written); 2 = input error. The input file is
never modified.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .drawing import DrawingError, build_drawing


def run(input_path: str, out_dir: str) -> int:
    try:
        with open(input_path, "r", encoding="utf-8") as handle:
            document = json.load(handle)
    except (OSError, ValueError) as exc:
        print("input error: %s" % exc, file=sys.stderr)
        return 2
    if not isinstance(document, dict):
        print("input error: document must be a JSON object",
              file=sys.stderr)
        return 2
    try:
        result = build_drawing(document)
    except DrawingError as exc:
        print("input error: %s" % exc, file=sys.stderr)
        return 2
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "drawing.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    if result["status"] == "ok":
        print(
            "ok: drawing template for %s (%s, %s)"
            % (
                result["part_name"],
                result["sheet_size"],
                result["scale"],
            )
        )
        return 0
    print(
        "drawing pending: %s" % "; ".join(result["pending"]),
        file=sys.stderr,
    )
    return 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Drawing template + mock render."
    )
    parser.add_argument("input", help="drawing input JSON")
    parser.add_argument("--out-dir", required=True,
                        help="output directory")
    args = parser.parse_args(argv)
    return run(args.input, args.out_dir)


if __name__ == "__main__":
    raise SystemExit(main())
