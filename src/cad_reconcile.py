"""Conservative Windows reconciliation: no COM attachment or process signals.

An unresolved writer can only be released here after both the original Python
controller and the exact spawned CAD process have exited, and all checkpointed
work bytes plus original user files equal their baseline. A live/unknown PID or
a missing checkpoint needs operator recovery and stays quarantined.
"""
import os
from pathlib import Path
import sys

from cad_checkpoint import Checkpoint, digest_file, inspect_checkpoint
from cad_receipts import ReceiptStore, ReconcileRequired


def _kernel():
    if sys.platform != 'win32':
        raise RuntimeError('native process reconciliation requires Windows')
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel.GetProcessTimes.restype = wintypes.BOOL
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.GetExitCodeProcess.restype = wintypes.BOOL
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    return kernel


def _stamp(kernel, handle):
    import ctypes
    from ctypes import wintypes
    creation, exited, system, user = (wintypes.FILETIME() for _ in range(4))
    if not kernel.GetProcessTimes(handle, ctypes.byref(creation), ctypes.byref(exited),
                                  ctypes.byref(system), ctypes.byref(user)):
        raise ctypes.WinError(ctypes.get_last_error())
    return (creation.dwHighDateTime << 32) | creation.dwLowDateTime


def current_controller_identity():
    kernel = _kernel()
    return {'pid': os.getpid(), 'creation_filetime': _stamp(kernel, kernel.GetCurrentProcess())}


def owned_process_identity(lease):
    from sw_session import require_model_write
    require_model_write(lease)
    lifetime = lease.native_launch.lifetime
    if lifetime.pid != lease.spawned_pid or lifetime.process.poll() is not None:
        raise ReconcileRequired('spawned CAD identity unavailable')
    # Retained spawn handle, never a PID reopened after possible reuse.
    return {'pid': lifetime.pid, 'creation_filetime': _stamp(_kernel(), int(lifetime.process._handle))}


def process_still_matches(identity):
    import ctypes
    from ctypes import wintypes
    if (not isinstance(identity, dict) or type(identity.get('pid')) is not int or
            type(identity.get('creation_filetime')) is not int or identity['pid'] <= 0 or
            identity['creation_filetime'] <= 0):
        raise ReconcileRequired('missing durable process identity')
    kernel = _kernel()
    handle = kernel.OpenProcess(0x1000, False, identity['pid'])
    if not handle:
        error = ctypes.get_last_error()
        if error == 87:  # ERROR_INVALID_PARAMETER: no process for this PID.
            return False
        raise ReconcileRequired('cannot prove old process exited: Windows error ' + str(error))
    try:
        if _stamp(kernel, handle) != identity['creation_filetime']:
            return False  # PID reused; the original process is gone.
        code = wintypes.DWORD()
        if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)):
            raise ctypes.WinError(ctypes.get_last_error())
        return code.value == 259  # STILL_ACTIVE
    finally:
        kernel.CloseHandle(handle)


def verify_quiescent_baseline(row, *, process_probe=process_still_matches):
    metadata = row['metadata']
    for role in ('controller', 'process'):
        if process_probe(metadata.get(role)):
            raise ReconcileRequired('old ' + role + ' is still alive; no write lease released')
    original_hashes = metadata.get('original_sha256')
    if not original_hashes:
        raise ReconcileRequired('original source hashes missing')
    for path, expected in original_hashes.items():
        if digest_file(path) != expected:
            raise ReconcileRequired('original source changed; engineering review required')
    declared = metadata.get('checkpoint')
    if not declared:
        raise ReconcileRequired('checkpoint not sealed before crash; manual recovery required')
    checkpoint = Checkpoint(Path(declared['directory']), declared['manifest_sha256'], Path(declared['scope']))
    manifest = inspect_checkpoint(checkpoint)
    if manifest['original_sha256'] != original_hashes:
        raise ReconcileRequired('checkpoint original baseline differs from durable receipt')
    for item in manifest['files']:
        if digest_file(item['target']) != item['source_sha256']:
            raise ReconcileRequired('isolated CAD is not restored; preserve checkpoint and recover it first')
    return {'quiescent': True, 'baseline_bytes_verified': True,
            'manifest_sha256': checkpoint.manifest_sha256,
            'native_reopen_verified': False,
            'scope': 'dead_controller_and_spawned_process_plus_byte_baseline_only'}


def reconcile_native(key, *, state_db=None):
    if sys.platform != 'win32':
        raise RuntimeError('native reconciliation requires Windows; cloud can inspect receipts')
    return ReceiptStore(state_db).reconcile(key, verify_quiescent_baseline)


def restore_dead_attempt_bytes(key, *, state_db=None):
    """Restore sealed task-copy bytes after both exact old processes exited.

    Preserve pre-recovery artifacts. This proves byte baseline only, never a
    native reopen, and uses the existing serialized reconciliation transaction.
    """
    import shutil
    import tempfile
    import uuid
    from cad_checkpoint import safe_file
    if sys.platform!='win32':raise RuntimeError('native recovery requires Windows')

    def restore_and_verify(row):
        from sw_owned_launch import _snapshot_sldworks_pids
        metadata=row['metadata']
        for role in ('controller','process'):
            if process_still_matches(metadata.get(role)):
                raise ReconcileRequired('old '+role+' still alive; restore refused')
        if _snapshot_sldworks_pids():
            raise ReconcileRequired('SolidWorks instances still running; task-copy restore refused')
        declared=metadata.get('checkpoint')
        if not declared:raise ReconcileRequired('sealed checkpoint required for byte restoration')
        checkpoint=Checkpoint(Path(declared['directory']),declared['manifest_sha256'],Path(declared['scope']))
        manifest=inspect_checkpoint(checkpoint)
        if not metadata.get('original_sha256') or manifest['original_sha256']!=metadata['original_sha256']:
            raise ReconcileRequired('original baseline differs from receipt')
        for name,expected in metadata['original_sha256'].items():
            if digest_file(name)!=expected:raise ReconcileRequired('original changed; restore refused')
        archive=checkpoint.directory.parent/('pre-recovery-'+uuid.uuid4().hex)
        archive.mkdir(exist_ok=False)
        preserved=[]
        for index,item in enumerate(manifest['files']):
            target=safe_file(item['target'],checkpoint.scope)
            before=digest_file(target);retained=archive/(str(index)+target.suffix)
            with target.open('rb') as source,retained.open('xb') as output:shutil.copyfileobj(source,output)
            if digest_file(retained)!=before or digest_file(target)!=before:
                raise ReconcileRequired('task copy changed during preservation')
            preserved.append({'target':str(target),'archive':str(retained),'sha256':before})
        # Re-check liveness immediately before replacements; do not signal CAD.
        for role in ('controller','process'):
            if process_still_matches(metadata[role]):raise ReconcileRequired('old process became active')
        for index,item in enumerate(manifest['files']):
            target=safe_file(item['target'],checkpoint.scope)
            fd,temp=tempfile.mkstemp(prefix='.dead-restore-',dir=target.parent)
            try:
                with os.fdopen(fd,'wb') as output,(checkpoint.directory/item['backup']).open('rb') as source:
                    shutil.copyfileobj(source,output);output.flush();os.fsync(output.fileno())
                if digest_file(temp)!=item['source_sha256']:raise ReconcileRequired('restore bytes differ from checkpoint')
                if digest_file(target)!=preserved[index]['sha256']:
                    raise ReconcileRequired('task copy changed after preservation')
                if _snapshot_sldworks_pids():raise ReconcileRequired('SolidWorks appeared during recovery')
                os.replace(temp,target)
            finally:
                if Path(temp).exists():Path(temp).unlink()
        proof=verify_quiescent_baseline(row,process_probe=process_still_matches)
        proof.update(byte_restore_performed=True,preserved_artifacts=preserved)
        return proof

    return ReceiptStore(state_db).reconcile(key,restore_and_verify)
