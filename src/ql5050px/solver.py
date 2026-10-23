"""Solve QL-5050PX derived dimensions without inventing unmapped OEM numbers.

Frame preflight math is shared with A01 through ``a01.make_plan``; the three
machine-agnostic unresolved reasons it emits are relabeled for QL-5050PX so a
reader never mistakes this plan for an A01 result. Constraint and register
helpers follow the a01_parametric pattern with QL-5050PX subsystems.
"""

from __future__ import annotations

from pathlib import Path

import a01

from src.a01_parametric.constraints import enforce as enforce_constraints

from . import graph as ql_graph
from .config import DEFAULT_ENVELOPE_MM, load_spec, with_envelope

PLAN_NOTE = (
    "Simulated QL-5050PX parametric preflight only. The 1800x900x1500 envelope "
    "is a target placeholder, not a confirmed dimension. Unmapped real-model "
    "dimensions stay null. A review_required plan is not SolidWorks live "
    "verification and does not certify mates or motion."
)

# a01.make_plan emits machine-agnostic reasons under these parameter names.
_RELABEL = {
    "engineering_approval": "QL-5050PX template identity and operating ranges require engineering confirmation",
    "template_identity": "QL-5050PX assembly identity is not verified; DWG-only machine with no native template",
    "native_template": "No verified SolidWorks assembly template for QL-5050PX",
}


def _relabel_unresolved(rows: list[dict]) -> list[dict]:
    return [
        {**row, "reason": _RELABEL.get(row.get("parameter"), row.get("reason"))}
        for row in rows
    ]


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


def build_register(spec: dict, values: dict, preflight_register: dict) -> dict:
    register = {}
    for name, row in preflight_register.items():
        register[name] = {
            **row,
            "subsystem": ql_graph.subsystem_of(name, spec),
            "kind": spec["parameter_graph"][name].get("kind"),
            "mapping_id": None,
            "preserve_interface": None,
            "production_approved": False,
        }
    for name, node in spec.get("parametric_graph", {}).items():
        kind = node.get("kind")
        resolved = values.get(name) is not None
        if kind == "pending_mapping":
            confirmation = "pending_mapping"
            source = "unmapped_real_model"
        elif resolved:
            confirmation = "generic_rule_not_oem"
            source = "generic_rule_not_oem_measurement"
        else:
            confirmation = "unconfirmed"
            source = "upstream_unresolved"
        register[name] = {
            "unit": node.get("unit", "mm"),
            "depends_on": list(node.get("depends_on", [])),
            "source": source,
            "confirmed_range_mm": node.get("confirmed_range_mm"),
            "confirmation_status": confirmation,
            "production_approved": False,
            "subsystem": ql_graph.subsystem_of(name, spec),
            "kind": kind,
            "mapping_id": node.get("mapping_id"),
            "preserve_interface": node.get("preserve_interface"),
        }
    return register


def solve(spec: dict) -> dict:
    if spec.get("units") != "mm":
        raise ValueError("Input units must be mm")
    ql_graph.assert_documented(spec)
    preflight = a01.make_plan(spec)
    order = dependency_order(spec)
    values = dict(preflight["values_mm"])
    unresolved = _relabel_unresolved(list(preflight["unresolved"]))
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
                "reason": "Real QL-5050PX model dimension is not mapped; no OEM value invented",
            }
            pending.append(item)
            unresolved.append({"parameter": name, "reason": item["reason"]})
        else:
            raise ValueError(f"{name}: unsupported parametric rule {kind}")
    interface_checks = enforce_constraints(spec, values)
    parameter_register = build_register(spec, values, preflight["parameter_register"])
    return {
        "task_id": "GORK-QL5050PX-001",
        "machine_id": spec["machine_id"],
        "spec_revision": spec["revision"],
        "units": "mm",
        "status": "review_required" if unresolved else "passed",
        "scope": "ql5050px_parametric_preflight_simulated",
        "simulated_only": True,
        "sw_live": "not_applicable_on_linux",
        "cad_executed": False,
        "cad_release_approved": False,
        "target_envelope_mm": dict(preflight["target_envelope_mm"]),
        "target_envelope_is_placeholder": spec.get("target_envelope_is_placeholder") is True,
        "parameter_order": order,
        "values_mm": {name: values.get(name) for name in order},
        "unresolved": unresolved,
        "pending_mapping": pending,
        "parameter_register": parameter_register,
        "dependency_edges": ql_graph.iter_edges(spec),
        "preserve_interfaces": list(spec.get("preserve_interfaces", [])),
        "interface_checks": interface_checks,
        "range_checks": preflight["range_checks"],
        "preflight_status": preflight["status"],
        "note": PLAN_NOTE,
    }


def solve_spec(
    path: Path | None = None,
    *,
    length: float | None = None,
    width: float | None = None,
    height: float | None = None,
) -> dict:
    spec = load_spec(path)
    if length is None and width is None and height is None:
        return solve(spec)
    return solve(
        with_envelope(
            spec,
            DEFAULT_ENVELOPE_MM["length"] if length is None else length,
            DEFAULT_ENVELOPE_MM["width"] if width is None else width,
            DEFAULT_ENVELOPE_MM["height"] if height is None else height,
        )
    )
