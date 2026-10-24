"""Read-only process liveness and explicit recovery of abandoned attempt records."""
import json,os
from pathlib import Path


def process_alive(pid):
    if type(pid) is not int or pid<=0:raise ValueError('valid recorded worker PID required')
    if os.name=='nt':
        import ctypes
        from ctypes import wintypes
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
        kernel.OpenProcess.restype=wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]
        kernel.WaitForSingleObject.restype=wintypes.DWORD
        kernel.CloseHandle.argtypes=[wintypes.HANDLE]
        handle=kernel.OpenProcess(0x00100000,False,pid)
        if not handle:
            error=ctypes.get_last_error()
            if error==87:return False
            raise RuntimeError('cannot prove worker exit; process query denied: '+str(error))
        try:
            result=kernel.WaitForSingleObject(handle,0)
            if result==0:return False
            if result==258:return True
            raise RuntimeError('worker liveness unknown')
        finally:kernel.CloseHandle(handle)
    try:os.kill(pid,0);return True
    except ProcessLookupError:return False
    except PermissionError:raise RuntimeError('cannot prove worker exit')


def recover_attempt(attempt,*,reviewer,evidence):
    """Never terminates processes or closes SW documents. Operator verifies SW state."""
    if not reviewer or not evidence:raise ValueError('reviewer and SW-session evidence required')
    attempt=Path(attempt).resolve();record=attempt/'supervisor.json'
    if record.exists():row=json.loads(record.read_text())
    else:
        worker=json.loads((attempt/'worker.json').read_text())
        row={'worker_pid':worker['pid'],'status':'needs_review','worker_may_be_running':True}
    if process_alive(row['worker_pid']):raise RuntimeError('worker still running; recovery refused')
    approval={'reviewer':reviewer,'evidence':evidence,'worker_exit_observed':True,
        'note':'Operator checked previous SW session; no shutdown or COM action performed.'}
    with (attempt/'recovery-review.json').open('x',encoding='utf-8') as stream:json.dump(approval,stream,indent=2)
    row.update(worker_may_be_running=False,status='needs_review',recovery_approved=True)
    temp=record.with_suffix('.new');temp.write_text(json.dumps(row,indent=2));temp.replace(record)
    return approval
