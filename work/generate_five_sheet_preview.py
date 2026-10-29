"""Export five reviewed presentation partitions; no SolidWorks activation."""
import argparse
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'src')]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--resume',action='store_true')
    args=parser.parse_args()
    from app_logging import bootstrap
    journal=bootstrap(ROOT,'five-sheet-preview')
    try:
        from five_sheet_preview import generate
        state=generate(args.manifest,args.output,resume=args.resume)
        print(json.dumps({'status':state['status'],'output':str(args.output),
                          'production_approved':False},ensure_ascii=False))
        return 0
    except Exception as error:
        journal.exception('five_sheet_preview_cli_failed',error)
        print(str(error),file=sys.stderr)
        return 1


if __name__=='__main__':raise SystemExit(main())
