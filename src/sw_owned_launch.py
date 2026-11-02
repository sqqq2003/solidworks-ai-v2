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
    DEFAULT_EXIT_POLL_SECONDS, adopt_leased_reference_documents, prepare_owned_inventory,
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
    # Never use the user's globally active window for a newly launched task.
    expected = f'solidworks_pid_{int(pid)}'
    rot = pythoncom.GetRunningObjectTable()
    for count, moniker in enumerate(rot.EnumRunning()):
        if count >= 4096:
            break
        try:
            name = moniker.GetDisplayName(pythoncom.CreateBindCtx(0), None).casefold()
            if name.lstrip('!') != expected:
                continue
            # ROT returns IUnknown. Query IDispatch before wrapping; otherwise
            # pywin32 calls GetTypeInfo on PyIUnknown and silently misses every
            # secondary instance whenever GetActiveObject points at another PID.
            dispatch = rot.GetObject(moniker).QueryInterface(pythoncom.IID_IDispatch)
            app = win32com.client.Dispatch(dispatch)
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

    def rebind_for_inventory(self, lease):
        """Rediscover this task's PID after a document-walk disconnect.

        Does not consume the one-shot GetProcessID rebind and does not ExitApp.
        The caller limits how many times a single listing may ask.
        """
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
            from sw_session import InventoryWalkDisconnected

            def _rebind_inventory():
                if self.rebind_for_inventory(lease):
                    return self.app
                return None

            try:
                # Retry racy startup enumeration before poisoning the lease.
                # Default blanks (零件N / PartN) are adopted and closed here.
                # A transient disconnect mid-walk rebinds this PID and rewalks.
                titles = set(prepare_owned_inventory(
                    lease, self.app, self.list_titles, rebind=_rebind_inventory,
                ))
                # Referenced parts/drawings loaded by an owned model are part of
                # this task. A document that model does not reference stays foreign.
                if titles - set(lease.owned_docs) and lease.owned_docs:
                    adopt_leased_reference_documents(lease, self.app)
            except Exception as exc:
                from part_verification import is_member_not_found
                normalized = normalize_com_disconnect(exc)
                lease.writes_blocked = True
                if normalized is not None or is_member_not_found(exc):
                    lease.verified_exclusive = False
                    lease.disconnected = True
                    if isinstance(exc, InventoryWalkDisconnected):
                        raise
                    raise InventoryWalkDisconnected(
                        "document inventory walk disconnected during GetNext; "
                        "writes refused; ExitApp was not called"
                    ) from exc
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
        return {'instance_mode':'new_process_alongside_existing', 'connection_policy':'spawned_pid_rot_only',
                'ownership': 'spawned_pid_and_live_handle', 'pid': self.lifetime.pid,
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


def suppress_saved_cleanup_error(binding, lease) -> bool:
    """Clear a post-save cleanup error so the context does not discard the path.

    Foreign documents still fail. A cleared error is ``partial_com_disconnect``
    unless the disconnect status is already the sheet-metal saved name.
    ExitApp is not called.
    """
    from owned_document_lifetime import cleanup_mentions_foreign_documents

    if not getattr(binding, "cleanup_error", None) or not getattr(lease, "generation_saved", False):
        return False
    if cleanup_mentions_foreign_documents(binding.cleanup_error):
        return False
    marker = str(binding.cleanup_error)
    folded = marker.casefold()
    partial = (
        binding.cleanup_status in {
            "saved_com_disconnected_after_generation",
            "partial_com_disconnect",
        }
        or "没有连接到服务器" in marker
        or "-2147220995" in marker
        or "objnotconnected" in folded
        or "disconnected" in folded
        or "com_error" in folded
        or "ComSessionDisconnected" in marker
        or "inventory unavailable" in folded
        or "document enumeration failed" in folded
        or "partial_com_disconnect" in folded
    )
    if not partial:
        return False
    binding.cleanup_disconnect = binding.cleanup_disconnect or marker
    binding.cleanup_error = None
    if binding.cleanup_status != "saved_com_disconnected_after_generation":
        binding.cleanup_status = "partial_com_disconnect"
    if getattr(lease, "post_save_outcome", None) is None:
        lease.post_save_outcome = "partial_com_disconnect"
    return True


@contextmanager
def owned_solidworks(executable, *, timeout=90):
    """Spawn a task-owned SLDWORKS beside any existing instance.

    Native modeling acceptance does not use this. That runner attaches to one
    existing process and must not start another one.
    """
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
        # A part already on disk must survive a dead GetProcessID or a failed
        # inventory in this finally. Raising here discards the result and the
        # CLI exits 1.
        if suppress_saved_cleanup_error(binding, lease):
            import logging
            logging.getLogger(__name__).warning(
                "saved part kept after cleanup/inventory COM failure: %s",
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


# Query-limited access only. This handle cannot terminate the process.
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


class QueryOnlyProcess:
    """Retained query handle for an existing PID. No terminate right is requested."""

    def __init__(self, pid):
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.GetExitCodeProcess.restype = wintypes.BOOL
        handle = kernel.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not handle:
            raise OSError(ctypes.get_last_error(), 'cannot open SLDWORKS for query')
        self._kernel = kernel
        self._handle = handle
        self._closed = False

    def poll(self):
        if self._closed:
            return None
        import ctypes
        from ctypes import wintypes
        code = wintypes.DWORD()
        if not self._kernel.GetExitCodeProcess(int(self._handle), ctypes.byref(code)):
            return None
        if int(code.value) == 259:  # STILL_ACTIVE
            return None
        return int(code.value)

    def close(self):
        if self._closed:
            return
        self._kernel.CloseHandle(int(self._handle))
        self._closed = True


class QueryProcessLifetime:
    """Existing SLDWORKS PID kept only so its image can be rechecked."""

    def __init__(self, pid, executable):
        self.pid = int(pid)
        self.executable = str(executable)
        self.process = QueryOnlyProcess(self.pid)

    def probe(self, pid):
        if int(pid) != self.pid or self.process.poll() is not None:
            return None
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
            return None
        image = buffer.value
        if os.path.normcase(os.path.realpath(image)) != os.path.normcase(os.path.realpath(self.executable)):
            raise SessionOwnershipError('attached process image differs from requested executable')
        return ProcessProbeInfo(self.pid, True, image)

    def close(self):
        self.process.close()


def _open_query_lifetime(pid, executable):
    return QueryProcessLifetime(pid, executable)


def _snapshot_sldworks_pids():
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    TH32CS_SNAPPROCESS = 0x00000002
    invalid = ctypes.c_void_p(-1).value

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ('dwSize', wintypes.DWORD),
            ('cntUsage', wintypes.DWORD),
            ('th32ProcessID', wintypes.DWORD),
            ('th32DefaultHeapID', ctypes.c_size_t),
            ('th32ModuleID', wintypes.DWORD),
            ('cntThreads', wintypes.DWORD),
            ('th32ParentProcessID', wintypes.DWORD),
            ('pcPriClassBase', wintypes.LONG),
            ('dwFlags', wintypes.DWORD),
            ('szExeFile', wintypes.WCHAR * 260),
        ]

    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel.Process32FirstW.restype = wintypes.BOOL
    kernel.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel.Process32NextW.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    snap = kernel.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snap or snap == invalid:
        raise OSError(ctypes.get_last_error(), 'cannot list processes')
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        pids = []
        ok = kernel.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            if str(entry.szExeFile).casefold() == 'sldworks.exe':
                pids.append(int(entry.th32ProcessID))
            ok = kernel.Process32NextW(snap, ctypes.byref(entry))
        return pids
    finally:
        kernel.CloseHandle(snap)


def _query_process_image(pid):
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    query = kernel.QueryFullProcessImageNameW
    query.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                      ctypes.POINTER(wintypes.DWORD)]
    query.restype = wintypes.BOOL
    handle = kernel.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not handle:
        return None
    try:
        size = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not query(handle, 0, buffer, ctypes.byref(size)):
            return None
        return buffer.value
    finally:
        kernel.CloseHandle(handle)


def _matching_sldworks_pids(executable):
    """PIDs whose image is exactly ``executable``. Read-only; does not signal them."""
    wanted = os.path.normcase(os.path.realpath(str(executable)))
    matched = []
    for pid in _snapshot_sldworks_pids():
        image = _query_process_image(pid)
        if image and os.path.normcase(os.path.realpath(image)) == wanted:
            matched.append(int(pid))
    return matched


def _discover_attached(pid, *, get_active=None):
    """Find the COM object for one existing PID. Never starts SLDWORKS."""
    app = _native_candidate(pid)
    if app is not None:
        return app
    if get_active is None:
        import win32com.client

        def get_active():
            return win32com.client.GetActiveObject('SldWorks.Application')
    try:
        active = get_active()
    except Exception:
        return None
    try:
        if _read_pid(active) == int(pid):
            return active
    except Exception:
        return None
    return None


def _clear_attached_documents(app, list_titles):
    """CloseDoc every document already open on the attached instance.

    Qile3: a foreign default assembly such as 装配体1 makes reuse report
    unowned documents. Close those documents before any modeling write.
    ExitApp is not called. UserControl is set first so the last CloseDoc
    does not quit SolidWorks.
    """
    try:
        app.UserControl = True
    except Exception:
        pass
    titles = [str(title) for title in (list_titles(app) or []) if str(title).strip()]
    closed = []
    for title in titles:
        app.CloseDoc(title)
        closed.append(title)
    remaining = [str(title) for title in (list_titles(app) or []) if str(title).strip()]
    return closed, remaining


class AttachedBinding(OwnedBinding):
    """One existing SLDWORKS. Open documents are CloseDoc'd before writes."""

    preserve_foreign_documents = True

    def __init__(self, lifetime, app, read_pid, list_titles):
        super().__init__(lifetime, app, read_pid, list_titles)
        self.closed_before_write = []

    def validate(self, lease, *, documents=True):
        from sw_session import normalize_com_disconnect
        image_ok, com_pid = self._read_connection_or_rebind(lease)
        if not image_ok or com_pid != self.lifetime.pid:
            lease.verified_exclusive = False
            lease.writes_blocked = True
            raise SessionOwnershipError('attached process lifetime/COM PID no longer matches')
        lease.observed_pid = int(com_pid)
        if documents:
            from sw_session import InventoryWalkDisconnected
            from owned_document_lifetime import read_owned_inventory

            def _rebind_inventory():
                if self.rebind_for_inventory(lease):
                    return self.app
                return None

            try:
                titles = set(read_owned_inventory(
                    self.list_titles, self.app, rebind=_rebind_inventory))
            except Exception as exc:
                from part_verification import is_member_not_found
                normalized = normalize_com_disconnect(exc)
                lease.writes_blocked = True
                if normalized is not None or is_member_not_found(exc):
                    lease.verified_exclusive = False
                    lease.disconnected = True
                    if isinstance(exc, InventoryWalkDisconnected):
                        raise
                    raise InventoryWalkDisconnected(
                        "document inventory walk disconnected during GetNext; "
                        "writes refused; ExitApp was not called"
                    ) from exc
                raise SessionOwnershipError('document inventory unavailable; refusing writes') from exc
            unknown = titles - set(lease.owned_docs) - set(lease.foreign_titles)
            if unknown:
                # Remember them so cleanup does not CloseDoc a document this task
                # did not create. Writes stop.
                lease.foreign_titles.update(unknown)
                lease.verified_exclusive = False
                lease.writes_blocked = True
                raise SessionOwnershipError(
                    'new documents appeared in the attached SolidWorks process; '
                    'left open and not closed: ' + ', '.join(sorted(unknown)))
        if not lease.prove_attached_reuse(self.lifetime.pid, self.lifetime.probe):
            lease.writes_blocked = True
            raise SessionOwnershipError('attached reuse proof failed')

    def reconnect(self, lease):
        require_model_write(lease)
        return self.app, False

    def evidence(self):
        from ql5050px.com_selection import callout_status
        code = None
        process = getattr(self.lifetime, 'process', None)
        if process is not None:
            code = process.poll()
        return {
            'instance_mode': 'attach_existing_sldworks',
            'connection_policy': 'existing_pid_query_handle_only',
            'ownership': 'attached_pid_and_query_handle',
            'pid': self.lifetime.pid,
            'image': self.lifetime.executable,
            'attached_existing': True,
            'spawned': False,
            'spawn_alongside': False,
            'close_doc_only': True,
            'exit_app': False,
            'process_killed': False,
            'native_verification': 'session_only_not_cad_acceptance',
            'cleanup_status': self.cleanup_status,
            'cleanup_error': self.cleanup_error,
            'cleanup_disconnect': self.cleanup_disconnect,
            'cleanup_exit_code': code,
            'keepalive_policy': 'close_doc_only_keep_alive_exit_not_required',
            'anchor_created': self.anchor_created,
            'anchor_closed': self.anchor_closed,
            'keepalive_verified': self.keepalive_verified,
            'callout': callout_status(),
            'closed_before_write': list(self.closed_before_write),
        }


def bind_attached(lifetime, discover, read_pid, list_titles, *, timeout=30, pump=None):
    """Bind one existing PID. Must run on the task STA. Does not start SLDWORKS."""
    lease = current_lease()
    if lease is None or not on_task_sta():
        raise SessionOwnershipError('attached launcher must run on task STA')
    if lease.shared_com_bound or lease.native_launch is not None or lease.writes_blocked or lease.poisoned:
        raise SessionOwnershipError('lease already bound/blocked; use a fresh CLI process')
    lease.close_doc_only = True
    lease.reuse_attached = True
    deadline = time.monotonic() + timeout
    app = None
    while time.monotonic() < deadline:
        if lifetime.probe(lifetime.pid) is None:
            raise SessionOwnershipError(
                'existing SLDWORKS exited or its image no longer matches; not starting a replacement')
        try:
            found = discover(lifetime.pid)
            matches = found is not None and read_pid(found) == lifetime.pid
        except Exception:
            matches = False
        if matches:
            app = found
            break
        if pump:
            pump()
        time.sleep(.1)
    if app is None:
        raise SessionOwnershipError(
            f'COM did not expose existing PID {lifetime.pid}; process left running; not starting another')
    binding = AttachedBinding(lifetime, app, read_pid, list_titles)
    binding.rediscover = discover
    try:
        closed, remaining = _clear_attached_documents(app, list_titles)
    except Exception as exc:
        raise SessionOwnershipError(
            'CloseDoc failed while clearing the attached session; '
            'ExitApp was not called: ' + str(exc)) from exc
    if remaining:
        raise SessionOwnershipError(
            'CloseDoc did not clear the attached session; left open and '
            'ExitApp was not called: ' + ', '.join(remaining))
    binding.closed_before_write = closed
    lease.attached_existing = True
    lease.created_by_task = False
    lease.spawn_claimed = False
    lease.close_doc_only = True
    lease.reuse_attached = True
    lease.shared_com_bound = True
    lease.foreign_titles = set()
    lease.foreign_titles_known = True
    lease.observed_pid = read_pid(app)
    lease.note_bound_application(app)
    lease.list_open_titles = list_titles
    lease.keep_application_open = True
    if not lease.prove_attached_reuse(lifetime.pid, lifetime.probe):
        raise SessionOwnershipError('attached PID/image proof failed; no writes and no new process')
    lease.native_launch = binding
    require_model_write(lease)
    return binding


def _finish_attached(lease, binding, lifetime, *, body_failed):
    from owned_document_lifetime import finish_owned_session, release_closed_session_references
    try:
        finish_owned_session(lease, binding)
        release_closed_session_references(lease, binding)
        if suppress_saved_cleanup_error(binding, lease):
            import logging
            logging.getLogger(__name__).warning(
                'saved part kept after cleanup/inventory COM failure: %s',
                binding.cleanup_disconnect,
            )
        if binding.cleanup_error and not body_failed:
            import logging
            logging.getLogger(__name__).error(
                'attached cleanup requires review: %s', binding.cleanup_error)
            error = SessionOwnershipError(
                'attached session cleanup failed: ' + binding.cleanup_error)
            error.native_session_evidence = binding.evidence()
            raise error
    finally:
        lifetime.close()


@contextmanager
def attached_solidworks(executable, *, timeout=30):
    """Reuse one running SLDWORKS whose image is ``executable``.

    CloseDoc documents already open (including a default 装配体1) before
    modeling writes, then CloseDoc only what this task creates afterwards.
    Does not start SLDWORKS, call ExitApp, or terminate the process.
    Zero matches and more than one match both refuse.
    """
    if sys.platform != 'win32':
        raise RuntimeError('attached SolidWorks launcher requires Windows')
    if not on_task_sta():
        raise SessionOwnershipError('attach to SolidWorks inside run_on_task_sta')
    lease = current_lease()
    if lease.shared_com_bound or lease.native_launch_attempt is not None or lease.writes_blocked or lease.poisoned:
        raise SessionOwnershipError('fresh task lease required before attaching to SolidWorks')
    lease.close_doc_only = True
    lease.reuse_attached = True
    path = Path(executable).expanduser().resolve()
    if not path.is_file() or path.name.casefold() != 'sldworks.exe':
        raise ValueError('provide the installed SLDWORKS.exe absolute path')
    pids = _matching_sldworks_pids(path)
    if not pids:
        raise SessionOwnershipError(
            'no running SLDWORKS matches the requested executable; '
            'acceptance attaches to one existing instance and will not start another')
    if len(pids) != 1:
        raise SessionOwnershipError(
            'multiple SLDWORKS processes match the requested executable ('
            + ', '.join(str(pid) for pid in pids)
            + '); refusing to guess or start another')
    lifetime = _open_query_lifetime(pids[0], path)
    lease.native_launch_attempt = lifetime
    import pythoncom
    from solidworks_generator import _list_open_document_titles
    try:
        binding = bind_attached(
            lifetime, _discover_attached, _read_pid, _list_open_document_titles,
            timeout=timeout, pump=pythoncom.PumpWaitingMessages)
    except Exception as exc:
        lease.writes_blocked = True
        lifetime.close()
        raise SessionOwnershipError(
            f'existing PID {lifetime.pid} was not attached; it was left running: {exc}') from exc
    body_failed = False
    try:
        yield binding
    except BaseException:
        body_failed = True
        raise
    finally:
        _finish_attached(lease, binding, lifetime, body_failed=body_failed)

