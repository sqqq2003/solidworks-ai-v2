"""Load the independent QL-5050PX spec and apply an envelope override.

The envelope override only moves the *placeholder* target. It never turns the
target into a confirmed envelope and never copies GT-ZX / A01 values.
Millimetres only.
"""

from __future__ import annotations

import copy
from pathlib import Path

import a01

DEFAULT_ENVELOPE_MM = {"length": 1800.0, "width": 900.0, "height": 1500.0}
SPEC_PATH = a01.ROOT / "data" / "ql_5050px_spec.json"


def load_spec(path: Path | None = None) -> dict:
    spec = a01.read_json(Path(path) if path is not None else SPEC_PATH)
    if spec.get("units") != "mm":
        raise ValueError("Input units must be mm")
    if spec.get("machine_id") != "QL-5050PX":
        raise ValueError("this loader only serves the independent QL-5050PX spec")
    if "target_envelope_mm" not in spec or "parameter_graph" not in spec:
        raise ValueError("QL-5050PX spec is missing target_envelope_mm or parameter_graph")
    if spec.get("target_envelope_is_placeholder") is not True:
        raise ValueError("QL-5050PX envelope must stay a target placeholder")
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
    # An override moves the placeholder only. It must not be promoted to a
    # confirmed envelope, and no GT-ZX / A01 value may ride along.
    if updated.get("target_envelope_is_placeholder") is not True:
        raise ValueError("envelope override must keep the target placeholder flag")
    return updated
