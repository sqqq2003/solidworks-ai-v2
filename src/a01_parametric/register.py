"""Parameter register: unit, source, dependency, range, confirmation, approval."""

from __future__ import annotations

from .graph import subsystem_of


def build_register(spec: dict, values: dict, preflight_register: dict) -> dict:
    register = {}
    for name, row in preflight_register.items():
        register[name] = {
            **row,
            "subsystem": subsystem_of(name, spec),
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
            "subsystem": subsystem_of(name, spec),
            "kind": kind,
            "mapping_id": node.get("mapping_id"),
            "preserve_interface": node.get("preserve_interface"),
        }
    return register
