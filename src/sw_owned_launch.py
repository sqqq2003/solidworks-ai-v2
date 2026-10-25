"""Spawn and bind a task-owned SolidWorks process on the serialized STA.

No PID-by-name claims, GetActiveObject write bypass, or process termination.
Process handles survive until the binding is discarded, preventing PID reuse
from becoming ownership evidence. Linux tests inject fake process/COM ports.
"""
from contextlib import contextmanager
import os
from pathlib import Path
import subprocess
import sys
import time

from owned_document_lifetime import (
    DEFAULT_EXIT_POLL_SECONDS, prepare_owned_inventory,
)
from sw_session import (SessionOwnershipError, ProcessProbeInfo, current_lease,
    on_task_sta, claim_spawned_process, require_model_write)


class WindowsProcessLifetime:
    def __init__(self, executable):
        self.executable = str(executable)
        self.process = subprocess.Popen([self.executable], shell=False,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.pid = self.process.pid

    def probe(self, pid):
        if pid != self.pid or self.process.poll() is not None:
            return None
        # Query the retained process handle, never reopen a possibly reused PID.
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        query = kernel.QueryFullProcessImageNameW
        query.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                          ctypes.POINTER(wintypes.DWORD)]
        query.restype = wintypes.BOOL
        size = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not query(int(self.process._handle), 0, buffer, ctypes.byref(size)):
            raise OSError(ctypes.get_last_error(), 'cannot verify launched process image')
        if os.path.normcase(os.path.realpath(buffer.value)) != os.path.normcase(os.path.realpath(self.executable)):
            raise SessionOwnershipError('spawned process image differs from requested executable')
        return ProcessProbeInfo(pid, True, buffer.value)


def _native_candidate(pid):
    import pythoncom
    import win32com.client
    # Read-only discovery; never Dispatch a ProgID (which can create another PID).
    try:
        app = win32com.client.GetActiveObject('SldWorks.Application')
        if _read_pid(app) == pid:
            return app
    except Exception:
        pass
    rot = pythoncom.GetRunningObjectTable()
    for count, moniker in enumerate(rot.EnumRunning()):
        if count >= 256:
            break
        try:
            name = moniker.GetDisplayName(pythoncom.CreateBindCtx(0), None).casefold()
            if 'solidworks' not in name and 'sldworks' not in name:
                continue
            app = win32com.client.Dispatch(rot.GetObject(moniker))
            if _read_pid(app) == pid:
                return app
        except Exception:
            continue
    return None


def _read_pid(app):
    """Read the owned PID. A dead IDispatch becomes ComSessionDisconnected."""
    from sw_session import normalize_com_disconnect
    try:
        value = getattr(app, 'GetProcessID')
        return int(value() if callable(value) else value)
    except Exception as exc:
        normalized = normalize_com_disconnect(exc)
        if normalized is not None:
            raise normalized from exc
        raise


class OwnedBinding:
    def __init__(self, lifetime, app, read_pid, list_titles):
        self.lifetime, self.app = lifetime, app
        self.read_pid, self.list_titles = read_pid, list_titles
        self.cleanup_status = 'not_attempted'
        self.cleanup_error = None
        self.cleanup_disconnect = None
        self.keepalive_verified = False
        self.anchor_created = False
        self.anchor_closed = False
        self.rediscover = None
        self.rebind_attempted = False

    def _read_connection(self):
        image_ok = self.lifetime.probe(self.lifetime.pid) is not None
        return image_ok, self.read_pid(self.app)

    def rebind_owned_pid(self, lease):
        """One rediscovery of this task's PID. A dead IDispatch is not a new process."""
        if self.rebind_attempted:
            return False
        self.rebind_attempted = True
        discover = self.rediscover
        if discover is None or self.lifetime.probe(self.lifetime.pid) is None:
            return False
        try:
            app = discover(self.lifetime.pid)
            if app is None or self.read_pid(app) != self.lifetime.pid:
                return False
        except Exception:
            return False
        self.app = app
        lease.note_bound_application(app)
        lease.disconnected = False
        lease.writes_blocked = False
        if not lease.poisoned and not lease.timed_out:
            lease.verified_exclusive = True
        return True

    def _read_connection_or_rebind(self, lease):
        from sw_session import normalize_com_disconnect
        try:
            return self._read_connection()
        except Exception as exc:
            normalized = normalize_com_disconnect(exc)
            if normalized is not None and self.rebind_owned_pid(lease):
                try:
                    return self._read_connection()
                except Exception as again:
                    exc = again
                    normalized = normalize_com_disconnect(again) or normalized
            if normalized is None:
                raise
            lease.verified_exclusive = False
            lease.writes_blocked = True
            lease.disconnected = True
            raise normalized from exc

    def validate(self, lease, *, documents=True):
        from sw_session import normalize_com_disconnect
        image_ok, com_pid = self._read_connection_or_rebind(lease)
        if not image_ok or com_pid != self.lifetime.pid:
            lease.verified_exclusive = False
            lease.writes_blocked = True
            raise SessionOwnershipError('launched process lifetime/COM PID no longer matches')
        if documents:
            try:
                # Retry racy startup enumeration before poisoning the lease.
                # Default blanks (零件N / PartN) are adopted and closed here.
                titles = set(prepare_owned_inventory(lease, self.app, self.list_titles))
            except Exception as exc:
                normalized = normalize_com_disconnect(exc)
                if normalized is not None and self.rebind_owned_pid(lease):
                    try:
                        titles = set(prepare_owned_inventory(lease, self.app, self.list_titles))
                        exc = None
                        normalized = None
                    except Exception as again:
                        exc = again
                        normalized = normalize_com_disconnect(again)
                if exc is not None:
                    lease.writes_blocked = True
                    if normalized is not None:
                        lease.verified_exclusive = False
                        lease.disconnected = True
                        raise normalized from exc
                    raise SessionOwnershipError('document inventory unavailable; refusing writes') from exc
            foreign = titles - set(lease.owned_docs)
            if foreign:
                lease.foreign_titles.update(foreign)
                lease.verified_exclusive = False
                lease.writes_blocked = True
                raise SessionOwnershipError('unowned documents appeared in task process')

    def reconnect(self, lease):
        require_model_write(lease)
        self.validate(lease)
        return self.app, True  # This exact application was created by this task.

    def evidence(self):
        # Issue #19 S5: the process exit code is the acceptance signal for
        # teardown. poll() is None while the process is still exiting; a
        # code of 0 is required for "stable exit", 139 / 0xC0000005 (-1073741819)
        # is the known teardown-crash class. pending_windows_validation.
        return {'ownership': 'spawned_pid_and_live_handle', 'pid': self.lifetime.pid,
                'image': self.lifetime.executable, 'attached_existing': False,
                'native_verification': 'session_only_not_cad_acceptance',
                'cleanup_status': self.cleanup_status, 'cleanup_error': self.cleanup_error,
                'cleanup_disconnect': self.cleanup_disconnect,
                'cleanup_exit_code': self.lifetime.process.poll(),
                'keepalive_policy': 'close_doc_only_keep_alive_exit_not_required',
                'exit_poll_seconds': DEFAULT_EXIT_POLL_SECONDS,
                'anchor_created': self.anchor_created, 'anchor_closed': self.anchor_closed,
                'keepalive_verified': self.keepalive_verified}


def bind_spawned(lifetime, candidate, read_pid, list_titles, *, timeout=90, pump=None,
        rediscover=None):
    """Injectable proof logic; must run under the real task STA/OS writer lock."""
    lease = current_lease()
    if lease is None or not on_task_sta():
        raise SessionOwnershipError('owned launcher must run on task STA')
    if lease.shared_com_bound or lease.native_launch is not None or lease.writes_blocked or lease.poisoned:
        raise SessionOwnershipError('lease already bound/blocked; use a fresh CLI process')
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if lifetime.probe(lifetime.pid) is None:
            raise SessionOwnershipError('launched process exited or forwarded to an existing instance')
        try:
            app = candidate(lifetime.pid)
            matches = app is not None and read_pid(app) == lifetime.pid
        except Exception:
            matches = False
        if matches:
            # User documents are a hard failure. Startup blanks of this PID are
            # adopted and closed; a racy empty title is retried, not a claim miss.
            titles = prepare_owned_inventory(lease, app, list_titles)
            unowned = [title for title in titles if title not in lease.owned_docs]
            if unowned:
                raise SessionOwnershipError('new process contains unowned documents; no writes allowed')
            binding = OwnedBinding(lifetime, app, read_pid, list_titles)
            binding.rediscover = rediscover
            lease.attached_existing = False
            lease.created_by_task = True
            lease.shared_com_bound = True
            lease.foreign_titles_known = True
            lease.foreign_titles = set()
            lease.observed_pid = read_pid(app)
            lease.note_bound_application(app)
            lease.list_open_titles = list_titles
            if not claim_spawned_process(lifetime.pid, lifetime.probe, lease=lease):
                raise SessionOwnershipError('spawn/PID/image/document proof failed')
            lease.native_launch = binding
            lease.keep_application_open = True
            require_model_write(lease)
            return binding
        if pump:
            pump()
        time.sleep(.1)
    raise SessionOwnershipError(f'COM registration did not match spawned PID {lifetime.pid}; process left untouched')


@contextmanager
def owned_solidworks(executable, *, timeout=90):
    if sys.platform != 'win32':
        raise RuntimeError('owned SolidWorks launcher requires Windows')
    if not on_task_sta():
        raise SessionOwnershipError('start owned SolidWorks inside run_on_task_sta')
    lease = current_lease()
    if lease.shared_com_bound or lease.native_launch_attempt is not None or lease.writes_blocked or lease.poisoned:
        raise SessionOwnershipError('fresh task lease required before starting another process')
    path = Path(executable).expanduser().resolve()
    if not path.is_file() or path.name.casefold() != 'sldworks.exe':
        raise ValueError('provide the installed SLDWORKS.exe absolute path')
    import pythoncom
    from solidworks_generator import _list_open_document_titles
    lifetime = WindowsProcessLifetime(path)
    lease.native_launch_attempt = lifetime  # Keep the lifetime handle even on failed proof.
    try:
        binding = bind_spawned(lifetime, _native_candidate, _read_pid,
            _list_open_document_titles, timeout=timeout, pump=pythoncom.PumpWaitingMessages,
            rediscover=_native_candidate)
    except Exception as exc:
        lease.writes_blocked = True
        raise SessionOwnershipError(f"spawned PID {lifetime.pid} is unproven and left open: {exc}") from exc
    body_failed = False
    try:
        yield binding
    except BaseException:
        body_failed = True
        raise
    finally:
        # CloseDoc only. finish_owned_session does not call ExitApp. A disconnect
        # after a saved part is a warning, not a failed session.
        from owned_document_lifetime import finish_owned_session, release_closed_session_references
        finish_owned_session(lease, binding)
        release_closed_session_references(lease, binding)
        # A part already on disk must survive a dead GetProcessID in this finally.
        # Raising here discards run_plan's result and the CLI exits 1.
        if binding.cleanup_error and getattr(lease, "generation_saved", False):
            marker = str(binding.cleanup_error)
            folded = marker.casefold()
            if (
                binding.cleanup_status == "saved_com_disconnected_after_generation"
                or "没有连接到服务器" in marker
                or "-2147220995" in marker
                or "objnotconnected" in folded
                or "disconnected" in folded
                or "com_error" in folded
                or "ComSessionDisconnected" in marker
            ):
                binding.cleanup_disconnect = binding.cleanup_disconnect or marker
                binding.cleanup_error = None
                binding.cleanup_status = "saved_com_disconnected_after_generation"
                import logging
                logging.getLogger(__name__).warning(
                    "saved part kept after cleanup GetProcessID disconnect: %s",
                    binding.cleanup_disconnect,
                )
        if binding.cleanup_error and not body_failed:
            import logging
            logging.getLogger(__name__).error(
                'owned cleanup requires review: %s', binding.cleanup_error)
            error = SessionOwnershipError(
                'owned session cleanup failed: ' + binding.cleanup_error)
            error.native_session_evidence = binding.evidence()
            raise error

