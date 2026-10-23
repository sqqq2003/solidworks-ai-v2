"""Solve derived A01 dimensions without inventing unmapped OEM numbers."""

from __future__ import annotations

from pathlib import Path

import a01

from . import constraints, register
from .config import apply_simulated_allowances, load_spec, with_envelope
from .graph import assert_documented, iter_edges

PLAN_NOTE = (
    "Simulated parametric preflight only. Unmapped real-model dimensions stay null. "
    "A review_required plan is not SolidWorks live verification and does not certify mates or motion."
)


def _combined_nodes(spec: dict) -> dict:
    combined = {
        name: {"depends_on": list(node.get("depends_on", []))}
        for name, node in spec["parameter_graph"].items()
    }
    for name, node in spec.get("parametric_graph", {}).items():
        if name in combined:
            raise ValueError(f"{name}: parametric node collides with parameter_graph")
        combined[name] = {"depends_on": list(node.get("depends_on", []))}
    return combined


def dependency_order(spec: dict) -> list[str]:
    return a01.topological_order(_combined_nodes(spec))


def solve(spec: dict) -> dict:
    if spec.get("units") != "mm":
        raise ValueError("Input units must be mm")
    assert_documented(spec)
    preflight = a01.make_plan(spec)
    order = dependency_order(spec)
    values = dict(preflight["values_mm"])
    unresolved = list(preflight["unresolved"])
    pending: list[dict] = []
    extra = spec.get("parametric_graph", {})
    for name in order:
        if name not in extra:
            continue
        node = extra[name]
        kind = node.get("kind")
        deps = list(node.get("depends_on", []))
        if kind == "copy":
            if len(deps) != 1:
                raise ValueError(f"{name}: copy needs exactly one dependency")
            upstream = values.get(deps[0])
            if upstream is None:
                values[name] = None
                unresolved.append({"parameter": name, "reason": "Upstream dimensions unresolved"})
            else:
                values[name] = a01.positive(upstream, name)
        elif kind == "pending_mapping":
            values[name] = None
            item = {
                "parameter": name,
                "mapping_id": node.get("mapping_id"),
                "subsystem": node.get("subsystem"),
                "unit": node.get("unit", "mm"),
                "depends_on": deps,
                "preserve_interface": node.get("preserve_interface"),
                "reason": "Real A01 model dimension is not mapped; no OEM value invented",
            }
            pending.append(item)
            unresolved.append({"parameter": name, "reason": item["reason"]})
        else:
            raise ValueError(f"{name}: unsupported parametric rule {kind}")
    interface_checks = constraints.enforce(spec, values)
    parameter_register = register.build_register(spec, values, preflight["parameter_register"])
    return {
        "task_id": "GORK-A01-004",
        "machine_id": spec["machine_id"],
        "spec_revision": spec["revision"],
        "units": "mm",
        "status": "review_required" if unresolved else "passed",
        "scope": "parametric_redesign_simulated",
        "simulated_only": True,
        "sw_live": "not_applicable_on_linux",
        "cad_executed": False,
        "cad_release_approved": False,
        "target_envelope_mm": dict(preflight["target_envelope_mm"]),
        "parameter_order": order,
        "values_mm": {name: values.get(name) for name in order},
        "unresolved": unresolved,
        "pending_mapping": pending,
        "parameter_register": parameter_register,
        "dependency_edges": iter_edges(spec),
        "preserve_interfaces": list(spec.get("preserve_interfaces", [])),
        "interface_checks": interface_checks,
        "range_checks": preflight["range_checks"],
        "preflight_status": preflight["status"],
        "note": PLAN_NOTE,
    }


def solve_spec(
    path: Path | None = None,
    *,
    length: float = 1800,
    width: float = 900,
    height: float = 1500,
    simulated_fixture: dict | None = None,
) -> dict:
    spec = with_envelope(load_spec(path), length, width, height)
    if simulated_fixture is not None:
        spec = apply_simulated_allowances(spec, simulated_fixture)
    return solve(spec)
