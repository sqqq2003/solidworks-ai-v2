"""Validate A01 mappings by default; --live explicitly starts an owned CAD job."""
import argparse
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'src')]
from src.a01_next.production import prepare_request


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('request',type=Path)
    p.add_argument('--live',action='store_true')
    p.add_argument('--sw-exe',type=Path)
    p.add_argument('--out',type=Path)
    a=p.parse_args()
    try:
        request=json.loads(a.request.read_text(encoding='utf-8-sig'))
        if a.live:
            if not a.sw_exe or not a.out:raise ValueError('--live requires --sw-exe and fresh --out')
            from src.a01_next.native_production import run_production
            result=run_production(request,a.sw_exe,a.out)
        else:result=prepare_request(request)
        print(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
        return 0
    except (OSError,ValueError,TypeError,KeyError,RuntimeError,AttributeError) as error:
        print(json.dumps(dict(status='failed',error=str(error),engineering_acceptance='unverified'),ensure_ascii=False))
        return 3


if __name__=='__main__':raise SystemExit(main())
