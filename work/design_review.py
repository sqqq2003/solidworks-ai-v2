"""Read-only design impact review or engineering evidence assessment."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))

def main():
    p=argparse.ArgumentParser(description=__doc__);s=p.add_subparsers(dest='action',required=True)
    impact=s.add_parser('impact');impact.add_argument('--plan',type=Path,required=True);impact.add_argument('--intent',type=Path,required=True)
    accept=s.add_parser('acceptance');accept.add_argument('--evidence',type=Path,required=True);accept.add_argument('--artifact-root',type=Path)
    repair=s.add_parser('repairs');repair.add_argument('--assessment',type=Path,required=True)
    p.add_argument('--out',type=Path);args=p.parse_args()
    def read(path):return json.loads(path.read_text(encoding='utf-8-sig'))
    try:
        from design_review import analyze_impact,evaluate_acceptance,propose_repairs
        if args.action=='repairs':result=propose_repairs(read(args.assessment))
        else:result=analyze_impact(read(args.plan),read(args.intent)) if args.action=='impact' else evaluate_acceptance(read(args.evidence),artifact_root=args.artifact_root)
        if args.out:
            with args.out.open('x',encoding='utf-8') as f:json.dump(result,f,ensure_ascii=False,indent=2)
        print(json.dumps(result,ensure_ascii=False,indent=2));return {'passed':0,'degraded':2,'failed':1,'review_required':3,'no_repair_proposed':0}[result['status']]
    except (ValueError,KeyError,TypeError,OSError) as exc:
        print(json.dumps({'status':'failed','error':str(exc)},ensure_ascii=False));return 1

if __name__=='__main__':raise SystemExit(main())
