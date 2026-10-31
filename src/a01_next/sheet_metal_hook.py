"""Hook into the existing sheet-metal generator. Does not fork a second cad2sw."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable

SHEET_METAL_ENTRY = "solidworks_generator.generate_sheet_metal"


def _load_generator():
    src = Path(__file__).resolve().parents[1]
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    from solidworks_generator import generate_sheet_metal

    return generate_sheet_metal


def sheet_metal_hook(plan: dict, executor: Callable | None = None) -> dict:
    """Describe a call to the existing generator.

    The default path does not execute it. Pass ``executor`` only from a test
    or a future Windows worker. ``executor`` receives the real
    ``generate_sheet_metal`` function and this request.
    """

    request = {
        "status": "scaffold",
        "track": "next",
        "entry": SHEET_METAL_ENTRY,
        "called": False,
        "cad_executed": False,
        "sw_live": "not_applicable_on_linux",
        "thickness_mm": plan.get("values_mm", {}).get("sheet_thickness"),
        "reason": (
            "No confirmed A01 sheet profile is mapped. "
            "The hook delegates to solidworks_generator.generate_sheet_metal and does not copy it."
        ),
    }
    if executor is None:
        return request
    generate_sheet_metal = _load_generator()
    if generate_sheet_metal.__name__ != "generate_sheet_metal":
        raise RuntimeError("sheet-metal hook lost the existing generator")
    request["called"] = True
    request["status"] = "delegated_to_existing_generator"
    request["result"] = executor(generate_sheet_metal, request)
    return request
