"""Whole-project capability, environment and serial job-manifest entrypoint."""
import argparse
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT),str(ROOT/'src')]
from project_workbench import capabilities, doctor, run_batch, write_report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    commands = p.add_subparsers(dest='command',required=True)
    commands.add_parser('status')
    commands.add_parser('doctor')
    native_doctor=commands.add_parser('native-doctor',help='Read-only active COM environment; no writes or spawn')
    native_doctor.add_argument('--sw-exe',type=Path)
    acceptance=commands.add_parser('export-acceptance',help='Redacted evidence export without CAD binaries')
    acceptance.add_argument('batch_root',type=Path)
    acceptance.add_argument('--out',type=Path,required=True)
    ql = commands.add_parser('ql',help='QL-5050PX offline workflow; no native writes')
    from ql5050px.workflow import ACTIONS
    ql.add_argument('--action',choices=sorted(ACTIONS),default='plan')
    ql.add_argument('--config',type=Path,required=True)
    ql.add_argument('--output-dir',type=Path)
    ql.add_argument('--resume',action='store_true')
    native = commands.add_parser('native-parts',help='Explicit Windows native batch; requires reviewed templates and plans')
    native.add_argument('manifest',type=Path)
    native.add_argument('--output',type=Path,required=True)
    native.add_argument('--resume',action='store_true')
    golden=commands.add_parser('golden-check',help='Assess reported p248 evidence without rewriting it')
    golden.add_argument('accept',type=Path)
    golden.add_argument('--verification',type=Path)
    recovery=commands.add_parser('recover-parts',help='Record operator recovery only after worker exit')
    recovery.add_argument('attempt',type=Path)
    recovery.add_argument('--reviewer',required=True)
    recovery.add_argument('--evidence',required=True)
    cad=commands.add_parser('plan-cad',help='Analyze CAD and attach reviewed feature IR without guessing depth')
    cad.add_argument('input',type=Path)
    cad.add_argument('--features',type=Path,required=True)
    cad.add_argument('--out',type=Path,required=True)
    review=commands.add_parser('review-parts',help='Bind explicit recipe review to local SW/template configuration')
    review.add_argument('manifest',type=Path)
    review.add_argument('--sw-exe',type=Path,required=True)
    review.add_argument('--template',type=Path,required=True)
    review.add_argument('--sketch-plane',required=True)
    review.add_argument('--out',type=Path,required=True)
    batch = commands.add_parser('batch')
    batch.add_argument('manifest',type=Path)
    batch.add_argument('--reports',type=Path,default=ROOT/'runtime/project-reports')
    args = p.parse_args()
    try:
        if args.command == 'status':
            report = capabilities()
        elif args.command == 'native-doctor':
            from ql5050px.native_environment import inspect_environment
            report=inspect_environment(args.sw_exe)
        elif args.command == 'export-acceptance':
            from ql5050px.acceptance_report import export_acceptance
            report=export_acceptance(args.batch_root,args.out)
        elif args.command == 'doctor':
            report = doctor()
        elif args.command == 'golden-check':
            from ql5050px.golden_gate import evaluate_p248
            evidence=json.loads(args.accept.read_text(encoding='utf-8-sig'))
            verification=json.loads(args.verification.read_text(encoding='utf-8-sig')) if args.verification else None
            report={'status':'review_required','evidence':evaluate_p248(evidence,verification)}
        elif args.command == 'recover-parts':
            from ql5050px.modeling_recovery import recover_attempt
            report={'status':'review_required','recovery':recover_attempt(args.attempt,reviewer=args.reviewer,evidence=args.evidence)}
        elif args.command == 'plan-cad':
            import hashlib
            from ql5050px.cad_features import geometry,feature_plan
            request=json.loads(args.features.read_text(encoding='utf-8-sig'));request['cad_path']=str(args.input.resolve())
            plan=feature_plan(request);plan['cad_source']={'path':str(args.input.resolve()),'sha256':hashlib.sha256(args.input.read_bytes()).hexdigest()}
            report={'status':'review_required','geometry':geometry(request),'plan':plan}
            with args.out.open('x',encoding='utf-8') as stream:json.dump(report,stream,ensure_ascii=False,indent=2)
        elif args.command == 'review-parts':
            from ql5050px.modeling_delivery import prepare_jobs
            data=json.loads(args.manifest.read_text(encoding='utf-8-sig'))
            jobs=prepare_jobs(data,sw_exe=args.sw_exe,template=args.template,sketch_plane=args.sketch_plane,review=True)
            with args.out.open('x',encoding='utf-8') as stream:json.dump({'jobs':jobs},stream,ensure_ascii=False,indent=2)
            report={'status':'review_required','reviewed_manifest':str(args.out),'job_count':len(jobs)}
        elif args.command == 'native-parts':
            if sys.platform!='win32':raise ValueError('native batch requires Windows')
            from ql5050px.modeling_supervisor import supervise
            data=json.loads(args.manifest.read_text(encoding='utf-8-sig'))
            report=supervise(data['jobs'],args.output,resume=args.resume)
        elif args.command == 'ql':
            from ql5050px.workflow import run_workflow
            config = json.loads(args.config.read_text(encoding='utf-8-sig'))
            report = run_workflow(args.action,config,output_dir=args.output_dir,resume=args.resume)
        else:
            data = json.loads(args.manifest.read_text(encoding='utf-8-sig'))
            if data.get('schema_version') != 1:
                raise ValueError('unsupported job manifest schema')
            jobs = data['jobs']
            for job in jobs:
                for key in ('source','output','sw_exe','config','output_dir'):
                    if key in job and not Path(job[key]).is_absolute():
                        job[key] = str((args.manifest.resolve().parent/job[key]).resolve())
            report = run_batch(jobs)
            report['report_file'] = str(write_report(report,args.reports))
        print(json.dumps(report,ensure_ascii=False,indent=2))
        return 1 if report.get('status') in {'failed','conflict'} else (3 if report.get('status') in {'review_required','pending_mapping','ready_for_native'} else 0)
    except (OSError,ValueError,KeyError,TypeError) as exc:
        print(json.dumps({'status':'failed','error':str(exc)},ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())


