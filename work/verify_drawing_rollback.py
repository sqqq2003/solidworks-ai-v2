"""Explicit Windows fault check for isolated A01 dimensions -> drawing/PDF."""
import argparse,json,sys
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'src')]


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('request',type=Path);p.add_argument('--sw-exe',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True);p.add_argument('--request-key',required=True)
    p.add_argument('--fault-after',choices=('saved_dimension','pdf'),required=True)
    p.add_argument('--enable-fault-injection',action='store_true',required=True)
    args=p.parse_args(argv)
    try:
        if sys.platform!='win32':raise RuntimeError('Windows SolidWorks required; cloud cannot verify this fault')
        if args.out.exists():raise FileExistsError('fault test requires a new output directory')
        from project_delivery import read_json
        from src.a01_next.native_production import A01ProductionDriver,run_production
        from drawing_review import atomic_json
        from cad_receipts import ReceiptStore
        from cad_checkpoint import Checkpoint,inspect_checkpoint,digest_file
        request=read_json(args.request);request['fault_test']={'after':args.fault_after}
        triggered=[]
        if args.fault_after=='saved_dimension':
            original=A01ProductionDriver._save
            def fail(driver,model):
                original(driver,model);triggered.append('saved_dimension')
                raise RuntimeError('GORK_FAULT_AFTER_SAVED_DIMENSION_BATCH')
            injection=patch.object(A01ProductionDriver,'_save',fail)
        else:
            from src.ql5050px.drawing_verification import export_pdf
            def fail(*a,**kw):
                export_pdf(*a,**kw);triggered.append('pdf')
                raise RuntimeError('GORK_FAULT_AFTER_PDF_SAVE')
            injection=patch('src.ql5050px.drawing_verification.export_pdf',fail)
        with injection:
            result=run_production(request,args.sw_exe,args.out,idempotency_key=args.request_key)
        errors=[]
        if triggered!=[args.fault_after]:errors.append('fault_not_reached_exactly_once')
        if result.get('status')!='failed' or result.get('rollback',{}).get('state')!='RESTORED':errors.append('rollback_unconfirmed')
        receipt=result.get('request_receipt',{})
        if receipt.get('status')!='FAILED' or receipt.get('session_state')!='RESOLVED':errors.append('request_still_unresolved')
        row=ReceiptStore().get(receipt['key']);declared=row['metadata']['checkpoint']
        checkpoint=Checkpoint(Path(declared['directory']),declared['manifest_sha256'],Path(declared['scope']))
        manifest=inspect_checkpoint(checkpoint)
        for item in manifest['files']:
            if digest_file(item['target'])!=item['source_sha256']:errors.append('copied_model_not_baseline')
        for path,sha in manifest['original_sha256'].items():
            if digest_file(path)!=sha:errors.append('user_original_changed')
        report={'status':'failed' if errors else 'review_required','fault_after':args.fault_after,
                'triggered':triggered,'errors':errors,'request_receipt':receipt,
                'rollback':result.get('rollback'),'delivery_accepted':False,'manufacturing_approved':False}
        atomic_json(args.out/'drawing-rollback-fault.json',report,exclusive=True)
        print(json.dumps(report,ensure_ascii=False,indent=2));return 1 if errors else 3
    except (OSError,ValueError,TypeError,KeyError,RuntimeError) as error:
        print(json.dumps({'status':'failed','error':str(error),'delivery_accepted':False},ensure_ascii=False));return 1


if __name__=='__main__':raise SystemExit(main())
