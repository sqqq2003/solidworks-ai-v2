"""JSON-lines bridge for existing project.py/app.py, offline by default."""
import argparse
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from ql5050px.workflow import ACTIONS, run_workflow


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--action',choices=sorted(ACTIONS),default='plan')
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--config',type=Path)
    source.add_argument('--request-json')
    parser.add_argument('--output-dir',type=Path)
    parser.add_argument('--resume',action='store_true')
    args = parser.parse_args(argv)
    try:
        config = json.loads(args.config.read_text(encoding='utf-8-sig')) if args.config else json.loads(args.request_json)
        result = run_workflow(args.action,config,output_dir=args.output_dir,resume=args.resume)
        event = {'event':'plan' if args.action=='plan' else 'done','kind':'ql5050px',
                 'status':result['status'],'workflow':result,'plan':result['plan'],'cad_executed':False}
        print(json.dumps(event,ensure_ascii=False,allow_nan=False))
        return 1 if result['status']=='failed' else 3
    except Exception as exc:
        print(json.dumps({'event':'error','kind':'ql5050px','message':str(exc),'cad_executed':False},ensure_ascii=False))
        return 1


if __name__=='__main__':
    raise SystemExit(main())
