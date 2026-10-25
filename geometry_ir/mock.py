"""Mock round-trip: tree -> IR -> mock execution record.

The round-trip answers one question: does the IR carry the same
geometry the tree executes, or did something get lost in translation?
It runs the original tree through feature_tree's own mock backend and
compares the execution record against the IR's derived values:

* every executed node id appears in the IR, and the executed order
  respects every depends_on edge;
* each bend's IR-derived BA matches the mock readback BA (1e-9);
* each revolve's IR-derived volume matches the mock readback volume
  (relative 1e-9);
* the IR-derived unfold length matches feature_tree's own unfold
  report whenever both are available (1e-9).

feature_tree is imported lazily inside this function: the serializer,
validator and build mapping are pure standard library and must stay
usable without it. A missing feature_tree is a hard error here,
because a round-trip without the executor proves nothing.

All compared values are mock computations labelled mock_readback by
the backend. Nothing here is a SolidWorks measurement.
"""

from __future__ import annotations

import math

from .ir import tree_to_ir
from .validate import validate_ir


def _close(a, b, tol=1e-9) -> bool:
    return math.isclose(float(a), float(b), rel_tol=tol, abs_tol=tol)


def mock_roundtrip(tree: dict) -> dict:
    """Round-trip a feature tree through the IR and mock execution."""
    checks = []

    def check(name, ok, detail):
        checks.append({"name": name, "ok": bool(ok), "detail": str(detail)})

    try:
        ir = tree_to_ir(tree)
    except Exception as exc:  # serializer refuses malformed trees
        return {
            "ok": False,
            "stage": "serialize",
            "checks": [{"name": "serialize", "ok": False, "detail": str(exc)}],
            "execution_status": None,
            "executed": [],
        }
    validation = validate_ir(ir)
    if validation["errors"]:
        return {
            "ok": False,
            "stage": "validate",
            "checks": [
                {"name": "validate", "ok": False,
                 "detail": "; ".join(validation["errors"])}
            ],
            "execution_status": None,
            "executed": [],
        }
    if validation["pending"]:
        check(
            "validate_no_pending", False,
            "pending: %s"
            % "; ".join(
                "%s:%s" % (p["node_id"], p["reason"])
                for p in validation["pending"]
            ),
        )
        return {
            "ok": False,
            "stage": "validate_pending",
            "checks": checks,
            "execution_status": None,
            "executed": [],
        }

    try:
        from feature_tree.executor import Executor, build_mock_artifact
        from feature_tree.mock_backend import MockSwApp
        from feature_tree.tree import parse_tree
        from feature_tree.unfold import compute_unfold
    except ImportError as exc:
        raise ImportError(
            "mock_roundtrip needs feature_tree on sys.path: %s" % exc
        ) from exc

    parsed = parse_tree(tree)
    backend = MockSwApp()
    record = Executor(backend).run(parsed)
    artifact = build_mock_artifact(record, backend)
    if record.status != "ok":
        check(
            "execute_ok", False,
            "failed at %s (%s)"
            % (record.failed_node, record.failure_detail),
        )
        return {
            "ok": False,
            "stage": "execute",
            "checks": checks,
            "execution_status": record.status,
            "executed": list(record.executed),
        }
    check("execute_ok", True, "executed %d nodes" % len(record.executed))

    by_id = {f["id"]: f for f in ir["features"]}
    position = {node_id: i for i, node_id in enumerate(record.executed)}
    order_ok = True
    for node_id in record.executed:
        for dep in by_id[node_id]["depends_on"]:
            if position.get(dep, -1) >= position[node_id]:
                order_ok = False
    check(
        "execution_order_respects_dependencies", order_ok,
        "executed order %s" % ",".join(record.executed),
    )
    check(
        "ir_covers_executed_nodes",
        set(record.executed) == set(by_id),
        "%d executed, %d in IR" % (len(record.executed), len(by_id)),
    )

    for bend_id, numbers in ir["derived"]["bends"].items():
        mock_ba = artifact["bends"].get(bend_id, {}).get("bend_allowance_mm")
        check(
            "bend_ba_matches_mock:%s" % bend_id,
            mock_ba is not None
            and _close(numbers["bend_allowance_mm"], mock_ba),
            "ir %.9f vs mock %s" % (numbers["bend_allowance_mm"], mock_ba),
        )
    step_by_node = {}
    for step in record.steps:
        step_by_node.setdefault(step.get("node_id"), step)
    # Step dicts carry the node id under "id" in this backend; fall back
    # to matching by op order when the key differs.
    if not step_by_node or all(k is None for k in step_by_node):
        step_by_node = {}
        for step, node_id in zip(record.steps, record.executed):
            step_by_node[node_id] = step
    for revolve_id, numbers in ir["derived"]["revolves"].items():
        step = step_by_node.get(revolve_id, {})
        readback = step.get("readback", {}) if isinstance(step, dict) else {}
        mock_volume = readback.get("volume_mm3")
        check(
            "revolve_volume_matches_mock:%s" % revolve_id,
            mock_volume is not None
            and _close(numbers["volume_mm3"], mock_volume),
            "ir %.9f vs mock %s" % (numbers["volume_mm3"], mock_volume),
        )
    unfold_report = compute_unfold(parsed)
    ir_unfold = ir["derived"]["unfold"]
    if (
        isinstance(ir_unfold, dict)
        and ir_unfold.get("unfold_length_mm") is not None
        and unfold_report.get("unfold_length_mm") is not None
    ):
        check(
            "unfold_matches_feature_tree",
            _close(
                ir_unfold["unfold_length_mm"],
                unfold_report["unfold_length_mm"],
            ),
            "ir %s vs feature_tree %s"
            % (ir_unfold["unfold_length_mm"],
               unfold_report["unfold_length_mm"]),
        )
    ok = all(c["ok"] for c in checks)
    return {
        "ok": ok,
        "stage": "done",
        "checks": checks,
        "execution_status": record.status,
        "executed": list(record.executed),
    }
