"""swctl: one offline command surface for the SolidWorks AI V2 framework.

    python swctl.py doctor
    python swctl.py machines
    python swctl.py plan --machine ql5050px
    python swctl.py precheck --groups runtime/chain.json
    python swctl.py unfold --legs 30,40 --thickness 2.5 --radius 1.5 --angle 90 --k 0.33
    python swctl.py estimate --unfold runtime/plan.json --width 400 --material SUS304 --qty 5
    python swctl.py numbers --parts 01x1,01x2 --journal runtime/numbers.json
    python swctl.py bom --parametric
    python swctl.py schema-check --name unfold-plan --file runtime/plan.json
    python swctl.py demo

Every command prints one JSON document. Nothing here starts SolidWorks;
planning outputs keep their cad_executed=False / sw_live markers.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT), str(ROOT / "src")]


def _emit(payload: dict) -> int:
    print(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


def _read_json(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def cmd_doctor(args: argparse.Namespace) -> int:
    from src.project_workbench import doctor

    return _emit(doctor())


def cmd_machines(args: argparse.Namespace) -> int:
    from src.machine_registry import list_machines

    return _emit({"machines": list_machines(), "sw_live": "not_applicable_on_linux"})


def cmd_plan(args: argparse.Namespace) -> int:
    from src.machine_registry import get_machine

    entry = get_machine(args.machine)
    module = entry["planner"]
    cmd = [sys.executable, "-X", "utf8", "-m", module]
    if entry["machine_id"] != "A01":
        cmd += ["--out", str(ROOT / "runtime" / "swctl" / f"{args.machine}-plan.json")]
    else:
        cmd += ["--dry-run"]
        if args.length is not None:
            cmd += ["--length", str(args.length)]
        if args.width is not None:
            cmd += ["--width", str(args.width)]
        if args.height is not None:
            cmd += ["--height", str(args.height)]
    completed = subprocess.run(cmd, cwd=ROOT)
    return completed.returncode


def cmd_precheck(args: argparse.Namespace) -> int:
    from src.a01_next.mate_chain import precheck_assembly

    return _emit(precheck_assembly(_read_json(args.groups)["groups"]))


def cmd_unfold(args: argparse.Namespace) -> int:
    from src.sheetmetal_unfold import unfold_chain, unfold_plan

    if args.segments:
        payload = unfold_chain(
            thickness_mm=args.thickness,
            radius_mm=args.radius,
            angle_degrees=args.angle,
            k_factor=args.k,
            segments_mm=[float(value) for value in args.segments.split(",")],
        )
    else:
        legs = [float(value) for value in args.legs.split(",")]
        payload = unfold_plan(
            thickness_mm=args.thickness,
            radius_mm=args.radius,
            angle_degrees=args.angle,
            k_factor=args.k,
            legs_mm=legs,
        )
    return _emit(payload)


def cmd_estimate(args: argparse.Namespace) -> int:
    from src.sheetmetal_estimate import estimate_job

    plan = _read_json(args.unfold)
    payload = estimate_job(
        plan,
        width_mm=args.width,
        material=args.material,
        quantity=args.qty,
        thickness_mm=args.thickness,
    )
    return _emit(payload)


def cmd_numbers(args: argparse.Namespace) -> int:
    from src.drawing_numbers import allocate_drawing_numbers

    parts = [part.strip() for part in args.parts.split(",") if part.strip()]
    payload = allocate_drawing_numbers(
        parts, scheme=args.scheme, journal_path=Path(args.journal)
    )
    return _emit(payload)


def cmd_bom(args: argparse.Namespace) -> int:
    from src.drawing_bom import bom_from_parametric_plan
    from src.a01_parametric.solver import solve_spec

    plan = solve_spec()
    payload = bom_from_parametric_plan(plan).to_dict()
    return _emit(payload)


def cmd_schema_check(args: argparse.Namespace) -> int:
    from src.schema_validate import validate_against_named_schema

    validate_against_named_schema(_read_json(args.file), args.name)
    return _emit({"schema": args.name, "file": args.file, "status": "valid"})


def cmd_demo(args: argparse.Namespace) -> int:
    completed = subprocess.run(
        [sys.executable, str(ROOT / "examples" / "issue6_framework_demo.py")], cwd=ROOT
    )
    return completed.returncode


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SolidWorks AI V2 offline control surface")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("doctor", help="environment and capability probe").set_defaults(handler=cmd_doctor)
    sub.add_parser("machines", help="list registered machines").set_defaults(handler=cmd_machines)

    plan = sub.add_parser("plan", help="parametric plan for a registered machine")
    plan.add_argument("--machine", required=True, help="machine id, e.g. ql5050px or a01-gt-zx")
    plan.add_argument("--length", type=float, default=None)
    plan.add_argument("--width", type=float, default=None)
    plan.add_argument("--height", type=float, default=None)
    plan.set_defaults(handler=cmd_plan)

    precheck = sub.add_parser("precheck", help="mate-chain structural pre-check")
    precheck.add_argument("--groups", required=True, help='JSON file with a top-level "groups" list')
    precheck.set_defaults(handler=cmd_precheck)

    unfold = sub.add_parser("unfold", help="offline sheet-metal unfold plan")
    unfold.add_argument("--legs", default=None, help="comma-separated legs for a single bend")
    unfold.add_argument("--segments", default=None, help="comma-separated segments for a bend chain")
    unfold.add_argument("--thickness", type=float, required=True)
    unfold.add_argument("--radius", type=float, required=True)
    unfold.add_argument("--angle", type=float, required=True)
    unfold.add_argument("--k", type=float, required=True)
    unfold.set_defaults(handler=cmd_unfold)

    estimate = sub.add_parser("estimate", help="offline material and labor estimate")
    estimate.add_argument("--unfold", required=True, help="unfold plan JSON file")
    estimate.add_argument("--width", type=float, required=True)
    estimate.add_argument("--material", required=True)
    estimate.add_argument("--qty", type=int, default=1)
    estimate.add_argument("--thickness", type=float, default=None)
    estimate.set_defaults(handler=cmd_estimate)

    numbers = sub.add_parser("numbers", help="allocate drawing numbers")
    numbers.add_argument("--parts", required=True, help="comma-separated part names")
    numbers.add_argument("--journal", required=True, help="journal JSON path")
    numbers.add_argument("--scheme", default="QL-5050PX-{seq:03d}")
    numbers.set_defaults(handler=cmd_numbers)

    sub.add_parser("bom", help="mock BOM for the A01 parametric plan").set_defaults(handler=cmd_bom)

    check = sub.add_parser("schema-check", help="validate a JSON file against a named schema")
    check.add_argument("--name", required=True)
    check.add_argument("--file", required=True)
    check.set_defaults(handler=cmd_schema_check)

    sub.add_parser("demo", help="run the five-module offline demo").set_defaults(handler=cmd_demo)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return args.handler(args)
    except (OSError, ValueError, KeyError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
