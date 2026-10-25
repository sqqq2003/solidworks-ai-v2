"""Command line: feature tree JSON -> geometry IR JSON.

Usage:
    python -m geometry_ir.cli tree.json --out-dir out
        [--title part.SLDPRT --part-path <staging path>
         --plan-id <id> --flip-direction true|false]

Outputs (only inside --out-dir; the input file is never modified):
    geometry_ir.json   -- the geometry-ir/1 document
    validation.json    -- the validator verdict
    build_request.json -- the CONTRACT.md section 12 request, only when
                          all four build arguments are given and the IR
                          has no errors and no pending items
    build_pending.json -- the blocking report, when build arguments are
                          given but the request is withheld

Exit codes: 0 = IR valid, no pending (and build request emitted when
requested); 1 = IR structurally valid but pending items exist, or the
build request was withheld; 2 = input error (unreadable JSON, malformed
tree, bad --flip-direction value).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .build import to_build_request
from .ir import IRError, tree_to_ir
from .validate import validate_ir


def _load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("document must be a JSON object")
    return data


def _write(out_dir: Path, name: str, document: dict) -> None:
    (out_dir / name).write_text(
        json.dumps(document, indent=2), encoding="utf-8"
    )


def run(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="geometry_ir.cli",
        description="Serialize a feature tree to a geometry IR.",
    )
    parser.add_argument("input", help="feature-tree/1 JSON document")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--title", default=None)
    parser.add_argument("--part-path", default=None)
    parser.add_argument("--plan-id", default=None)
    parser.add_argument("--flip-direction", default=None)
    args = parser.parse_args(argv)

    try:
        document = _load_json(args.input)
    except (OSError, ValueError) as exc:
        print("input error: %s" % exc, file=sys.stderr)
        return 2
    try:
        ir = tree_to_ir(document)
    except IRError as exc:
        print("input error: %s" % exc, file=sys.stderr)
        return 2
    validation = validate_ir(ir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    _write(out_dir, "geometry_ir.json", ir)
    _write(out_dir, "validation.json", validation)
    if validation["errors"]:
        print(
            "invalid IR: %s" % "; ".join(validation["errors"]),
            file=sys.stderr,
        )
        return 2
    if validation["pending"]:
        print(
            "IR pending: %s"
            % "; ".join(
                "%s:%s" % (p["node_id"], p["reason"])
                for p in validation["pending"]
            ),
            file=sys.stderr,
        )
        return 1
    build_args = (
        args.title is not None
        or args.part_path is not None
        or args.plan_id is not None
        or args.flip_direction is not None
    )
    if not build_args:
        print(
            "ok: IR valid, %d features, %d bends"
            % (validation["feature_count"], validation["bend_count"])
        )
        return 0
    if args.flip_direction is None or args.flip_direction.lower() not in (
        "true",
        "false",
    ):
        print(
            "input error: --flip-direction must be true or false "
            "(no default)",
            file=sys.stderr,
        )
        return 2
    try:
        request, report = to_build_request(
            ir,
            title=args.title,
            part_path=args.part_path,
            plan_id=args.plan_id,
            flip_direction=args.flip_direction.lower() == "true",
        )
    except ValueError as exc:
        print("input error: %s" % exc, file=sys.stderr)
        return 2
    if request is None:
        _write(out_dir, "build_pending.json", report)
        print(
            "build withheld: %s"
            % "; ".join(report["errors"] + report["pending"]),
            file=sys.stderr,
        )
        return 1
    _write(out_dir, "build_request.json", request)
    print(
        "ok: IR valid, build request for plan %s (%d bends)"
        % (args.plan_id, request["bend_count"])
    )
    return 0


def main(argv=None) -> int:
    return run(argv)


if __name__ == "__main__":
    raise SystemExit(main())
