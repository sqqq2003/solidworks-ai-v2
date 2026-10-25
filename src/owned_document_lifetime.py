"""Task-owned document anchor for intermediate last-document closes.

No process attachment, no arbitrary CloseDoc, no model defaults or forced kill.
The existing lease/STA/PID/write checks remain the authority. Native unverified.
"""
from pathlib import Path
import subprocess


def ensure_anchor(lease,app):
    if not getattr(lease,'keepalive_document_enabled',False) or not lease.keep_application_open:return
    from sw_session import require_model_write,SessionOwnershipError
    require_model_write(lease)
    titles=set(lease.list_open_titles(app))
    current=getattr(lease,'keepalive_document_title',None)
    if current:
        if current not in titles or current not in lease.owned_docs:
            lease.writes_blocked=True
            raise SessionOwnershipError('owned keepalive document disappeared; preserve session for recovery')
        return
    # No anchor is needed while two or more documents remain. Creation happens
    # before closing the last original document, never after the server is lost.
    if len(titles)>1:return
    import solidworks_generator as sw
    template=getattr(lease,'keepalive_part_template_path',None) or app.GetUserPreferenceStringValue(sw.SW_DEFAULT_TEMPLATE_PART)
    if not template or not Path(template).is_file():
        lease.writes_blocked=True
        raise SessionOwnershipError('existing part template required for owned document anchor; close refused')
    model=None
    try:
        model=app.NewDocument(str(template),0,0.0,0.0)
        if model is None:raise RuntimeError('NewDocument returned no keepalive document')
        title=str(sw._com_read(model,'GetTitle'))
        if not title or title in titles or int(sw._com_read(model,'GetType'))!=1:
            raise RuntimeError('keepalive document identity/type is not a new native part')
        lease.note_owned_document(title,handle_id=id(model))
        lease.keepalive_document_title=title
        binding=lease.native_launch
        if binding is not None:binding.anchor_created=True
        require_model_write(lease)
    except Exception as exc:
        lease.writes_blocked=True
        raise SessionOwnershipError('owned document anchor could not be established; close refused') from exc
    finally:model=None


def poll_exit(binding,timeout=0):
    process=getattr(binding.lifetime,'process',None)
    if process is None:return None
    code=process.poll()
    if code is None and timeout:
        try:code=process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:return None
    return code


def finish_owned_session(lease,binding):
    """Close only our anchor after proving it is the sole remaining document.

    A clean automatic server exit after anchor CloseDoc needs no further COM
    calls. Any crash/nonzero/unknown exit is preserved for independent review.
    """
    from sw_session import require_model_write,close_owned_document,exit_owned_application,SessionOwnershipError
    anchor_started=False
    try:
        binding.validate(lease);require_model_write(lease)
        titles=set(binding.list_titles(binding.app));anchor=getattr(lease,'keepalive_document_title',None)
        if titles-({anchor} if anchor else set()):
            raise SessionOwnershipError('task/foreign documents remain; no final cleanup or ExitApp')
        if anchor:
            if anchor not in titles or anchor not in lease.owned_docs:raise SessionOwnershipError('keepalive document ownership/inventory differs')
            anchor_started=True
            close_owned_document(lease,binding.app,anchor)
            lease.keepalive_document_title=None
            binding.anchor_closed=True
            code=poll_exit(binding)
            if code is not None:
                if type(code) is not int or code!=0:raise RuntimeError('owned process exited abnormally after anchor close: '+str(code))
                binding.cleanup_status='process_exited_cleanly';return
        binding.validate(lease);require_model_write(lease)
        if binding.list_titles(binding.app):raise SessionOwnershipError('documents remain; ExitApp refused')
        exit_owned_application(lease,binding.app)
        binding.cleanup_status='exit_requested'
        code=poll_exit(binding,timeout=2)
        if code is not None:
            if type(code) is not int or code!=0:raise RuntimeError('owned process exited abnormally: '+str(code))
            binding.cleanup_status='process_exited_cleanly'
        else:
            binding.cleanup_status='left_open_for_recovery'
            binding.cleanup_error='owned process exit remains unobserved after exit request; preserve session'
    except Exception as exc:
        code=poll_exit(binding,timeout=2 if anchor_started else 0)
        # Only an already-proved sole-anchor close can cause expected COM
        # disconnection on clean auto-exit. Do not hide errors from other phases.
        from sw_session import _exception_is_disconnect
        if anchor_started and type(code) is int and code==0 and _exception_is_disconnect(exc):
            lease.owned_docs.pop(getattr(lease,'keepalive_document_title',None),None)
            lease.keepalive_document_title=None;binding.anchor_closed=True
            binding.cleanup_status='process_exited_cleanly';return
        binding.cleanup_status='left_open_for_recovery' if code is None else 'process_exit_failed'
        binding.cleanup_error=type(exc).__name__+': '+str(exc)


def release_closed_session_references(lease,binding):
    """Release only the completed session's app references, on its STA."""
    if binding.cleanup_error or binding.cleanup_status not in {'exit_requested','process_exited_cleanly'}:return
    from sw_session import on_task_sta,SessionOwnershipError
    if not on_task_sta():raise SessionOwnershipError('COM references must be released on the task STA')
    lease.app_for_recycle=None
    lease.native_launch.app=None
    lease.bound_app_ids.clear();lease.app_handle_id=None
    lease.verified_exclusive=False;lease.writes_blocked=True
