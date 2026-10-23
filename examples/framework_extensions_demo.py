"""Offline demo for the framework extensions built after Issue #6.

Covers the machine registry, K-factor/material lookups, the estimate module,
drawing-number allocation, the mate-chain pre-check, and schema validation.
Everything is synthetic and offline: no SolidWorks, no CAD writes.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

OUT = ROOT / "runtime" / "issue6-extensions-demo"


def module_registry() -> dict:
    from src.machine_registry import list_machines

    rows = list_machines()
    return {"machines": [row["id"] for row in rows], "sw_live": "not_applicable_on_linux"}


def module_material_data() -> dict:
    from src.material_data import density_for, k_factor_for

    density = density_for("SUS304")
    k = k_factor_for("SUS304", 2.5)
    return {
        "density_status": density["status"],
        "k_factor_status": k["status"],
        "note": "K stays unresolved until a confirmed shop value exists; no default K is assumed",
    }


def module_estimate() -> dict:
    from src.sheetmetal_estimate import estimate_job
    from src.sheetmetal_unfold import unfold_chain

    chain = unfold_chain(
        thickness_mm=2.5, radius_mm=1.5, angle_degrees=90.0, k_factor=0.33, segments_mm=[300.0, 400.0, 300.0]
    )
    report = estimate_job(chain, width_mm=400.0, material="SUS304", quantity=5, thickness_mm=2.5)
    return {
        "estimate_only": report["estimate_only"],
        "mass_kg_total": report["totals"]["mass_kg_total"],
        "labor_minutes_total": report["totals"]["labor_minutes_total"],
        "assumptions_confirmed": any(a["confirmed"] for a in report["labor"]["assumptions"]),
    }


def module_drawing_numbers() -> dict:
    from src.drawing_numbers import allocate_drawing_numbers

    journal = OUT / "drawing-number-journal.json"
    first = allocate_drawing_numbers(["panel-a", "panel-b"], journal_path=journal)
    again = allocate_drawing_numbers(["panel-a"], journal_path=journal)
    return {
        "allocated": [row["drawing_number"] for row in first["allocations"]],
        "idempotent_status": again["allocations"][0]["status"],
        "max_seq": again["max_seq"],
    }


def module_mate_chain() -> dict:
    from src.a01_next.mate_chain import precheck_assembly

    report = precheck_assembly(
        [
            {
                "group_id": "roller-bed",
                "components": ["frame", "roller-1", "roller-2", "loose-bracket"],
                "grounded": "frame",
                "mates": [
                    {"type": "revolute", "between": ["frame", "roller-1"]},
                    {"type": "revolute", "between": ["frame", "roller-2"]},
                ],
                "fasteners": [{"type": "bolt", "between": ["frame", "roller-1"], "count": 4}],
                "holes": [{"component": "frame", "count": 2}],
            }
        ]
    )
    return {
        "total_issues": report["total_issues"],
        "isolated": report["groups"][0]["isolated_components"],
        "mates_solved": report["mates_solved"],
    }


def module_schema() -> dict:
    from src.schema_validate import validate_against_named_schema
    from src.sheetmetal_unfold import unfold_plan

    plan = unfold_plan(
        thickness_mm=2.5, radius_mm=1.5, angle_degrees=90.0, k_factor=0.33, legs_mm=[30.0, 40.0]
    )
    validate_against_named_schema(plan, "unfold-plan")
    return {"unfold_plan_schema": "valid"}


def main() -> int:
    shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir(parents=True, exist_ok=True)
    summary: dict[str, dict] = {}
    for name, runner in (
        ("registry", module_registry),
        ("material_data", module_material_data),
        ("estimate", module_estimate),
        ("drawing_numbers", module_drawing_numbers),
        ("mate_chain", module_mate_chain),
        ("schema", module_schema),
    ):
        payload = runner()
        summary[name] = payload
        print(f"[{name}] {json.dumps(payload, ensure_ascii=False)}")
        (OUT / f"{name}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary_doc = {
        "sample": "synthetic_only",
        "solidworks_live_verified": False,
        "sw_live": "not_applicable_on_linux",
        "cad_executed": False,
    }
    (OUT / "summary.json").write_text(json.dumps(summary_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary_doc, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
