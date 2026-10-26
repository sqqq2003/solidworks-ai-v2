"""Command line entry: DXF file -> geometry.json + plan.json.

Usage:

    python -m dxf_extract.cli input.dxf --out-dir out
    python -m dxf_extract.cli input.dxf --out-dir out --job-params job.json
    python -m dxf_extract.cli input.dxf --out-dir out --assume-units mm

Exit codes: 0 = parsed (even with flagged entities or pending
features — both are reported, not hidden); 2 = input error
(missing file, binary or malformed DXF, bad job-params file,
unknown --assume-units value). Outputs are built fully in memory
and only then written, so a failure never leaves a half-written pair.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dxf_extract.dxf_parser import DxfError, extract_dxf
from dxf_extract.planner import plan_features
from dxf_extract.relations import infer_relations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dxf_extract",
        description="Extract DXF geometry, dimension relations and a feature plan.",
    )
    parser.add_argument("dxf_file", help="Input ASCII DXF file (never modified).")
    parser.add_argument("--out-dir", required=True, help="Directory for geometry.json and plan.json.")
    parser.add_argument(
        "--job-params",
        default=None,
        help="Optional JSON file with per-job parameters: thickness_mm, "
        "radius_mm, angle_degrees, k_factor. All four are required for "
        "bend numbers; missing keys mean pending_confirmation, never a default.",
    )
    parser.add_argument(
        "--assume-units",
        default=None,
        choices=["mm", "inch", "cm", "m"],
        help="Explicit caller override for files with unknown $INSUNITS. "
        "Recorded as assumed, never as measured.",
    )
    args = parser.parse_args(argv)

    job_params = None
    if args.job_params:
        try:
            job_params = json.loads(Path(args.job_params).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            print(f"error: cannot read job-params file: {error}", file=sys.stderr)
            return 2
        if not isinstance(job_params, dict):
            print("error: job-params file must contain a JSON object.", file=sys.stderr)
            return 2

    try:
        doc = extract_dxf(args.dxf_file, assume_units=args.assume_units)
    except DxfError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    relations = infer_relations(doc)
    plan = plan_features(doc, relations=relations, job_params=job_params)

    geometry_text = json.dumps(doc.to_json(), indent=2, ensure_ascii=False)
    plan_text = json.dumps(plan, indent=2, ensure_ascii=False)
    out_dir = Path(args.out_dir)
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "geometry.json").write_text(geometry_text, encoding="utf-8")
        (out_dir / "plan.json").write_text(plan_text, encoding="utf-8")
    except OSError as error:
        print(f"error: cannot write outputs: {error}", file=sys.stderr)
        return 2

    print(f"entities: {len(doc.entities)} (flagged: {plan['stats']['flagged_entity_count']})")
    print(f"relations: {len(relations)}")
    print(f"features: {len(plan['features'])}")
    print(f"pending: {len(plan['pending'])}")
    for item in plan["pending"]:
        print(f"  pending: {item}")
    print(f"wrote: {out_dir / 'geometry.json'}")
    print(f"wrote: {out_dir / 'plan.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
