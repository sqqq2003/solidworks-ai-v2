"""Load the A01 machine spec and apply an envelope override. Millimetres only."""

from __future__ import annotations

import copy
from pathlib import Path

import a01

DEFAULT_ENVELOPE_MM = {"length": 1800.0, "width": 900.0, "height": 1500.0}
SPEC_PATH = a01.ROOT / "data" / "machine_spec.json"


def load_spec(path: Path | None = None) -> dict:
    spec = a01.read_json(Path(path) if path is not None else SPEC_PATH)
    if spec.get("units") != "mm":
        raise ValueError("Input units must be mm")
    if "target_envelope_mm" not in spec or "parameter_graph" not in spec:
        raise ValueError("machine spec is missing target_envelope_mm or parameter_graph")
    return spec


def with_envelope(
    spec: dict,
    length: float = DEFAULT_ENVELOPE_MM["length"],
    width: float = DEFAULT_ENVELOPE_MM["width"],
    height: float = DEFAULT_ENVELOPE_MM["height"],
) -> dict:
    updated = copy.deepcopy(spec)
    updated["units"] = spec.get("units")
    updated["target_envelope_mm"] = {
        "length": a01.positive(length, "length"),
        "width": a01.positive(width, "width"),
        "height": a01.positive(height, "height"),
    }
    return updated


def apply_simulated_allowances(spec: dict, fixture: dict) -> dict:
    """Copy a labeled simulation fixture onto measured nodes.

    The fixture must say it is not a real A01 measurement. Ignored numbers in
    the fixture are never written into the graph.
    """

    if fixture.get("not_measured_from_real_a01") is not True:
        raise ValueError("simulated fixture must set not_measured_from_real_a01 true")
    updated = copy.deepcopy(spec)
    overrides = fixture.get("measured_overrides_mm") or {}
    graph = updated["parameter_graph"]
    for name, value in overrides.items():
        node = graph.get(name)
        if node is None or node.get("kind") != "measured":
            raise ValueError(f"{name}: simulated override is not a measured node")
        node["value_mm"] = a01.positive(value, name)
        node["confirmed"] = True
        node["source"] = "simulated fixture; not a real A01 measurement"
    return updated
