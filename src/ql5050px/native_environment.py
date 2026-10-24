"""Non-writing environment report; no spawn, CloseDoc, ExitApp or gate bypass."""
import sys,os,importlib.util,json
from pathlib import Path


def inspect_environment(executable=None):
    result={'platform':sys.platform,'python':sys.version.split()[0],
        'requested_executable_exists':Path(executable).is_file() if executable else None,
        'pywin32_available':importlib.util.find_spec('pythoncom') is not None,
        'cad_written':False,'spawned':False,'documents_closed':False,
        'native_acceptance':'pending_windows_validation','diagnostics':[]}
    if sys.platform!='win32':
        result['status']='windows_required';return result
    try:
        import pythoncom,win32com.client
    except ImportError:
        result['status']='pywin32_missing';return result
    pythoncom.CoInitialize()
    app=None
    try:
        try:app=win32com.client.GetActiveObject('SldWorks.Application')
        except pythoncom.com_error:
            result['status']='no_registered_active_instance'
            result['diagnostics'].append('No active COM object does not prove an owned new instance will bind.')
            return result
        pid=app.GetProcessID();revision=app.RevisionNumber
        if callable(revision):revision=revision()
        result.update(status='active_instance_observed',active_pid=int(pid),revision=str(revision),
            open_document_count=len(app.GetDocuments() or []),owned_write_authorized=False)
        result['diagnostics'].append('Active object is observational only. Single-instance COM registration can prevent a new spawned PID from binding. Run owned launch proof separately; never bypass require_model_write.')
    except Exception as exc:
        result.update(status='read_only_probe_failed',error=type(exc).__name__+': '+str(exc))
    finally:
        app=None
        pythoncom.CoUninitialize()
    return result
