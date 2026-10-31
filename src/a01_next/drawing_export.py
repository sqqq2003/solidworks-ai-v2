"""Drawing/export skeleton aligned with the existing roller drawing modules."""

from __future__ import annotations

import sys
from pathlib import Path

ALIGNED_MODULES = ("roller_drawing", "drawing_notes", "roller_spec")


def drawing_export_skeleton(plan: dict) -> dict:
    src = Path(__file__).resolve().parents[1]
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    imported = []
    for name in ALIGNED_MODULES:
        module = __import__(name)
        imported.append(module.__name__)
    return {
        "status": "scaffold",
        "track": "next",
        "aligned_modules": imported,
        "outputs": [],
        "dxf_written": False,
        "dwg_written": False,
        "slddrw_written": False,
        "cad_executed": False,
        "sw_live": "not_applicable_on_linux",
        "envelope_mm": dict(plan["target_envelope_mm"]),
        "note": "No drawing file is written. Roller drawing code stays in src/roller_drawing.py.",
    }
