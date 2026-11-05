"""Explicit native fault after a parameter batch was actually saved to its copy."""
import argparse
import json
from pathlib import Path
import sys
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT)]


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('workspace',type=Path);parser.add_argument('--sw-exe',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True);parser.add_argument('--approval-sha256',required=True)
    parser.add_argument('--request-key',required=True);parser.add_argument('--state-db',type=Path)
    parser.add_argument('--session-mode',choices=('auto','idle_existing','dedicated'),default='auto')
    parser.add_argument('--enable-fault-injection',action='store_true',required=True)
    args=parser.parse_args(argv)
    try:
        if sys.platform!='win32':raise RuntimeError('Windows SolidWorks required; cloud cannot verify this native fault')
        if args.out.exists():raise FileExistsError('fault test requires a new output directory')
        from parametric_functions.native import DimensionExecutionPort
        from parametric_functions.api import execute_edit_workspace
        from cad_receipts import ReceiptStore
        from cad_checkpoint import Checkpoint,inspect_checkpoint,digest_file
        from drawing_review import atomic_json
        original=DimensionExecutionPort.save_as;triggered=[]
        def fail(port,destination):
            original(port,destination);triggered.append('after_saved_parameter_batch')
            raise RuntimeError('GORK_FAULT_AFTER_SAVED_PARAMETER_BATCH')
        with patch.object(DimensionExecutionPort,'save_as',fail):
            result=execute_edit_workspace(args.workspace,args.sw_exe,args.out,approval_sha256=args.approval_sha256,
                request_key=args.request_key,state_db=args.state_db,session_mode=args.session_mode,
                fault_test='after_saved_parameter_batch')
        errors=[]
        if triggered!=['after_saved_parameter_batch']:errors.append('fault_not_reached_exactly_once')
        if result.get('status')!='failed' or result.get('rollback',{}).get('state')!='RESTORED':errors.append('rollback_not_confirmed')
        receipt=result.get('request_receipt',{})
        if receipt.get('status')!='FAILED' or receipt.get('session_state')!='RESOLVED':errors.append('request_unresolved')
        row=ReceiptStore(args.state_db).get(receipt['key']);declared=row['metadata']['checkpoint']
        checkpoint=Checkpoint(Path(declared['directory']),declared['manifest_sha256'],Path(declared['scope']))
        manifest=inspect_checkpoint(checkpoint)
        for item in manifest['files']:
            if digest_file(item['target'])!=item['source_sha256']:errors.append('work_copy_not_at_baseline')
        for path,sha in manifest['original_sha256'].items():
            if digest_file(path)!=sha:errors.append('original_changed')
        report={'status':'failed' if errors else 'review_required','errors':errors,'triggered':triggered,
                'rollback':result.get('rollback'),'request_receipt':receipt,
                'source_revision_required_from_candidate':True,'manufacturing_approved':False}
        atomic_json(args.out/'parameter-edit-rollback-fault.json',report,exclusive=True)
        print(json.dumps(report,ensure_ascii=False,indent=2));return 1 if errors else 3
    except (OSError,ValueError,TypeError,KeyError,RuntimeError) as error:
        print(json.dumps({'status':'failed','error':str(error),'manufacturing_approved':False},ensure_ascii=False));return 1


if __name__=='__main__':raise SystemExit(main())
