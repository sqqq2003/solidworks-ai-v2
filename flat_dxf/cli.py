"""CLI for flat-pattern DXF (mirrors feature_tree.cli exit codes).

  python -m flat_dxf.cli unfold.json job.json --out-dir out

Writes out/flat.dxf + out/bend_card.json. Exit codes: 0 = DXF ok;
1 = job pending (bend_card.json still written as the pending report);
2 = input error (missing file, malformed JSON, malformed shape).
Input files are never modified.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .dxf import FlatDxfError, build_flat_dxf


def _load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("document must be a JSON object")
    return data


def run(unfold_path: str, job_path: str, out_dir: str) -> int:
    try:
        unfold = _load_json(unfold_path)
        job = _load_json(job_path)
    except (OSError, ValueError) as exc:
        print("input error: %s" % exc, file=sys.stderr)
        return 2
    try:
        result = build_flat_dxf(
            unfold, job.get("bends"), job.get("blank_width_mm")
        )
    except FlatDxfError as exc:
        print("input error: %s" % exc, file=sys.stderr)
        return 2
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "bend_card.json").write_text(
        json.dumps(result, indent=2),
        encoding="utf-8",
    )
    if result["status"] == "ok":
        (out / "flat.dxf").write_text(
            result["dxf_text"], encoding="utf-8"
        )
        print(
            "ok: flat DXF %.4f mm, %d bend line(s)"
            % (
                result["flat_length_mm"],
                len(result["bend_card"]["bends"]),
            )
        )
        return 0
    print(
        "flat DXF pending: %s" % "; ".join(result["pending"]),
        file=sys.stderr,
    )
    return 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Flat-pattern DXF for laser cutting."
    )
    parser.add_argument("unfold", help="unfold report JSON")
    parser.add_argument("job", help="per-job bend records JSON")
    parser.add_argument("--out-dir", required=True,
                        help="output directory")
    args = parser.parse_args(argv)
    return run(args.unfold, args.job, args.out_dir)


if __name__ == "__main__":
    raise SystemExit(main())
