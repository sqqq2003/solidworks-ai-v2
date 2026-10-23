"""Range, positivity, and preserved-interface checks for a solved A01 plan."""

from __future__ import annotations

import a01

ALLOWED_NODE_UNITS = {"mm", "count"}


def _range_ok(limit) -> bool:
    return (
        isinstance(limit, list)
        and len(limit) == 2
        and all(not isinstance(item, bool) and isinstance(item, (int, float)) for item in limit)
        and limit[0] <= limit[1]
    )


def enforce(spec: dict, values: dict) -> list[dict]:
    if spec.get("units") != "mm":
        raise ValueError("Input units must be mm")
    target = spec["target_envelope_mm"]
    for axis in ("length", "width", "height"):
        a01.positive(target[axis], axis)

    for name, node in spec["parameter_graph"].items():
        if node.get("kind") != "measured":
            continue
        if node.get("confirmed") is not True and values.get(name) is not None:
            raise ValueError(f"{name}: unconfirmed measured dimension must stay unresolved")

    rules = list(spec.get("preserve_interfaces") or [])
    covered: set[str] = set()
    rows: list[dict] = []
    for name, node in spec.get("parametric_graph", {}).items():
        unit = node.get("unit", "mm")
        if unit not in ALLOWED_NODE_UNITS:
            raise ValueError(f"{name}: unit must be mm or count")
        value = values.get(name)
        if node.get("kind") == "pending_mapping" and value is not None:
            raise ValueError(f"{name}: pending_mapping cannot carry a fabricated value")
        if value is not None:
            if unit == "mm":
                a01.positive(value, name)
            elif isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
                raise ValueError(f"{name}: expected a positive count")
            limit = node.get("confirmed_range_mm")
            if limit is not None:
                if not _range_ok(limit) or not limit[0] <= value <= limit[1]:
                    raise ValueError(f"{name}: outside confirmed range")
        rule = node.get("preserve_interface")
        if not rule:
            continue
        if rule not in rules:
            raise ValueError(f"{name}: preserve_interface is not listed on the machine spec")
        if value is not None and node.get("production_approved") is not True:
            raise ValueError(f"{name}: refusing to overwrite preserved interface {rule}")
        covered.add(rule)
        rows.append(
            {
                "parameter": name,
                "rule": rule,
                "overwritten": False,
                "action": "preserve_unresolved" if value is None else "preserve_confirmed",
            }
        )
    missing = [rule for rule in rules if rule not in covered]
    if missing:
        raise ValueError(
            "preserve_interfaces not covered by the parametric graph: " + "; ".join(missing)
        )
    return rows
