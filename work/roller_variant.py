"""Issue24: plan/package or explicitly run an isolated 800mm overall roller variant."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=('plan','package','inspect','native'))
    p.add_argument('--request',type=Path,required=True);p.add_argument('--out',type=Path);p.add_argument('--sw-exe',type=Path)
    p.add_argument('--state-db',type=Path);p.add_argument('--idempotency-key')
    args=p.parse_args()
    try:
        request=json.loads(args.request.read_text(encoding='utf-8-sig'))
        if args.action=='plan':
            from roller_variant import plan_variant
            result=plan_variant(request)
        elif args.action=='package':
            if not args.out:raise ValueError('--out required')
            from roller_variant.delivery import export_package
            result=export_package(request,args.out)
        else:
            if not args.out or not args.sw_exe:raise ValueError('--out and --sw-exe required')
            from roller_variant.native import run_native
            result=run_native(request,args.out,args.sw_exe,inspect_only=args.action=='inspect',
                              state_db=args.state_db,idempotency_key=args.idempotency_key)
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 1 if result['status']=='failed' else 3
    except (OSError,ValueError,RuntimeError,KeyError,TypeError) as exc:
        print(json.dumps({'status':'failed','error':str(exc)},ensure_ascii=False));return 1

if __name__=='__main__':raise SystemExit(main())
