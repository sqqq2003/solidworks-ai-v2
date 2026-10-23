"""Machine-specific dependency evaluation; lengths are mm, never GT-ZX values."""
from math import isfinite


def numeric(value, name, minimum=0):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) or value <= minimum:
        raise ValueError(f"{name}: finite number > {minimum} required")
    return float(value)


def finite_number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
        raise ValueError(f"{name}: finite number required")
    return float(value)


MODULES = {
    "frame": ("frame_length", "frame_width", "frame_height", "sheet_thickness"),
    "conveyor": ("conveyor_length", "conveyor_width", "conveyor_height"),
    "left_drive": ("left_drive_x", "drive_belt_length", "drive_speed"),
    "right_drive": ("right_drive_x", "drive_belt_length", "drive_speed"),
    "sealing": ("sealing_height", "sealing_clearance"),
    "interfaces": ("mount_pitch", "motor_shaft_diameter"),
    "purchased": ("motor_power", "bearing_diameter"),
}


def build_plan(envelope=None, measurements=None):
    """Measurements: {name: {value, source, confirmed}}; absent OEM data stays null.

    Rules are explicit design relationships, not certified OEM dimensions.
    The target envelope alone must never enable a native write.
    """
    envelope = envelope or {"length": 1800, "width": 900, "height": 1500}
    values = {"target_" + k: numeric(envelope[k], k) for k in ("length", "width", "height")}
    register = {k: {"unit": "mm", "source": "user_target", "status": "target_only", "depends_on": []} for k in values}
    names = set(sum((list(v) for v in MODULES.values()), []))
    allowances = {"end_allowance", "side_allowance", "top_allowance", "belt_offset"}
    for name in names | allowances:
        values[name] = None
        register[name] = {"unit": {"drive_speed": "mm/s", "motor_power": "W"}.get(name, "mm"),
                          "source": None, "status": "pending_mapping", "depends_on": []}
    for name, row in (measurements or {}).items():
        if name not in names | allowances:
            raise ValueError(f"unknown QL parameter: {name}")
        if row.get("confirmed") is not True or not row.get("source"):
            continue
        # left_drive_x is a signed offset from the centre line.
        read = finite_number if name == "left_drive_x" else numeric
        values[name] = read(row["value"], name)
        register[name].update(source=row["source"], status="confirmed_input")
    rules = {
        "frame_length": (("target_length", "end_allowance"), lambda a,b: a-2*b),
        "frame_width": (("target_width", "side_allowance"), lambda a,b: a-2*b),
        "frame_height": (("target_height", "top_allowance"), lambda a,b: a-b),
        "left_drive_x": (("conveyor_width", "belt_offset"), lambda a,b: -(a/2+b)),
        "right_drive_x": (("conveyor_width", "belt_offset"), lambda a,b: a/2+b),
    }
    for name, (deps, fn) in rules.items():
        if values[name] is not None:
            continue
        register[name]["depends_on"] = list(deps)
        if all(values[d] is not None for d in deps):
            result = fn(*(values[d] for d in deps))
            if name != "left_drive_x":
                numeric(result, name)
            values[name] = result
            register[name].update(status="derived_design", source="QL design relationship; OEM validation pending")
    return {"schema_version": 1, "machine": "QL-5050PX", "units": "mm",
            "values_mm": values, "parameter_register": register, "modules": MODULES,
            "pending_mapping": sorted(k for k,v in values.items() if v is None),
            "mechanical_acceptance": "unverified"}
