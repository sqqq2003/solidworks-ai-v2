"""Issue #6 five-module offline framework demo.

Runs all five modules end to end without SolidWorks:

1. QL-5050PX parameter preflight (module 1)
2. Controlled execution request -> mock dry-run trace (module 2)
3. Assembly mate / DOF / motion / interference pre-check (module 3)
4. Sheet-metal unfold + relief + K-factor + generation request (module 4)
5. Drawing / BOM data + mock export trace (module 5)

Every artifact is synthetic and written under runtime/issue6-demo. No CAD or
drawing product file is produced and sw_live is never claimed.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from src.a01_next.assembly_precheck import (
    dof_report,
    interference_check,
    motion_check,
)
from src.drawing_bom import (
    bom_from_parametric_plan,
    bom_from_sheet_jobs,
    bom_csv_rows,
    export_plan,
    write_bom_csv,
)
from src.ql5050px.solver import solve_spec
from src.sheetmetal_unfold import generation_request, relief_plan, unfold_plan
from src.sw_api.controlled import ExecutionRequest, run_controlled_execution

OUT = ROOT / "runtime" / "issue6-demo"


def module_1() -> dict:
    plan = solve_spec()
    (OUT / "ql5050px-plan.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        "[module1] QL-5050PX plan status=%s pending=%d sw_live=%s"
        % (plan["status"], len(plan["pending_mapping"]), plan["sw_live"])
    )
    return plan


def module_2(plan: dict) -> dict:
    destination = OUT / "controlled-dry-run.json"
    request = ExecutionRequest(
        source="simulated://QL-5050PX/unmapped-template",
        destination=destination,
        plan=plan,
        live=False,
    )
    report = run_controlled_execution(request)
    print(
        "[module2] controlled execution status=%s backend=%s refusals=%d"
        % (report["status"], report["backend"], len(report["refusals"]))
    )
    return report


def module_3() -> dict:
    mates = dof_report(
        components=3,
        mates=[
            {"type": "coincident", "between": ["frame", "panel"]},
            {"type": "revolute", "between": ["frame", "door"]},
        ],
    )
    motion = motion_check(mates, sweep_degrees=90.0)
    interference = interference_check(
        [
            {"name": "frame", "bounds": (0, 0, 0, 1800, 900, 1500)},
            {"name": "conveyor", "bounds": (100, 100, 300, 1700, 800, 500)},
            {"name": "drive-box", "bounds": (1700, 700, 400, 1900, 950, 700)},
        ]
    )
    payload = {"mates": mates, "motion": motion, "interference": interference}
    (OUT / "assembly-precheck.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        "[module3] dof=%d mates_solved=%s exact_interference=%s overlapping=%s"
        % (
            mates["dof"],
            mates["mates_solved"],
            interference["exact_interference"],
            interference["overlapping"],
        )
    )
    return payload


def module_4() -> dict:
    unfold = unfold_plan(
        thickness_mm=2.5,
        radius_mm=1.0,
        angle_degrees=90.0,
        k_factor=0.4,
        legs_mm=(220.0, 180.0),
    )
    relief = relief_plan(thickness_mm=2.5, radius_mm=1.0, relief_step=0)
    request = generation_request(
        thickness_mm=2.5,
        radius_mm=1.0,
        angle_degrees=90.0,
        k_factor=0.4,
        profile_index=0,
        bend_indices=(0,),
        output_path=str(OUT / "demo-part.SLDPRT"),
    )
    payload = {"unfold": unfold, "relief": relief, "generation_request": request}
    (OUT / "sheetmetal-unfold.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        "[module4] flat=%.2fmm BD=%.2fmm relief %.1fx%.1f called=%s"
        % (
            unfold["bend"]["flat_length_mm"],
            unfold["bend"]["bend_deduction_mm"],
            relief["width_mm"],
            relief["depth_past_centerline_mm"],
            request["called"],
        )
    )
    return payload


def module_5(plan: dict) -> dict:
    from src.batch_export import SheetPartJob

    jobs = [
        SheetPartJob(
            profile_index=209,
            bend_indices=(3,),
            area_mm2=49749.33,
            label="件01_#210",
            quantity=1,
            thickness_mm=2.5,
            thickness_source="synthetic demo annotation",
            size_hint="420x180",
        ),
        SheetPartJob(
            profile_index=190,
            bend_indices=(1,),
            area_mm2=1019.45,
            label="件02_#191",
            quantity=2,
            thickness_mm=None,
            thickness_source="",
            size_hint="120x40",
        ),
    ]
    report = bom_from_sheet_jobs(jobs, material="软钢/冷轧", drawing_ref="QL-5050PX-demo.dwg")
    mock_report = bom_from_parametric_plan(plan, drawing_ref="QL-5050PX")
    csv_path = write_bom_csv(report, OUT / "bom.csv")
    trace = export_plan(report, destination=OUT / "drawing-export-trace.json")
    (OUT / "bom-parametric-mock.json").write_text(
        json.dumps(mock_report.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        "[module5] bom rows=%d unresolved=%d csv=%s export=%s dxf_written=%s"
        % (
            len(report.items),
            len(report.unresolved),
            csv_path.name,
            trace["status"],
            trace["dxf_written"],
        )
    )
    print("[module5] bom csv header:", bom_csv_rows(report)[0])
    return {"sheet_bom": report.to_dict(), "mock_bom": mock_report.to_dict(), "trace": trace}


def main() -> int:
    # Make the demo repeatable: the mock dry-run and export refuse existing
    # destinations, so clear the previous run's synthetic outputs first.
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True, exist_ok=True)
    plan = module_1()
    module_2(plan)
    module_3()
    module_4()
    module_5(plan)
    summary = {
        "sample": "synthetic_only",
        "solidworks_live_verified": False,
        "sw_live": "not_applicable_on_linux",
        "cad_executed": False,
        "modules": [
            "ql5050px-parametric-config",
            "sw-controlled-execution",
            "assembly-precheck",
            "sheetmetal-unfold-relief-kfactor",
            "drawing-dxf-bom",
        ],
    }
    (OUT / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
