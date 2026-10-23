"""Issue #6 module 3 extension: mate-chain pre-check data model.

Additive to ``assembly_precheck`` (which stays untouched). Where
``dof_report`` answers "how many degrees of freedom does this mate list
remove", this module answers the structural questions a shop actually asks
before an assembly is exported:

* does every mate reference components that exist in its group?
* is any component left isolated (no mate, not grounded)?
* are any mates redundant within a group?
* do fastener counts match the hole counts they pass through?

This is a data-model pre-check, not the SolidWorks mate solver: no native
mate is solved and every report carries ``mates_solved=False``.
"""
from __future__ import annotations

from typing import Iterable, Sequence

MODULE = "issue6-module3-mate-chain"

try:  # normal package import
    from .assembly_precheck import SIMPLIFIED_MATE_DOF, UNMODELED_MATE_TYPES, dof_report
except ImportError:  # direct script import from src/a01_next
    from assembly_precheck import SIMPLIFIED_MATE_DOF, UNMODELED_MATE_TYPES, dof_report  # type: ignore

KNOWN_MATE_TYPES = set(SIMPLIFIED_MATE_DOF) | set(UNMODELED_MATE_TYPES)


class MateChainError(ValueError):
    """Raised when a mate-chain group is structurally invalid."""


def _group_components(group: dict) -> set[str]:
    components = group.get("components")
    if not isinstance(components, list) or not components:
        raise MateChainError(f"group {group.get('group_id')!r} needs a non-empty components list")
    for component in components:
        if not isinstance(component, str) or not component:
            raise MateChainError(f"group {group.get('group_id')!r} has an empty component name")
    return set(components)


def _group_mates(group: dict, components: set[str]) -> list[dict]:
    mates = group.get("mates", [])
    if not isinstance(mates, list):
        raise MateChainError(f"group {group.get('group_id')!r} mates must be a list")
    normalized: list[dict] = []
    for mate in mates:
        if not isinstance(mate, dict):
            raise MateChainError(f"group {group.get('group_id')!r} has a non-dict mate")
        mate_type = str(mate.get("type", "")).strip().lower()
        between = mate.get("between")
        if not mate_type:
            raise MateChainError(f"group {group.get('group_id')!r} has a mate without a type")
        if mate_type not in KNOWN_MATE_TYPES:
            raise MateChainError(
                f"group {group.get('group_id')!r} mate type {mate_type!r} is unknown; "
                f"known types: {sorted(KNOWN_MATE_TYPES)}"
            )
        if not isinstance(between, list) or len(between) != 2:
            raise MateChainError(
                f"group {group.get('group_id')!r} mate {mate_type!r} needs exactly two endpoints"
            )
        unknown = [name for name in between if name not in components]
        if unknown:
            raise MateChainError(
                f"group {group.get('group_id')!r} mate {mate_type!r} references unknown components: {unknown}"
            )
        normalized.append({"type": mate_type, "between": list(between), "label": mate.get("label")})
    return normalized


def build_chain(groups: Sequence[dict]) -> list[dict]:
    """Normalize and structurally validate a list of mate groups."""
    if not isinstance(groups, Iterable):
        raise MateChainError("groups must be a sequence of group dicts")
    chain: list[dict] = []
    seen_ids: set[str] = set()
    for group in groups:
        if not isinstance(group, dict):
            raise MateChainError("each group must be a dict")
        group_id = str(group.get("group_id", "")).strip()
        if not group_id:
            raise MateChainError("each group needs a non-empty group_id")
        if group_id in seen_ids:
            raise MateChainError(f"duplicate group_id: {group_id}")
        seen_ids.add(group_id)
        components = _group_components(group)
        mates = _group_mates(group, components)
        grounded = group.get("grounded")
        if grounded is not None and grounded not in components:
            raise MateChainError(
                f"group {group_id!r} grounded component {grounded!r} is not in its components"
            )
        chain.append(
            {
                "group_id": group_id,
                "components": sorted(components),
                "grounded": grounded,
                "mates": mates,
                "fasteners": list(group.get("fasteners", [])),
                "holes": list(group.get("holes", [])),
            }
        )
    if not chain:
        raise MateChainError("an assembly needs at least one mate group")
    return chain


def _isolated_components(group: dict) -> list[str]:
    grounded = group.get("grounded")
    connected = {grounded} if grounded else set()
    for mate in group["mates"]:
        connected.update(mate["between"])
    return sorted(set(group["components"]) - connected)


def _redundant_mates(group: dict) -> list[dict]:
    report = dof_report(
        components=len(group["components"]),
        mates=group["mates"],
        grounded_component=group.get("grounded"),
    )
    return [row for row in report["rows"] if row["status"] == "redundant"]


def _fastener_hole_check(group: dict) -> list[dict]:
    """Compare fastener counts against the hole counts of the parts they join."""
    holes_by_component = {
        row.get("component"): int(row.get("count", 0)) for row in group.get("holes", []) if isinstance(row, dict)
    }
    findings: list[dict] = []
    for row in group.get("fasteners", []):
        if not isinstance(row, dict):
            continue
        between = row.get("between", [])
        count = int(row.get("count", 0))
        for component in between:
            holes = holes_by_component.get(component)
            if holes is None:
                findings.append(
                    {
                        "kind": "holes_unknown",
                        "component": component,
                        "fastener": row.get("type"),
                        "detail": "no hole row for this component; cannot verify count",
                    }
                )
            elif holes < count:
                findings.append(
                    {
                        "kind": "holes_insufficient",
                        "component": component,
                        "fastener": row.get("type"),
                        "holes": holes,
                        "fastener_count": count,
                        "detail": "fewer holes than fasteners passing through",
                    }
                )
    return findings


def precheck_assembly(groups: Sequence[dict]) -> dict:
    """Structural pre-check report for a mate-chain description."""
    chain = build_chain(groups)
    rows: list[dict] = []
    for group in chain:
        isolated = _isolated_components(group)
        redundant = _redundant_mates(group)
        unmodeled = [mate["type"] for mate in group["mates"] if mate["type"] in UNMODELED_MATE_TYPES]
        fastener_findings = _fastener_hole_check(group)
        rows.append(
            {
                "group_id": group["group_id"],
                "components": len(group["components"]),
                "mates": len(group["mates"]),
                "isolated_components": isolated,
                "redundant_mates": redundant,
                "unmodeled_mate_types": unmodeled,
                "fastener_findings": fastener_findings,
                "issues": len(isolated) + len(redundant) + len(unmodeled) + len(fastener_findings),
            }
        )
    return {
        "module": MODULE,
        "backend": "offline_python",
        "status": "checked",
        "cad_executed": False,
        "mates_solved": False,
        "sw_live": "not_applicable_on_linux",
        "groups": rows,
        "total_issues": sum(row["issues"] for row in rows),
        "note": (
            "Structural data-model pre-check only. No native mate is solved, "
            "no motion is simulated, no exact interference is computed."
        ),
    }


if __name__ == "__main__":
    import json

    demo = [
        {
            "group_id": "roller-bed",
            "components": ["frame", "roller-1", "roller-2", "loose-bracket"],
            "grounded": "frame",
            "mates": [
                {"type": "revolute", "between": ["frame", "roller-1"]},
                {"type": "revolute", "between": ["frame", "roller-2"]},
                {"type": "revolute", "between": ["frame", "roller-1"], "label": "duplicate axle"},
            ],
            "fasteners": [{"type": "bolt", "between": ["frame", "roller-1"], "count": 4}],
            "holes": [{"component": "frame", "count": 2}],
        }
    ]
    print(json.dumps(precheck_assembly(demo), ensure_ascii=False, indent=2))
