"""P0 CAD feature planning, trace simulation, or guarded Windows native execution."""
import argparse
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'src')]
from cad_analyzer import analyze_cad_file
from sheet_metal_pipeline import build_plan, run_plan, MockSheetMetalPort


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('source', type=Path)
    p.add_argument('--sw-exe', type=Path, help='installed SLDWORKS.exe; spawn and verify a dedicated process')
    p.add_argument('--profile', type=int, default=0, help='zero-based contour index')
    for key in ('thickness','radius','angle','k-factor'):
        p.add_argument('--'+key, type=float)
    p.add_argument('--direction', choices=('normal','reverse'))
    p.add_argument('--confirm-bends', action='store_true', help='operator confirmed analyzer bend candidates')
    p.add_argument('--confirm-unitless-mm', action='store_true')
    p.add_argument('--relief-bends', type=int, nargs='*', default=[])
    p.add_argument('--out', type=Path, default=ROOT/'runtime/sheet-metal')
    group = p.add_mutually_exclusive_group()
    group.add_argument('--dry-run', action='store_true')
    group.add_argument('--live', action='store_true')
    args = p.parse_args()
    try:
        analysis = analyze_cad_file(args.source)
        plan = build_plan(analysis, profile_index=args.profile, thickness_mm=args.thickness,
            radius_mm=args.radius, angle_degrees=args.angle, k_factor=args.k_factor,
            flip_direction=None if args.direction is None else args.direction == 'reverse',
            units_confirmed=args.confirm_unitless_mm, relief_bend_indices=args.relief_bends,
            bends_confirmed=args.confirm_bends)
        report = {'plan': plan}
        if args.dry_run:
            report['execution'] = run_plan(analysis, plan, args.out, MockSheetMetalPort())
        elif args.live:
            from sheet_metal_windows import WindowsSheetMetalPort
            from sw_session import run_on_task_sta
            def live_job():
                if args.sw_exe is None:
                    return run_plan(analysis, plan, args.out, WindowsSheetMetalPort())
                from sw_owned_launch import owned_solidworks
                with owned_solidworks(args.sw_exe) as binding:
                    report['session'] = binding.evidence()
                    result = run_plan(analysis, plan, args.out, WindowsSheetMetalPort())
                report['session'] = binding.evidence()
                return result
            report['execution'] = run_on_task_sta(live_job,
                timeout=300, task_name='p0-sheet-metal')
        print(json.dumps(report, indent=2, ensure_ascii=False, default=str, allow_nan=False))
        status = report.get('execution', plan)['status']
        return 1 if status == 'failed' else (3 if status == 'pending' else 0)
    except (OSError, ValueError, RuntimeError, IndexError) as exc:
        print(json.dumps({'status':'failed', 'error':str(exc), 'sw_live_verified':False}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
