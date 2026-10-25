"""Whole-part flat-pattern (unfold) length for a sheet-metal tree.

BA method (same formulas as csharp-bridge/SHEET_METAL_RULES.md):

    unfold_length = sum(straight_lengths_mm) + sum(BA per bend)
    BA = theta_rad * (R + K * t)

Straight lengths are measured to the bend tangent points (BA method).
They are NOT derived from the sketch outline: the outline of a formed
part does not determine its flat straight legs, and guessing them
would fabricate geometry. Straight lengths therefore come from an
explicit source, in this order:

1. the caller's ``straight_lengths_mm`` argument, or
2. the sheetmetal group node's ``straight_lengths_mm`` param.

If neither source provides them, the result is pending with a listed
reason, never a substituted number. Likewise every bend's BA is
computed from that bend node's own per-job parameters (thickness,
radius, angle, K); a bend missing or mis-ranged in any of them
contributes no BA and is listed pending, and the whole result is
pending. A pending unfold never silently skips an uncomputed bend.

Non-sheet-metal features (holes, extrudes, revolves, checks,
fillets, chamfers) are listed under ``excluded`` and contribute
nothing to the length; the outline sketch is listed as an outline
reference, not a length contributor.

Scope boundary (honest): this module computes one flat-pattern
group. A tree with more than one sheetmetal group node is reported
pending (multiple_sheetmetal_groups_unsupported) rather than summed
across groups, because group-to-group interaction is not modelled.

Usage as a library:
  from feature_tree.unfold import compute_unfold
  report = compute_unfold(tree)

Usage as a CLI (mirrors feature_tree.cli exit codes):
  python -m feature_tree.unfold <tree.json> --out-dir out
  python -m feature_tree.unfold <tree.json> --out-dir out \\
      --straight-lengths 30,40,30
Exit codes: 0 = unfold ok; 1 = unfold pending (report still written);
2 = input error (missing file, malformed JSON, tree validation error).
The input file is never modified; only --out-dir/unfold.json is written.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .tree import TreeError, bend_allowance_mm, parse_tree

UNFOLD_VERSION = "feature-tree-unfold/1"

_BEND_KEYS = ("thickness_mm", "radius_mm", "angle_degrees", "k_factor")


def _bend_allowance_or_pending(node: dict) -> tuple:
    """BA for one bend node, or the pending reasons that block it.

    Returns (ba_or_None, reasons). Missing or non-numeric parameters
    and out-of-range values are all pending reasons here: unfold is a
    report, not execution, so anything uncomputable is reported as
    pending with its cause, never defaulted and never skipped silently.
    """
    params = node.get("params", {})
    reasons = []
    for key in _BEND_KEYS:
        value = params.get(key)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
        ):
            reasons.append("missing_param:%s" % key)
    if reasons:
        return None, reasons
    thickness = float(params["thickness_mm"])
    radius = float(params["radius_mm"])
    angle = float(params["angle_degrees"])
    k_factor = float(params["k_factor"])
    problems = []
    if thickness <= 0:
        problems.append("invalid_param:thickness_mm must be > 0")
    if radius < 0:
        problems.append("invalid_param:radius_mm must be >= 0")
    if not 0 < angle < 180:
        problems.append("invalid_param:angle_degrees must be in (0, 180)")
    if not 0 <= k_factor <= 1:
        problems.append("invalid_param:k_factor must be in [0, 1]")
    if problems:
        return None, problems
    numbers = bend_allowance_mm(angle, radius, k_factor, thickness)
    return numbers["bend_allowance_mm"], []


def _straight_lengths_or_pending(tree, straight_lengths_mm) -> tuple:
    """Resolve straight lengths, or the pending reasons that block them."""
    if straight_lengths_mm is not None:
        values = straight_lengths_mm
    else:
        groups = [n for n in tree.features if n.type == "sheetmetal"]
        if len(groups) == 1:
            values = groups[0].params.get("straight_lengths_mm")
        else:
            values = None
        if len(groups) > 1:
            return None, ["multiple_sheetmetal_groups_unsupported"]
    if values is None:
        return None, ["missing_param:straight_lengths_mm"]
    if (
        not isinstance(values, list)
        or not values
        or any(
            isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0
            for v in values
        )
    ):
        return None, ["invalid_param:straight_lengths_mm"]
    return [float(v) for v in values], []


def compute_unfold(tree, straight_lengths_mm=None) -> dict:
    """Flat-pattern length report for one parsed FeatureTree.

    ``tree`` must already be validated (parse_tree). The report is a
    plain dict: status "ok" only when every bend's BA and the straight
    total are both known; otherwise status "pending", unfold_length_mm
    is None, and every blocker is listed under "pending".
    """
    nodes = {node.id: node for node in tree.features}
    groups = [n for n in tree.features if n.type == "sheetmetal"]
    bend_nodes = []
    pending = []
    if len(groups) > 1:
        pending.append("multiple_sheetmetal_groups_unsupported")
        bend_nodes = [n for n in tree.features if n.type == "bend"]
    elif len(groups) == 1:
        for ref in groups[0].params.get("bend_refs", []):
            target = nodes.get(ref)
            if target is None:
                pending.append("unresolved_bend_ref:%s" % ref)
            elif target.type != "bend":
                pending.append("bend_ref_not_a_bend:%s" % ref)
            else:
                bend_nodes.append(target)
    else:
        bend_nodes = [n for n in tree.features if n.type == "bend"]

    straight, straight_reasons = _straight_lengths_or_pending(
        tree, straight_lengths_mm
    )
    pending.extend(straight_reasons)

    bend_entries = []
    total_ba = 0.0
    all_bends_computed = True
    for node in bend_nodes:
        ba, reasons = _bend_allowance_or_pending(node.to_dict())
        bend_entries.append(
            {
                "bend_id": node.id,
                "bend_allowance_mm": ba,
                "pending_reasons": reasons,
            }
        )
        if reasons:
            all_bends_computed = False
            pending.append(
                "bend_pending:%s:%s" % (node.id, ";".join(reasons))
            )
        else:
            total_ba += ba

    excluded = []
    bend_ids = {n.id for n in bend_nodes}
    for node in tree.features:
        if node.type == "bend" and node.id in bend_ids:
            continue
        if node.type == "sheetmetal":
            continue
        note = (
            "outline_reference"
            if node.type == "sketch"
            else "non_sheetmetal_feature"
        )
        excluded.append(
            {"node_id": node.id, "type": node.type, "note": note}
        )

    # A bend-less tree is a flat blank: with known straight lengths
    # its unfold length is just the straight total (BA total 0).
    status = "pending" if pending else "ok"
    straight_total = sum(straight) if straight is not None else None
    if status == "ok":
        unfold_length = straight_total + total_ba
    else:
        unfold_length = None
    return {
        "unfold_version": UNFOLD_VERSION,
        "tree_name": tree.name,
        "status": status,
        "straight_lengths_mm": straight,
        "straight_total_mm": straight_total,
        "bends": bend_entries,
        # Full BA total only when every bend computed; otherwise None
        # (per-bend values that did compute are still in "bends").
        "total_bend_allowance_mm": (
            total_ba if all_bends_computed else None
        ),
        "unfold_length_mm": unfold_length,
        "pending": pending,
        "excluded": excluded,
    }


def _load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("document must be a JSON object")
    return data


def run(input_path: str, out_dir: str,
        straight_lengths: list | None = None) -> int:
    try:
        document = _load_json(input_path)
    except (OSError, ValueError) as exc:
        print("input error: %s" % exc, file=sys.stderr)
        return 2
    try:
        tree = parse_tree(document)
    except TreeError as exc:
        print("input error: %s" % exc, file=sys.stderr)
        return 2
    report = compute_unfold(tree, straight_lengths)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "unfold.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    if report["status"] == "ok":
        print(
            "ok: unfold length %.4f mm "
            "(straight %.4f + BA %.4f)"
            % (
                report["unfold_length_mm"],
                report["straight_total_mm"],
                report["total_bend_allowance_mm"],
            )
        )
        return 0
    print(
        "unfold pending: %s" % "; ".join(report["pending"]),
        file=sys.stderr,
    )
    return 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Whole-part unfold length for a feature tree."
    )
    parser.add_argument("input", help="tree JSON (feature-tree/1)")
    parser.add_argument("--out-dir", required=True,
                        help="output directory (only unfold.json is written)")
    parser.add_argument(
        "--straight-lengths",
        help="comma-separated straight lengths in mm, e.g. 30,40,30; "
             "overrides the sheetmetal node's straight_lengths_mm",
    )
    args = parser.parse_args(argv)
    straight = None
    if args.straight_lengths is not None:
        try:
            straight = [float(v) for v in args.straight_lengths.split(",")]
        except ValueError:
            print("input error: --straight-lengths must be numbers",
                  file=sys.stderr)
            return 2
    return run(args.input, args.out_dir, straight)


if __name__ == "__main__":
    raise SystemExit(main())
