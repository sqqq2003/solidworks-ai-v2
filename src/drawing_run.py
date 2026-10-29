"""Use existing v5 receipts/STA ownership for the two native drawing entries."""
import hashlib

from cad_checkpoint import digest_file,json_bytes
from cad_receipts import ReceiptStore


def note_drawing_process(lease):
    from cad_reconcile import owned_process_identity
    store,key,owner=lease.durable_attempt
    store.update_metadata(key,owner,process=owned_process_identity(lease))


def run_receipted_drawing(document,originals,payload,job,*,timeout,task_name,state_db=None,key=None):
    from sw_session import run_on_task_sta,current_lease
    from cad_reconcile import current_controller_identity
    from drawing_review import drawing_implementation_hashes
    store=ReceiptStore(state_db)
    revision=hashlib.sha256(json_bytes(originals)).hexdigest()
    payload={'input':payload,'implementation_sha256':drawing_implementation_hashes()}
    row=store.begin(document,revision,payload,key=key,metadata={'original_sha256':originals})
    key,owner=row['key'],row['owner']
    if row['replayed']:
        return {**row['result'],'request_receipt':{'key':key,'status':row['status'],
                'session_state':row['session_state'],'replayed':True,'cad_reexecuted':False}}
    def guarded():
        lease=current_lease();lease.close_doc_only=True
        lease.durable_attempt=(store,key,owner)
        lease.durable_write_guard=lambda:store.assert_writer(key,owner)
        try:
            store.update_metadata(key,owner,controller=current_controller_identity())
            return job()
        finally:
            lease.durable_write_guard=None
            lease.durable_attempt=None
            store.returned(key,owner)
    try:
        result=run_on_task_sta(guarded,timeout=timeout,task_name=task_name,durable_attempt=(store,key,owner))
        unchanged=all(digest_file(p)==sha for p,sha in originals.items())
        session=result.get('session',{})
        cleanup=(session.get('cleanup_status') in {'left_open_keepalive','process_exited_cleanly'} and
                 not session.get('cleanup_error') and not session.get('cleanup_disconnect'))
        success=result.get('status') in {'completed_partial_model_trial','native_workflow_executed_pending_review'}
        restored=result.get('rollback',{}).get('state')=='RESTORED'
        if unchanged and cleanup and (success or restored):
            store.finish(key,owner,result,succeeded=success)
        else:
            store.quarantine(key,owner,'ROLLBACK_UNCONFIRMED' if result.get('rollback',{}).get('state')=='ROLLBACK_UNCONFIRMED' else 'OUTCOME_UNKNOWN')
        receipt=store.get(key)
        result.update(request_receipt={'key':key,'status':receipt['status'],'session_state':receipt['session_state'],
                                       'replayed':False},delivery_accepted=False,acceptance_state='reviewing')
        return result
    except BaseException as error:
        store.quarantine(key,owner,'OUTCOME_UNKNOWN',detail={'error_type':type(error).__name__})
        raise
