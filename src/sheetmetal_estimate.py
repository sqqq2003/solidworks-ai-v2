"""Offline material-usage and labor estimates for an unfold plan.

This module is deliberately estimate_only: it multiplies geometry by generic
material densities and by planning-assumption labor rates. It never quotes,
never touches SolidWorks, and every rate it uses is listed in the report's
assumptions with its source so a shop can replace them with real rates.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

MODULE = "issue6-sheetmetal-estimate"

_SRC = Path(__file__).resolve().parent
ROOT = _SRC.parent
LABOR_RATES_PATH = ROOT / "data" / "labor_rates.json"

MM3_PER_CM3 = 1000.0
KG_PER_G = 0.001


class EstimateError(ValueError):
    """Raised when an estimate input is invalid."""


def _positive(value: float, name: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise EstimateError(f"{name} must be finite and positive")
    return number


def load_labor_rates(path: Path | None = None) -> dict:
    path = Path(path) if path is not None else LABOR_RATES_PATH
    try:
        rates = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise EstimateError(f"labor rates table not found: {path}") from exc
    if rates.get("table_version") != 1:
        raise EstimateError("unsupported labor rates table_version")
    return rates


def _rate(rates: dict, key: str) -> dict:
    row = rates.get(key)
    if not isinstance(row, dict) or not isinstance(row.get("value"), (int, float)):
        raise EstimateError(f"labor rates table missing numeric row: {key}")
    return row


def estimate_material(flat_length_mm: float, width_mm: float, thickness_mm: float, material: str) -> dict:
    """Mass of one piece from unfolded geometry and the density table."""
    from .material_data import density_for

    length = _positive(flat_length_mm, "flat_length_mm")
    width = _positive(width_mm, "width_mm")
    thickness = _positive(thickness_mm, "thickness_mm")
    density = density_for(material)
    if density.get("status") != "resolved":
        return {
            "status": "unresolved",
            "material": material,
            "reason": density.get("reason"),
            "note": "mass is not estimated without a confirmed density row",
        }
    area_mm2 = length * width
    volume_mm3 = area_mm2 * thickness
    mass_kg = volume_mm3 / MM3_PER_CM3 * density["density_g_per_cm3"] * KG_PER_G
    return {
        "status": "resolved",
        "material": material,
        "area_mm2": area_mm2,
        "volume_mm3": volume_mm3,
        "mass_kg_per_piece": mass_kg,
        "density_g_per_cm3": density["density_g_per_cm3"],
        "density_source": density.get("source"),
    }


def estimate_labor(bends: int, quantity: int, *, rates_path: Path | None = None) -> dict:
    """Labor minutes from bend count and quantity using planning assumptions."""
    rates = load_labor_rates(rates_path)
    bend_count = int(bends)
    pieces = int(quantity)
    if bend_count < 0:
        raise EstimateError("bends must be >= 0")
    if pieces <= 0:
        raise EstimateError("quantity must be >= 1")
    per_bend = _rate(rates, "bend_minutes_per_bend")
    handling = _rate(rates, "handling_minutes_per_piece")
    minutes_per_piece = bend_count * float(per_bend["value"]) + float(handling["value"])
    return {
        "status": "estimate_only",
        "bend_minutes_per_bend": float(per_bend["value"]),
        "handling_minutes_per_piece": float(handling["value"]),
        "minutes_per_piece": minutes_per_piece,
        "total_minutes": minutes_per_piece * pieces,
        "assumptions": [
            {"key": key, "value": float(_rate(rates, key)["value"]), "source": _rate(rates, key)["source"], "confirmed": _rate(rates, key).get("confirmed") is True}
            for key in ("bend_minutes_per_bend", "handling_minutes_per_piece")
        ],
    }


def plan_geometry(unfold_plan: dict, *, thickness_mm: float | None = None) -> dict:
    """Normalize unfold_plan / unfold_chain output to flat length, thickness, bends.

    ``unfold_chain`` output does not repeat the thickness, so callers may pass
    it explicitly; a plan that carries its own thickness uses that value.
    """
    bend = unfold_plan.get("bend", {})
    flat_length_mm = unfold_plan.get("flat_length_mm", bend.get("flat_length_mm"))
    thickness = thickness_mm if thickness_mm is not None else unfold_plan.get(
        "thickness_mm", bend.get("thickness_mm")
    )
    bends = unfold_plan.get("bend_count", bend.get("bend_count"))
    if bends is None:
        bends = 1 if bend else None
    if flat_length_mm is None or thickness is None or bends is None:
        raise EstimateError(
            "unfold plan lacks flat_length_mm / thickness_mm / bend count; "
            "pass thickness_mm explicitly for chain output"
        )
    return {
        "flat_length_mm": _positive(flat_length_mm, "flat_length_mm"),
        "thickness_mm": _positive(thickness, "thickness_mm"),
        "bends": int(bends),
    }


def estimate_job(
    unfold_plan: dict,
    *,
    width_mm: float,
    material: str,
    quantity: int,
    thickness_mm: float | None = None,
    rates_path: Path | None = None,
) -> dict:
    """Combine material and labor estimates for one unfold plan."""
    geometry = plan_geometry(unfold_plan, thickness_mm=thickness_mm)
    material_row = estimate_material(
        geometry["flat_length_mm"], width_mm, geometry["thickness_mm"], material
    )
    labor = estimate_labor(geometry["bends"], quantity, rates_path=rates_path)
    rates = load_labor_rates(rates_path)
    waste = _rate(rates, "material_waste_factor")
    unresolved: list[str] = []
    if material_row.get("status") != "resolved":
        unresolved.append(f"material mass unresolved for {material}")
    report = {
        "module": MODULE,
        "estimate_only": True,
        "inputs": {
            "flat_length_mm": geometry["flat_length_mm"],
            "width_mm": float(width_mm),
            "thickness_mm": geometry["thickness_mm"],
            "bends": geometry["bends"],
            "quantity": int(quantity),
            "material": material,
        },
        "material": material_row,
        "labor": labor,
        "totals": {
            "mass_kg_per_piece": material_row.get("mass_kg_per_piece"),
            "mass_kg_total": material_row.get("mass_kg_per_piece", 0.0) * int(quantity) if material_row.get("status") == "resolved" else None,
            "mass_kg_total_with_waste": material_row.get("mass_kg_per_piece", 0.0) * int(quantity) * float(waste["value"]) if material_row.get("status") == "resolved" else None,
            "labor_minutes_total": labor["total_minutes"],
        },
        "waste_factor": {"value": float(waste["value"]), "source": waste["source"], "confirmed": waste.get("confirmed") is True},
        "unresolved": unresolved,
        "sw_live": "not_applicable_on_linux",
        "note": "Planning estimate from generic densities and assumption rates; not a quote.",
    }
    return report
