"""Issue #6 module 4: offline sheet-metal unfold, relief and K-factor interface.

Pure-Python planning on top of the existing implementations:

* bend math comes from ``bend_allowance`` (BA / BD / OSSB / K-factor);
* relief craft rules come from ``solidworks_generator`` (槽宽 / 中心线深度 /
  扩槽级差), documented in ``src/BEND_RELIEF.md``;
* generation stays delegated to ``solidworks_generator.generate_sheet_metal``
  through ``a01_next.sheet_metal_hook`` — this module never forks a second
  generator and never writes a CAD file.
"""

from __future__ import annotations

import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence

MODULE = "issue6-module4-sheetmetal-unfold"

_SRC = Path(__file__).resolve().parent


def _load_bend_allowance():
    if str(_SRC) not in sys.path:
        sys.path.insert(0, str(_SRC))
    import bend_allowance

    return bend_allowance


def _load_generator_helpers():
    if str(_SRC) not in sys.path:
        sys.path.insert(0, str(_SRC))
    import solidworks_generator

    return solidworks_generator


def k_factor_options() -> dict[str, float]:
    """Material K-factor defaults, straight from ``bend_allowance``."""

    return dict(_load_bend_allowance().MATERIAL_K_FACTORS)


@dataclass(frozen=True)
class BendPlan:
    thickness_mm: float
    radius_mm: float
    angle_degrees: float
    k_factor: float
    bend_allowance_mm: float
    bend_deduction_mm: float
    outside_setback_mm: float
    deduction_factor: float
    flat_length_mm: float
    legs_mm: tuple[float, ...]

    def to_dict(self) -> dict:
        return asdict(self)


def _positive(value, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric")
    value = float(value)
    if value != value or value in (float("inf"), float("-inf")) or value < 0:
        raise ValueError(f"{name} must be a finite non-negative number")
    return value


def unfold_plan(
    *,
    thickness_mm: float,
    radius_mm: float,
    angle_degrees: float,
    k_factor: float,
    legs_mm: Sequence[float],
    mode: str = "k_factor",
    bend_deduction_mm: float | None = None,
    bend_allowance_mm: float | None = None,
    material_name: str = "软钢/冷轧",
) -> dict:
    """One bend: BA / BD / OSSB plus the flat length for the given legs.

    ``legs_mm`` are measured to the virtual sharp (outside tangent intersection);
    the flat length is ``sum(legs) - BD``. The returned plan carries the
    ``BendAllowanceSpec`` that would be written into SolidWorks, as data.
    """

    bend_allowance = _load_bend_allowance()
    legs = tuple(_positive(leg, f"legs_mm[{index}]") for index, leg in enumerate(legs_mm))
    if len(legs) < 2:
        raise ValueError("a single bend needs at least two legs")
    spec, computed = bend_allowance.resolve_bend_allowance_spec(
        thickness_mm=thickness_mm,
        radius_mm=radius_mm,
        angle_degrees=angle_degrees,
        mode=mode,
        k_factor=k_factor,
        bend_deduction_mm=bend_deduction_mm,
        bend_allowance_mm_value=bend_allowance_mm,
        material_name=material_name,
    )
    flat = sum(legs) - computed.bend_deduction_mm
    plan = BendPlan(
        thickness_mm=computed.thickness_mm,
        radius_mm=computed.radius_mm,
        angle_degrees=computed.angle_degrees,
        k_factor=computed.k_factor,
        bend_allowance_mm=computed.bend_allowance_mm,
        bend_deduction_mm=computed.bend_deduction_mm,
        outside_setback_mm=computed.outside_setback_mm,
        deduction_factor=computed.deduction_factor,
        flat_length_mm=flat,
        legs_mm=legs,
    )
    return {
        "module": MODULE,
        "backend": "offline_python",
        "status": "planned",
        "cad_executed": False,
        "sw_live": "not_applicable_on_linux",
        "bend": plan.to_dict(),
        "bend_allowance_spec": {
            "mode": spec.mode,
            "k_factor": spec.k_factor,
            "bend_deduction_mm": spec.bend_deduction_mm,
            "bend_allowance_mm": spec.bend_allowance_mm,
            "material_name": spec.material_name,
            "sw_type": spec.sw_type,
        },
        "summary": bend_allowance.format_bend_summary(computed),
        "note": (
            "Flat length uses legs measured to the virtual sharp and the "
            "resolved bend deduction. No CAD file is produced."
        ),
    }


def unfold_chain(
    *,
    thickness_mm: float,
    radius_mm: float,
    angle_degrees: float,
    k_factor: float,
    segments_mm: Sequence[float],
) -> dict:
    """N collinear bends with identical T / R / angle / K: sum(segments) - sum(BD)."""

    bend_allowance = _load_bend_allowance()
    segments = tuple(
        _positive(segment, f"segments_mm[{index}]") for index, segment in enumerate(segments_mm)
    )
    if len(segments) < 2:
        raise ValueError("an unfold chain needs at least two segments")
    rows = []
    for index in range(len(segments) - 1):
        computed = bend_allowance.compute_bend_allowance(
            thickness_mm, radius_mm, angle_degrees, k_factor
        )
        rows.append(
            {
                "bend_index": index,
                "between_segments": [index, index + 1],
                "bend_allowance_mm": computed.bend_allowance_mm,
                "bend_deduction_mm": computed.bend_deduction_mm,
                "outside_setback_mm": computed.outside_setback_mm,
            }
        )
    total_deduction = sum(row["bend_deduction_mm"] for row in rows)
    return {
        "module": MODULE,
        "backend": "offline_python",
        "status": "planned",
        "cad_executed": False,
        "sw_live": "not_applicable_on_linux",
        "bend_count": len(rows),
        "segments_mm": list(segments),
        "bends": rows,
        "total_bend_deduction_mm": total_deduction,
        "flat_length_mm": sum(segments) - total_deduction,
        "note": "Identical T / R / angle / K for every bend in the chain.",
    }


def relief_plan(
    *,
    thickness_mm: float,
    radius_mm: float,
    relief_step: int = 0,
    has_drawn_relief: bool = True,
) -> dict:
    """Relief craft sizes from the existing generator helpers.

    Rules (see ``src/BEND_RELIEF.md``): slot width ``k >= t`` and at least
    ``0.5t``; depth past the bend centerline ``t + R + 0.5mm``; drawn reliefs
    are kept as-is at step 0 and expand only toward the panel side.
    """

    generator = _load_generator_helpers()
    if isinstance(relief_step, bool) or not isinstance(relief_step, int) or relief_step < 0:
        raise ValueError("relief_step must be a non-negative integer")
    if relief_step > generator.MAX_RELIEF_STEPS:
        raise ValueError(f"relief_step must not exceed MAX_RELIEF_STEPS={generator.MAX_RELIEF_STEPS}")
    _positive(thickness_mm, "thickness_mm")
    _positive(radius_mm, "radius_mm")
    expand_up, expand_inward = generator.relief_cut_extents_mm(relief_step)
    return {
        "module": MODULE,
        "backend": "offline_python",
        "status": "planned",
        "cad_executed": False,
        "sw_live": "not_applicable_on_linux",
        "relief_step": relief_step,
        "max_relief_steps": generator.MAX_RELIEF_STEPS,
        "has_drawn_relief": bool(has_drawn_relief),
        "width_mm": generator.minimal_relief_width_mm(thickness_mm),
        "depth_past_centerline_mm": generator.minimal_relief_depth_past_centerline_mm(
            thickness_mm, radius_mm
        ),
        "expand_up_mm": expand_up,
        "expand_inward_mm": expand_inward,
        "source": "solidworks_generator relief helpers + src/BEND_RELIEF.md",
        "note": (
            "Craft sizes only. Whether a real bend passes still needs the "
            "Windows generator and operator evidence."
        ),
    }


def generation_request(
    *,
    thickness_mm: float,
    radius_mm: float,
    angle_degrees: float,
    k_factor: float,
    profile_index: int,
    bend_indices: Sequence[int],
    output_path: str | Path,
    flip_direction: bool = False,
    relief_step: int = 0,
    auto_bend: bool = False,
    analysis: object | None = None,
) -> dict:
    """Describe a call to the existing generator. Does not execute anything."""

    bend_allowance = _load_bend_allowance()
    spec, _ = bend_allowance.resolve_bend_allowance_spec(
        thickness_mm=thickness_mm,
        radius_mm=radius_mm,
        angle_degrees=angle_degrees,
        mode="k_factor",
        k_factor=k_factor,
    )
    return {
        "module": MODULE,
        "backend": "request_only",
        "status": "request_only",
        "called": False,
        "cad_executed": False,
        "sw_live": "not_applicable_on_linux",
        "entry": "solidworks_generator.generate_sheet_metal",
        "hook": "a01_next.sheet_metal_hook.sheet_metal_hook",
        "kwargs": {
            "analysis": None if analysis is None else "<DrawingAnalysis supplied by caller>",
            "profile_index": int(profile_index),
            "bend_indices": [int(index) for index in bend_indices],
            "thickness_mm": float(thickness_mm),
            "radius_mm": float(radius_mm),
            "angle_degrees": float(angle_degrees),
            "output_path": str(output_path),
            "flip_direction": bool(flip_direction),
            "relief_bend_indices": [int(index) for index in bend_indices],
            "relief_step": int(relief_step),
            "bend_allowance": {
                "mode": spec.mode,
                "k_factor": spec.k_factor,
                "bend_deduction_mm": spec.bend_deduction_mm,
                "bend_allowance_mm": spec.bend_allowance_mm,
                "material_name": spec.material_name,
                "sw_type": spec.sw_type,
            },
            "auto_bend": bool(auto_bend),
        },
        "note": (
            "Request description only. Execute it on Windows through the "
            "sheet_metal_hook executor; this framework dispatch never runs it."
        ),
    }
