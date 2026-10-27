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


def review_ledger(spec: dict, values: dict, preflight_register: dict, *, source_sha256: str):
    """Adapt the existing A01 register to the shared review document contract.

    The register remains authoritative for dependency/source metadata. Existing
    generic rules and legacy confirmation strings never auto-confirm a value.
    Unresolved graph values remain explicit missing dependencies.
    """
    from parameter_ledger import Parameter, ParameterLedger
    register = build_register(spec, values, preflight_register)
    ledger = ParameterLedger(source_sha256)
    units = {'mm': 'mm', 'deg': 'deg', 'count': 'count', 'ratio': 'ratio'}
    for key, row in register.items():
        if values.get(key) is None:
            continue
        unit = row.get('unit', 'mm')
        if unit not in units:
            raise ValueError('unsupported register unit: ' + str(unit))
        limits = row.get('confirmed_range_mm') if unit == 'mm' else None
        ledger.parameters[key] = Parameter(key, values[key], unit, 'derived',
            str(row.get('source') or 'A01 register proposal'),
            minimum=limits[0] if limits else None, maximum=limits[1] if limits else None,
            depends_on=tuple(row.get('depends_on') or ()))
    return ledger
