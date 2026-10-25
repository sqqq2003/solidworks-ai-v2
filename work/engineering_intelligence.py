"""Engineering API/JSON CLI, no COM or CAD write command."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from engineering_intelligence import build_batch, run_module
from engineering_intelligence.workflow import MODULES


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('module',choices=['batch',*MODULES])
    parser.add_argument('request',type=Path)
    parser.add_argument('--out',type=Path)
    args=parser.parse_args(argv)
    try:
        request=json.loads(args.request.read_text(encoding='utf-8-sig'))
        if args.module=='batch': report=build_batch(request,args.out)
        elif args.out: report=build_batch({'modules':{args.module:request}},args.out)
        else: report=run_module(args.module,request)
        print(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False))
        return {'passed':0,'degraded':2,'failed':1,'review_required':3}[report['status']]
    except (ValueError,KeyError,TypeError,OSError,OverflowError) as exc:
        print(json.dumps({'status':'failed','error':type(exc).__name__+': '+str(exc),'cad_executed':False},ensure_ascii=False))
        return 1


if __name__=='__main__': raise SystemExit(main())
