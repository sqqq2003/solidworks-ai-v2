import argparse,json,sys
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parents[1]/'src')]
from src.ql5050px.drawing_trial import run_trial

if __name__=='__main__':
    from app_logging import bootstrap
    bootstrap(Path(__file__).resolve().parents[1],'native-drawing-worker')
    parser=argparse.ArgumentParser();parser.add_argument('--request',type=Path,required=True);args=parser.parse_args()
    result=run_trial(json.loads(args.request.read_text(encoding='utf-8')))
    print(json.dumps({k:v for k,v in result.items() if k not in ('components','loads')},ensure_ascii=False,default=str))
    raise SystemExit(0 if result['status']=='completed_partial_model_trial' and not result['source_hash_mismatches'] else 1)
