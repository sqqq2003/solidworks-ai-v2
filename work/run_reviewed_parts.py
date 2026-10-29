"""Unified patched native-part entry on the current dev source; no old ZIP overlay."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))

def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='action',required=True)
    offline=sub.add_parser('package');offline.add_argument('request',type=Path);offline.add_argument('--out',type=Path,required=True)
    review=sub.add_parser('review');review.add_argument('request',type=Path);review.add_argument('--sw-exe',type=Path,required=True);review.add_argument('--template',type=Path,required=True);review.add_argument('--sketch-plane',required=True);review.add_argument('--out',type=Path,required=True)
    run=sub.add_parser('run');run.add_argument('manifest',type=Path);run.add_argument('--out',type=Path,required=True);run.add_argument('--resume',action='store_true')
    audit=sub.add_parser('evidence');audit.add_argument('batch',type=Path);audit.add_argument('--out',type=Path,required=True)
    doctor=sub.add_parser('doctor');doctor.add_argument('--sw-exe',type=Path)
    recover=sub.add_parser('recover');recover.add_argument('attempt',type=Path);recover.add_argument('--reviewer',required=True);recover.add_argument('--evidence',required=True)
    args=p.parse_args()
    def read(path):return json.loads(path.read_text(encoding='utf-8-sig'))
    try:
        if args.action=='package':
            from ql5050px.modeling_delivery import export_delivery
            result=export_delivery(read(args.request),args.out)
        elif args.action=='review':
            from ql5050px.modeling_delivery import prepare_jobs
            jobs=prepare_jobs(read(args.request),sw_exe=args.sw_exe,template=args.template,sketch_plane=args.sketch_plane,review=True)
            with args.out.open('x',encoding='utf-8') as f:json.dump({'jobs':jobs},f,ensure_ascii=False,indent=2)
            result={'status':'review_required','reviewed_manifest':str(args.out),'jobs':len(jobs)}
        elif args.action=='run':
            if sys.platform!='win32':raise ValueError('Windows native execution required')
            from ql5050px.modeling_supervisor import supervise
            result=supervise(read(args.manifest)['jobs'],args.out,resume=args.resume)
        elif args.action=='evidence':
            from ql5050px.acceptance_report import export_acceptance
            result=export_acceptance(args.batch,args.out)
        elif args.action=='recover':
            from ql5050px.modeling_recovery import recover_attempt
            result={'status':'review_required','recovery':recover_attempt(args.attempt,reviewer=args.reviewer,evidence=args.evidence)}
        else:
            from ql5050px.native_environment import inspect_environment
            result=inspect_environment(args.sw_exe)
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 1 if result.get('status') in {'failed','conflict'} else 3
    except (OSError,ValueError,KeyError,RuntimeError,TypeError) as exc:
        print(json.dumps({'status':'failed','error':str(exc)},ensure_ascii=False));return 1

if __name__=='__main__':raise SystemExit(main())
