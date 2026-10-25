"""Task-scoped SolidWorks session boundary.

Dangerous operations run only when this process can prove it owns an
exclusive session: ExitApp, CloseAllDocuments, closing a document this task
did not create, and terminating a process. The watchdog thread never calls
COM. Nothing in this module force-kills by process name.

COM activation (GetActiveObject / Dispatch) is not proof of ownership. Exclusive
ownership requires a process this task spawned, a matching observed PID, a live
probe of that exact PID, and zero foreign documents at connect.

One cross-process writer lock (a Windows named mutex, or a file lock elsewhere)
covers run_on_task_sta. A timed-out waiter marks the lease so the STA cannot
continue saving. reset_for_tests is test isolation only and is not that path.
"""

from __future__ import annotations

import logging
import os
import queue
import signal
import sys
import tempfile
import threading
import time
import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

# Outer bound for one task call. Bend-insert watchdog abandon wakes the waiter
# earlier. This bound exists so removing process kill cannot wait forever.
SW_SESSION_CALL_TIMEOUT_SEC = 600.0

_DISCONNECT_HRESULTS = frozenset(
    {
        -2147417848,  # RPC_E_DISCONNECTED
        -2147023174,  # RPC_S_SERVER_UNAVAILABLE
        -2147418111,  # RPC_E_CALL_REJECTED
        -2147467261,  # E_POINTER
        -2147220995,  # CO_E_OBJNOTCONNECTED (0x800401FD)
    }
)


class SessionOwnershipError(RuntimeError):
    """Dangerous SolidWorks operation refused because ownership is not proven."""


class ComSessionDisconnected(SessionOwnershipError):
    """Owned COM server dropped. This is not a modeling pass and does not call ExitApp."""

    status = "com_disconnected"
    native_acceptance = "pending_windows_validation"


class SwCallTimeoutError(TimeoutError):
    """A SolidWorks call exceeded its deadline.

    The waiting thread raises this and returns. The watchdog does not call COM.
    An unproven session is not force-killed and is not sent ExitApp.
    """


@dataclass(frozen=True)
class ProcessProbeInfo:
    pid: int
    alive: bool
    image: str


Probe = Callable[[int], ProcessProbeInfo | None]
Killer = Callable[[int], None]
PidReader = Callable[[Any], int | None]


@dataclass
class OwnedDocument:
    title: str
    handle_id: int | None = None


@dataclass
class SessionLease:
    task_id: str
    created_by_task: bool = False
    attached_existing: bool = False
    spawn_claimed: bool = False
    spawned_pid: int | None = None
    observed_pid: int | None = None
    foreign_titles: set[str] = field(default_factory=set)
    foreign_titles_known: bool = False
    owned_docs: dict[str, OwnedDocument] = field(default_factory=dict)
    com_thread_id: int | None = None
    com_initialized: bool = False
    shared_com_bound: bool = False
    verified_exclusive: bool = False
    poisoned: bool = False
    timed_out: bool = False
    writes_blocked: bool = False
    disconnected: bool = False
    terminate_sent: bool = False
    app_handle_id: int | None = None
    app_for_recycle: Any = None
    bound_app_ids: set[int] = field(default_factory=set)
    list_open_titles: Callable[[Any], list[str]] | None = None
    probe: Probe | None = None
    native_launch: Any = None
    native_launch_attempt: Any = None
    keep_application_open: bool = False
    generation_saved: bool = False
    killer: Killer | None = None
    abandon: threading.Event = field(default_factory=threading.Event)
    watchdog_thread_ids: list[int] = field(default_factory=list)

    def bind_com_thread(self, thread_id: int) -> None:
        self.com_thread_id = int(thread_id)

    def note_bound_application(self, app: Any) -> None:
        """Remember a COM wrapper for this same session.

        Typed wrappers do not share the raw application's id. Teardown still
        has to accept the wrapper this task actually holds, and reject any
        other application object.
        """

        if app is None:
            return
        self.bound_app_ids.add(id(app))
        if self.app_for_recycle is None:
            self.app_for_recycle = app
        if self.app_handle_id is None:
            self.app_handle_id = id(app)

    def note_owned_document(self, title: str, handle_id: int | None = None) -> None:
        title = str(title)
        if title in self.foreign_titles:
            raise SessionOwnershipError(
                f"refusing to mark user document {title!r} as owned by this task"
            )
        self.owned_docs[title] = OwnedDocument(title, handle_id)

    def rename_owned(self, old: str, new: str) -> None:
        old, new = str(old), str(new)
        if new in self.foreign_titles:
            raise SessionOwnershipError(
                f"refusing to retarget an owned document onto user document {new!r}"
            )
        doc = self.owned_docs.pop(old, None)
        if doc is None:
            raise SessionOwnershipError(f"cannot rename unowned document {old!r}")
        doc.title = new
        self.owned_docs[new] = doc

    def is_owned_title(self, title: str | None) -> bool:
        return title is not None and str(title) in self.owned_docs

    def request_abandon(self, reason: str) -> None:
        self.timed_out = True
        self.writes_blocked = True
        self.abandon.set()
        logger.error(
            "task %s: %s. Watchdog is not calling COM.",
            self.task_id,
            reason,
        )

    def prove_exclusive(self, pid: int, probe: Probe) -> bool:
        """Return True only for a spawned PID this task can still prove.

        GetActiveObject / Dispatch alone never satisfies this. A foreign
        document, a failed enumeration, a dead PID, or a non-SolidWorks image
        keeps the session unproven.
        """

        self.verified_exclusive = False
        self.probe = probe
        if not self.spawn_claimed or self.attached_existing or self.poisoned:
            return False
        if not self.foreign_titles_known or self.foreign_titles:
            return False
        if self.spawned_pid is None or int(self.spawned_pid) != int(pid):
            return False
        if self.observed_pid is None or int(self.observed_pid) != int(pid):
            return False
        info = probe(int(pid))
        if info is None or not info.alive or int(info.pid) != int(pid):
            return False
        if not _is_sldworks_image(info.image):
            return False
        self.spawned_pid = int(pid)
        self.verified_exclusive = True
        return True


_CURRENT_LEASE: ContextVar[SessionLease | None] = ContextVar(
    "sw_current_lease", default=None
)
_worker_lock = threading.Lock()
_worker: "SwTaskWorker | None" = None
_process_poisoned = False
_WRITER_MUTEX_NAME = "Local\\A01SolidWorksWriter"
_WRITER_LOCK_FILE = Path(tempfile.gettempdir()) / "a01-solidworks-writer.lock"


def current_lease() -> SessionLease | None:
    return _CURRENT_LEASE.get()


def on_task_sta() -> bool:
    worker = _worker
    return (
        worker is not None
        and worker.sta_id is not None
        and threading.get_ident() == worker.sta_id
    )


def active_worker() -> "SwTaskWorker | None":
    return _worker


def worker_lock_locked() -> bool:
    return _worker_lock.locked()


class _Job:
    def __init__(self, fn: Callable, args: tuple, kwargs: dict) -> None:
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.done = threading.Event()
        self.result: Any = None
        self.error: BaseException | None = None

    def ok(self, result: Any) -> None:
        self.result = result
        self.done.set()

    def fail(self, error: BaseException) -> None:
        self.error = error
        self.done.set()


class SwTaskWorker:
    """One STA thread for this process. Callers wait outside that thread."""

    def __init__(self) -> None:
        self.lease = SessionLease(task_id=f"sw-task-{uuid.uuid4().hex[:12]}")
        self._queue: queue.Queue = queue.Queue()
        self.sta_id: int | None = None
        self.poisoned = False
        self._stop = False
        self._ready = threading.Event()
        self.pending_lock_token: int | None = None
        self._queued_this_call = False
        self._thread = threading.Thread(
            target=self._loop, name="sw-task-sta", daemon=True
        )
        self._thread.start()
        if not self._ready.wait(5):
            raise SessionOwnershipError("SolidWorks task STA worker failed to start")

    def _loop(self) -> None:
        self.sta_id = threading.get_ident()
        self.lease.bind_com_thread(self.sta_id)
        com = False
        pythoncom = None
        try:
            import pythoncom as pythoncom  # type: ignore

            pythoncom.CoInitialize()
            com = True
            self.lease.com_initialized = True
        except ImportError:
            self.lease.com_initialized = False
        except Exception:
            logger.debug("CoInitialize failed on task STA", exc_info=True)
            self.lease.com_initialized = False
        self._ready.set()
        while not self._stop:
            job = self._queue.get()
            if job is None:
                break
            lock_token = self.pending_lock_token
            if self.poisoned or self.lease.poisoned:
                self._release_writer_token(lock_token)
                job.fail(
                    SessionOwnershipError(
                        "Refusing SolidWorks call: the task worker is poisoned "
                        "after a timeout and will not recycle an unproven session."
                    )
                )
                continue
            token = _CURRENT_LEASE.set(self.lease)
            outcome: BaseException | None = None
            result: Any = None
            try:
                result = job.fn(*job.args, **job.kwargs)
            except BaseException as error:  # noqa: BLE001
                outcome = error
            finally:
                _CURRENT_LEASE.reset(token)
                # Unlock before waking the waiter so the next task cannot
                # overlap this one, and so a timed-out waiter is not the
                # thing that drops the lock early.
                self._release_writer_token(lock_token)
            if outcome is None:
                job.ok(result)
            else:
                job.fail(outcome)
        if com and pythoncom is not None:
            try:
                pythoncom.CoUninitialize()
            except Exception:
                logger.debug("CoUninitialize failed", exc_info=True)

    def call(
        self,
        fn: Callable,
        *args: Any,
        timeout: float,
        lock_token: int | None = None,
        **kwargs: Any,
    ) -> Any:
        self._queued_this_call = False
        if self.poisoned or self.lease.poisoned:
            raise SessionOwnershipError(
                "Refusing SolidWorks call: the task worker is poisoned and this "
                "task will not attach to or tear down an unproven session."
            )
        if self.sta_id is not None and threading.get_ident() == self.sta_id:
            return fn(*args, **kwargs)
        if lock_token is not None:
            self.pending_lock_token = lock_token
        self.lease.abandon.clear()
        self.lease.timed_out = False
        job = _Job(fn, args, kwargs)
        self._queue.put(job)
        self._queued_this_call = True
        deadline = time.monotonic() + float(timeout)
        while True:
            if job.done.is_set():
                break
            if self.lease.abandon.is_set() or time.monotonic() >= deadline:
                exclusive = self.lease.verified_exclusive
                if exclusive:
                    try:
                        terminate_owned_process(self.lease)
                    except SessionOwnershipError:
                        logger.error(
                            "exclusive session timed out; owned-pid terminate was refused"
                        )
                    except Exception:
                        logger.exception("owned-pid terminate failed during timeout")
                # The STA keeps the writer lock until the job returns. Further
                # saves are refused. reset_for_tests is not a recovery path.
                self.lease.writes_blocked = True
                self._poison("call timed out or the watchdog abandoned the wait")
                if exclusive:
                    detail = (
                        " An owned pid terminate was requested from outside the "
                        "STA. ExitApp was not called from the watchdog thread."
                    )
                else:
                    detail = (
                        " ExitApp, CloseAllDocuments, and process kill were refused "
                        "because this task cannot prove an exclusive session."
                    )
                raise SwCallTimeoutError(
                    "SolidWorks call timed out. The watchdog did not call COM." + detail
                )
            remaining = deadline - time.monotonic()
            job.done.wait(min(0.05, max(remaining, 0.0)))
        if job.error is not None:
            raise job.error
        return job.result

    def _poison(self, reason: str) -> None:
        global _process_poisoned
        self.poisoned = True
        self.lease.poisoned = True
        self.lease.writes_blocked = True
        self.lease.verified_exclusive = False
        _process_poisoned = True
        logger.error("task worker poisoned: %s", reason)

    def _release_writer_token(self, lock_token: int | None) -> None:
        if lock_token is None:
            return
        _WRITER_LOCK.release(lock_token)
        if self.pending_lock_token == lock_token:
            self.pending_lock_token = None

    def shutdown_idle(self) -> None:
        """Ask an idle worker to exit. Does not call SolidWorks."""

        self._stop = True
        self._queue.put(None)


def ensure_worker() -> SwTaskWorker:
    global _worker
    if _process_poisoned or (_worker is not None and _worker.poisoned):
        raise SessionOwnershipError(
            "Refusing a new SolidWorks session: a previous call timed out and "
            "this process will not attach to, recycle, or kill a session it "
            "cannot prove it owns."
        )
    if _worker is None:
        _worker = SwTaskWorker()
    return _worker


class _CrossProcessWriterLock:
    """One writer across processes.

    Windows uses a named mutex. Other platforms use an exclusive file lock.
    The acquiring thread is not the STA: an owner thread holds the OS object
    so a Windows mutex can still be released after the waiter has returned.
    """

    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._state = "free"
        self._epoch = 0
        self._held_token: int | None = None
        self._release_event: threading.Event | None = None
        self._owner: threading.Thread | None = None

    def acquire(self) -> int:
        with self._guard:
            if self._state != "free":
                raise SessionOwnershipError(
                    "another task holds the SolidWorks writer lock. "
                    "Refusing to enter run_on_task_sta."
                )
            self._state = "pending"
        release_event = threading.Event()
        ready = threading.Event()
        box: dict[str, Any] = {}

        def owner() -> None:
            try:
                box["resource"] = _os_writer_acquire_nonblocking()
                box["ok"] = box["resource"] is not None
            except Exception:
                logger.exception("cross-process SolidWorks writer lock failed closed")
                box["ok"] = False
            ready.set()
            if not box.get("ok"):
                return
            release_event.wait()
            try:
                _os_writer_release(box.get("resource"))
            except Exception:
                logger.exception("releasing the SolidWorks writer lock failed")

        thread = threading.Thread(target=owner, name="sw-writer-lock", daemon=True)
        thread.start()
        if not ready.wait(5):
            release_event.set()
            thread.join(timeout=1)
            with self._guard:
                if self._state == "pending":
                    self._state = "free"
            raise SessionOwnershipError(
                "SolidWorks writer lock did not start; refusing the task"
            )
        if not box.get("ok"):
            thread.join(timeout=1)
            with self._guard:
                if self._state == "pending":
                    self._state = "free"
            raise SessionOwnershipError(
                "another process holds the SolidWorks writer lock. "
                "Refusing to enter run_on_task_sta."
            )
        with self._guard:
            self._epoch += 1
            token = self._epoch
            self._held_token = token
            self._state = "held"
            self._release_event = release_event
            self._owner = thread
            return token

    def release(self, token: int | None = None, *, force: bool = False) -> None:
        with self._guard:
            if self._state != "held":
                if force and self._state == "pending":
                    self._state = "free"
                return
            if not force and token != self._held_token:
                return
            event = self._release_event
            thread = self._owner
            self._state = "free"
            self._held_token = None
            self._release_event = None
            self._owner = None
        if event is not None:
            event.set()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)


_WRITER_LOCK = _CrossProcessWriterLock()


def _os_writer_acquire_nonblocking() -> Any:
    if sys.platform == "win32":
        return _win_mutex_acquire()
    return _flock_acquire()


def _os_writer_release(resource: Any) -> None:
    if resource is None:
        return
    if sys.platform == "win32":
        _win_mutex_release(resource)
        return
    _flock_release(resource)


def _flock_acquire() -> Any:
    import fcntl

    _WRITER_LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    handle = open(_WRITER_LOCK_FILE, "a+b")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        return None
    return handle


def _flock_release(handle: Any) -> None:
    import fcntl

    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


def _win_mutex_acquire() -> Any:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.ReleaseMutex.argtypes = (wintypes.HANDLE,)
    kernel32.ReleaseMutex.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    handle = kernel32.CreateMutexW(None, False, _WRITER_MUTEX_NAME)
    if not handle:
        return None
    # WAIT_OBJECT_0 or WAIT_ABANDONED. A recursive initial owner is not used.
    result = int(kernel32.WaitForSingleObject(handle, 0))
    if result not in (0, 0x00000080):
        kernel32.CloseHandle(handle)
        return None
    return (kernel32, handle)


def _win_mutex_release(resource: Any) -> None:
    kernel32, handle = resource
    kernel32.ReleaseMutex(handle)
    kernel32.CloseHandle(handle)


def run_on_task_sta(fn: Callable, *, timeout: float, task_name: str = "sw-task") -> Any:
    """Run ``fn`` on the single task STA. The caller waits at most ``timeout``.

    A second caller in this process fails immediately. A second process fails
    on the OS writer lock. Neither attaches to the active session or closes
    that session's documents. On timeout the waiter returns and blocks further
    saves; it does not call reset_for_tests and it does not drop the writer
    lock while the STA job is still inside ``fn``.
    """

    if on_task_sta():
        return fn()
    acquired = _worker_lock.acquire(blocking=False)
    if not acquired:
        raise SessionOwnershipError(
            f"{task_name}: another task holds the SolidWorks worker. "
            "Refusing to attach, close documents, ExitApp, or kill that session."
        )
    token: int | None = None
    worker: SwTaskWorker | None = None
    try:
        token = _WRITER_LOCK.acquire()
        worker = ensure_worker()
        logger.info("running %s on task STA %s", task_name, worker.lease.task_id)
        try:
            return worker.call(fn, timeout=timeout, lock_token=token)
        except SwCallTimeoutError:
            global _process_poisoned
            _process_poisoned = True
            worker.poisoned = True
            worker.lease.poisoned = True
            worker.lease.writes_blocked = True
            worker.lease.verified_exclusive = False
            raise
    finally:
        _worker_lock.release()
        if token is not None and (worker is None or not worker._queued_this_call):
            _WRITER_LOCK.release(token)
            if worker is not None and worker.pending_lock_token == token:
                worker.pending_lock_token = None


def reset_for_tests() -> None:
    """Drop worker bookkeeping. Does not call COM or signal any process.

    Test isolation only. Production timeout recovery never calls this. The
    abandoned lease is marked writes-blocked before the OS writer lock is
    force-released, so a still-running STA cannot keep saving.
    """

    global _worker, _process_poisoned
    if _worker_lock.locked():
        raise RuntimeError("cannot reset while a task holds the worker lock")
    old = _worker
    if old is not None:
        old.lease.writes_blocked = True
        old.lease.verified_exclusive = False
        old.poisoned = True
        old._stop = True
        old._queue.put(None)
    _WRITER_LOCK.release(force=True)
    _worker = None
    _process_poisoned = False


def _is_sldworks_image(image: str) -> bool:
    name = (image or "").replace("\\", "/").rsplit("/", 1)[-1].casefold()
    return name in {"sldworks.exe", "sldworks"}


def connect_application(
    lease: SessionLease,
    *,
    get_active: Callable[[], Any],
    dispatch: Callable[[], Any],
    list_titles: Callable[[Any], list[str]],
    is_absent: Callable[[BaseException], bool],
    read_pid: PidReader | None = None,
) -> tuple[Any, bool]:
    """Attach or activate SolidWorks without treating that as ownership.

    Returns ``(app, created_by_task)``. ``created_by_task`` is true only when
    ``get_active`` raised an absent-instance error and ``dispatch`` returned.
    That is not exclusive ownership.
    """

    if lease.com_thread_id not in (None, threading.get_ident()):
        raise SessionOwnershipError(
            "refusing SolidWorks connect off the task STA thread"
        )
    if lease.com_thread_id is None:
        lease.bind_com_thread(threading.get_ident())
    try:
        app = get_active()
        attached = True
    except Exception as error:
        if not is_absent(error):
            raise
        app = dispatch()
        attached = False
    lease.attached_existing = attached
    lease.created_by_task = not attached
    lease.app_handle_id = id(app)
    lease.app_for_recycle = app
    lease.bound_app_ids.add(id(app))
    lease.list_open_titles = list_titles
    lease.shared_com_bound = True
    lease.verified_exclusive = False
    if read_pid is not None:
        try:
            observed = read_pid(app)
        except Exception:
            logger.error("SolidWorks PID read failed; ownership stays unproven", exc_info=True)
            observed = None
        if observed is not None:
            lease.observed_pid = int(observed)
    try:
        titles = list_titles(app)
    except Exception:
        logger.error(
            "could not enumerate SolidWorks documents; session ownership stays unproven"
        )
        lease.foreign_titles = set()
        lease.foreign_titles_known = False
        return app, lease.created_by_task
    lease.foreign_titles = {str(title) for title in (titles or []) if str(title)}
    lease.foreign_titles_known = True
    if (
        lease.spawn_claimed
        and lease.spawned_pid is not None
        and lease.probe is not None
        and lease.observed_pid == lease.spawned_pid
    ):
        lease.prove_exclusive(lease.spawned_pid, lease.probe)
    else:
        lease.verified_exclusive = False
    return app, lease.created_by_task


def claim_spawned_process(
    pid: int,
    probe: Probe,
    *,
    lease: SessionLease | None = None,
) -> bool:
    """Record a PID this task itself spawned. Does not launch SolidWorks."""

    lease = lease or current_lease()
    if lease is None:
        raise SessionOwnershipError(
            "no task lease; refusing to claim a SolidWorks process"
        )
    lease.spawn_claimed = True
    lease.spawned_pid = int(pid)
    lease.probe = probe
    if (
        lease.foreign_titles_known
        and not lease.attached_existing
        and lease.observed_pid == lease.spawned_pid
    ):
        return lease.prove_exclusive(pid, probe)
    lease.verified_exclusive = False
    return False


def _require_sta(lease: SessionLease) -> None:
    if lease.com_thread_id is None or threading.get_ident() != lease.com_thread_id:
        raise SessionOwnershipError(
            "refusing SolidWorks COM teardown from a thread that does not own the STA"
        )


def _application_is_bound(lease: SessionLease, app: Any) -> bool:
    if app is None:
        return False
    if lease.app_for_recycle is not None and app is lease.app_for_recycle:
        return True
    ident = id(app)
    if lease.app_handle_id is not None and ident == int(lease.app_handle_id):
        return True
    return ident in lease.bound_app_ids


def _require_bound_application(lease: SessionLease, app: Any, action: str) -> None:
    if _application_is_bound(lease, app):
        return
    raise SessionOwnershipError(
        f"refusing {action}: the application object is not the lease-bound "
        "SolidWorks session (app_handle_id / identity)"
    )


def _session_writes_blocked(lease: SessionLease) -> bool:
    return bool(
        lease.disconnected
        or lease.poisoned
        or lease.writes_blocked
        or lease.timed_out
        or lease.abandon.is_set()
    )


def require_model_write(lease: SessionLease | None = None) -> SessionLease:
    """Refuse a modeling write unless this task still holds an exclusive session.

    GetActiveObject or Dispatch by itself is not enough. A disconnected,
    abandoned, or timed-out lease cannot change automation mode, create or
    open a document, or save.
    """

    if lease is None:
        lease = current_lease()
    if lease is None:
        raise SessionOwnershipError(
            "refusing model write: no task lease. GetActiveObject/Dispatch is not exclusive ownership"
        )
    _require_sta(lease)
    worker = active_worker()
    if worker is None or worker.lease is not lease or not on_task_sta():
        raise SessionOwnershipError("refusing model write outside the serialized task worker")
    if _session_writes_blocked(lease):
        raise SessionOwnershipError(
            "refusing model write: the session is abandoned, disconnected, or writes are blocked"
        )
    if not lease.verified_exclusive or lease.spawned_pid is None:
        raise SessionOwnershipError(
            "refusing model write: GetActiveObject/Dispatch alone is not exclusive ownership"
        )
    if lease.native_launch is not None:
        lease.native_launch.validate(lease)
    return lease


def ensure_application_keepalive(lease: SessionLease, app: Any) -> None:
    """Prevent background SW from exiting on the last intermediate CloseDoc.

    UserControl=True makes this proved task-owned instance visible. It does
    not grant ownership; all PID, inventory, STA and write gates still apply.
    """
    if getattr(lease, "keep_application_open", False) is not True:
        return
    require_model_write(lease)
    _require_bound_application(lease, app, "UserControl keepalive")
    try:
        app.UserControl = True
        actual = getattr(app, "UserControl")
        actual = actual() if callable(actual) else actual
        if actual is not True:
            raise RuntimeError("UserControl readback did not confirm True")
    except Exception as error:
        lease.writes_blocked = True
        raise SessionOwnershipError("owned application keepalive could not be verified; CloseDoc refused") from error
    binding = getattr(lease, "native_launch", None)
    if binding is not None:
        binding.keepalive_verified = True
    logger.info("owned application keepalive verified: UserControl=True pid=%s", lease.spawned_pid)


def close_owned_document(lease: SessionLease, app: Any, title: str) -> None:
    _require_sta(lease)
    _require_bound_application(lease, app, "CloseDoc")
    if _session_writes_blocked(lease):
        raise SessionOwnershipError(
            "refusing CloseDoc: the session is abandoned, disconnected, or writes are blocked"
        )
    title = str(title)
    owned = lease.owned_docs.get(title)
    if title in lease.foreign_titles or owned is None:
        raise SessionOwnershipError(
            f"refusing to close document {title!r}: this task cannot prove it owns that document"
        )
    ensure_application_keepalive(lease, app)
    app.CloseDoc(title)
    # Drop the title and its handle only after CloseDoc returns. A replacement
    # opened later under the same title is not this registration.
    if lease.owned_docs.get(title) is owned:
        lease.owned_docs.pop(title, None)


def close_all_documents(lease: SessionLease, app: Any, open_titles: Any) -> None:
    """Close every open document only when every one of them is owned."""

    _require_sta(lease)
    _require_bound_application(lease, app, "CloseAllDocuments")
    if _session_writes_blocked(lease):
        raise SessionOwnershipError(
            "refusing CloseAllDocuments: the session is abandoned, disconnected, or writes are blocked"
        )
    if not lease.verified_exclusive:
        raise SessionOwnershipError(
            "refusing CloseAllDocuments: exclusive SolidWorks ownership is not proven"
        )
    titles = [str(title) for title in (open_titles or [])]
    foreign = [title for title in titles if title not in lease.owned_docs]
    if foreign:
        raise SessionOwnershipError(
            "refusing CloseAllDocuments while documents this task does not own are open: "
            + ", ".join(foreign)
        )
    ensure_application_keepalive(lease, app)
    app.CloseAllDocuments(True)


def _listed_open_titles(lease: SessionLease, app: Any) -> list[str]:
    if lease.list_open_titles is None:
        raise SessionOwnershipError(
            "refusing ExitApp: open documents cannot be listed, so a foreign document cannot be ruled out"
        )
    try:
        raw = lease.list_open_titles(app)
    except Exception as error:
        raise SessionOwnershipError(
            "refusing ExitApp: document enumeration failed"
        ) from error
    return [str(title) for title in (raw or []) if str(title)]


def exit_owned_application(lease: SessionLease, app: Any) -> None:
    _require_sta(lease)
    _require_bound_application(lease, app, "ExitApp")
    if lease.disconnected:
        raise SessionOwnershipError(
            "refusing ExitApp: the SolidWorks session is disconnected"
        )
    if _session_writes_blocked(lease):
        raise SessionOwnershipError(
            "refusing ExitApp: the session is abandoned or writes are blocked"
        )
    if not lease.verified_exclusive or lease.spawned_pid is None:
        raise SessionOwnershipError(
            "refusing ExitApp: this task cannot prove it owns an exclusive SolidWorks session"
        )
    open_titles = _listed_open_titles(lease, app)
    foreign = [title for title in open_titles if title not in lease.owned_docs]
    if foreign:
        raise SessionOwnershipError(
            "refusing ExitApp while documents this task does not own are open: "
            + ", ".join(foreign)
        )
    app.ExitApp()


def _exception_is_disconnect(error: BaseException | None) -> bool:
    if error is None:
        return False
    unsigned = {code & 0xFFFFFFFF for code in _DISCONNECT_HRESULTS}
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        args = getattr(current, "args", ())
        if args and isinstance(args[0], int):
            hr = args[0]
            if hr in _DISCONNECT_HRESULTS or (hr & 0xFFFFFFFF) in unsigned:
                return True
        text = str(current)
        folded = text.casefold()
        if (
            "断开连接" in text
            or "没有连接到服务器" in text
            or "not connected to server" in folded
            or "disconnected" in folded
        ):
            return True
        nested = args[0] if args and isinstance(args[0], BaseException) else None
        if nested is not None and id(nested) not in seen:
            current = nested
            continue
        current = current.__cause__ or current.__context__
    return False


def is_com_server_disconnect(error: BaseException | None) -> bool:
    """True for RPC disconnects and CO_E_OBJNOTCONNECTED after a dead proxy."""
    return _exception_is_disconnect(error)


def release_task_documents(
    lease: SessionLease | None,
    app: Any,
    *,
    title: str | None,
    close: bool,
    resolve_title: Callable[[], Any] | None = None,
) -> None:
    """Close one owned document. ExitApp only when the session is exclusive.

    A COM disconnect is recorded and does not escalate to ExitApp or to a
    process kill. ExitApp on a disconnected proxy can hang, so it is skipped.
    """

    if lease is None or app is None:
        logger.error("no lease or application; skipping SolidWorks teardown")
        return
    _require_sta(lease)
    active_title = str(title) if title else None
    if (
        close
        and active_title
        and resolve_title is not None
        and lease.is_owned_title(active_title)
    ):
        try:
            updated = resolve_title()
        except Exception as error:
            if _exception_is_disconnect(error):
                lease.disconnected = True
                logger.error(
                    "COM disconnect while reading the document title; "
                    "not calling ExitApp and not killing the process"
                )
                return
            logger.exception("could not refresh the owned document title")
            updated = None
        if updated:
            updated = str(updated)
            if updated in lease.foreign_titles:
                logger.error("refusing to close user document %r after save", updated)
                active_title = None
            else:
                try:
                    lease.rename_owned(active_title, updated)
                    active_title = updated
                except SessionOwnershipError:
                    logger.error("refusing to retarget close onto %r", updated)
                    active_title = None
    if close and active_title:
        try:
            from owned_document_lifetime import is_startup_blank_title
            if (
                is_startup_blank_title(active_title)
                and active_title not in lease.owned_docs
                and active_title not in lease.foreign_titles
                and lease.verified_exclusive
                and lease.spawned_pid is not None
            ):
                lease.note_owned_document(str(active_title).strip())
                active_title = str(active_title).strip()
            close_owned_document(lease, app, active_title)
        except SessionOwnershipError as error:
            logger.error("skipped close of unowned document %r: %s", active_title, error)
        except Exception as error:
            if _exception_is_disconnect(error):
                lease.disconnected = True
                logger.error(
                    "COM disconnect closing owned document %r; "
                    "not calling ExitApp and not force-killing SolidWorks",
                    active_title,
                )
                return
            logger.exception("failed to close owned document %r", active_title)
    if lease.disconnected:
        return
    if (
        lease.verified_exclusive
        and not lease.keep_application_open
        and not lease.generation_saved
    ):
        try:
            exit_owned_application(lease, app)
        except SessionOwnershipError:
            logger.error("ExitApp refused for task %s", lease.task_id)
        except Exception as error:
            if _exception_is_disconnect(error):
                lease.disconnected = True
                logger.error(
                    "COM disconnect during ExitApp of an owned session; "
                    "not force-killing by process name"
                )
            else:
                logger.exception("ExitApp failed for an owned session")
    else:
        logger.info(
            "leaving SolidWorks running; exclusive ownership is not proven "
            "(created_by_task=%s attached_existing=%s spawn_claimed=%s)",
            lease.created_by_task,
            lease.attached_existing,
            lease.spawn_claimed,
        )


def terminate_owned_process(
    lease: SessionLease,
    *,
    killer: Killer | None = None,
) -> None:
    """Signal the exact spawned PID. Never a process-name kill."""

    if lease.terminate_sent:
        return
    if not lease.verified_exclusive or lease.spawned_pid is None or lease.probe is None:
        raise SessionOwnershipError(
            "refusing to terminate a process this task cannot prove it owns"
        )
    pid = int(lease.spawned_pid)
    # Re-check immediately before the signal. prove_exclusive clears the flag
    # first, so a stale claim cannot kill a different process.
    if not lease.prove_exclusive(pid, lease.probe):
        raise SessionOwnershipError(
            "refusing to terminate: exclusive ownership failed re-verification"
        )
    killer = killer or lease.killer
    if killer is None:
        raise SessionOwnershipError(
            "native PID termination disabled until a process-lifetime-bound handle is implemented"
        )
    killer(pid)
    lease.terminate_sent = True


def _terminate_pid(pid: int) -> None:
    os.kill(int(pid), signal.SIGTERM)


def recycle_exclusive_session(
    *,
    private_mb: float,
    commit_free_mb: float | None,
    progress: Callable[[str], None] | None = None,
) -> bool:
    """Recycle only a proven exclusive session, on its STA thread.

    There is no GetActiveObject lookup, no CloseAllDocuments of an unknown
    instance, and no process-name kill. Without proof this raises immediately.
    """

    lease = current_lease()
    worker = _worker
    if (
        lease is None
        or worker is None
        or not lease.verified_exclusive
        or lease.poisoned
        or worker.poisoned
    ):
        raise SessionOwnershipError(
            "Refusing to recycle SolidWorks "
            f"(private memory {private_mb:.0f} MB, free commit {commit_free_mb}). "
            "No verified exclusive session. This task will not GetActiveObject, "
            "CloseAllDocuments, ExitApp, or kill SLDWORKS.exe."
        )
    if threading.get_ident() != lease.com_thread_id:
        raise SessionOwnershipError(
            "Refusing to recycle SolidWorks off the owning STA thread."
        )
    app = lease.app_for_recycle
    if app is None or lease.list_open_titles is None:
        raise SessionOwnershipError(
            "Refusing to recycle: the owned session handle is not registered. "
            "Will not look up a running SolidWorks instance."
        )
    try:
        titles = list(lease.list_open_titles(app))
    except Exception as error:
        raise SessionOwnershipError(
            "Refusing to recycle: cannot enumerate documents to prove they are all owned."
        ) from error
    if progress:
        progress("回收已证明由本任务独占的 SolidWorks 会话。")
    close_all_documents(lease, app, titles)
    exit_owned_application(lease, app)
    return True


def call_with_watchdog(
    timeout_sec: float,
    func: Callable,
    *args: Any,
    lease: SessionLease | None = None,
    **kwargs: Any,
) -> Any:
    """Bound ``func``. The watcher thread never calls COM.

    When this thread already owns the STA and shared COM is bound, ``func``
    stays on that thread so the call is not marshaled. A parent
    ``run_on_task_sta`` wait observes abandon and returns. Otherwise ``func``
    runs on a fresh thread that initializes COM before the call, and this
    caller returns when the deadline expires.
    """

    lease = current_lease() if lease is None else lease
    finished = threading.Event()
    state = {"timed_out": False}

    def _watch() -> None:
        ident = threading.get_ident()
        if lease is not None:
            lease.watchdog_thread_ids.append(ident)
        if finished.wait(timeout_sec):
            return
        state["timed_out"] = True
        logger.error(
            "SolidWorks call exceeded %.1fs; watchdog is not calling COM "
            "and will not kill by process name",
            timeout_sec,
        )
        if lease is None:
            return
        lease.timed_out = True
        if lease.verified_exclusive:
            try:
                terminate_owned_process(lease)
            except SessionOwnershipError:
                logger.error("owned-pid terminate refused after timeout")
            except Exception:
                logger.exception("owned-pid terminate failed after timeout")
        lease.request_abandon(
            "timeout; unproven sessions are not closed or killed"
            if not lease.verified_exclusive
            else "timeout; owned pid handled outside COM"
        )

    watcher = threading.Thread(target=_watch, name="sw-bend-watchdog", daemon=True)
    watcher.start()
    try:
        inline = (
            lease is not None
            and lease.shared_com_bound
            and lease.com_thread_id is not None
            and lease.com_thread_id == threading.get_ident()
        )
        if lease is not None and lease.shared_com_bound and not inline:
            raise SessionOwnershipError(
                "Refusing a timed SolidWorks call that would marshal shared COM "
                "onto another thread, and refusing to kill an unproven session "
                "to unblock it."
            )
        if inline:
            try:
                result = func(*args, **kwargs)
            except Exception as error:
                if state["timed_out"] or (lease is not None and lease.timed_out):
                    raise SwCallTimeoutError(
                        f"SolidWorks call timed out ({timeout_sec:.0f}s); "
                        "unproven sessions were not force-killed"
                    ) from error
                raise
            if state["timed_out"] or (lease is not None and lease.timed_out):
                raise SwCallTimeoutError(
                    f"SolidWorks call timed out ({timeout_sec:.0f}s); "
                    "unproven sessions were not force-killed"
                )
            return result

        box: dict[str, Any] = {}

        def _runner() -> None:
            com_ready = False
            pythoncom = None
            try:
                if (
                    lease is not None
                    and lease.shared_com_bound
                    and lease.com_thread_id not in (None, threading.get_ident())
                ):
                    box["error"] = SessionOwnershipError(
                        "refusing to run a SolidWorks call on a different STA"
                    )
                    return
                try:
                    import pythoncom as pythoncom  # type: ignore

                    pythoncom.CoInitialize()
                    com_ready = True
                except ImportError:
                    com_ready = False
                if lease is not None and lease.com_thread_id is None:
                    lease.bind_com_thread(threading.get_ident())
                box["result"] = func(*args, **kwargs)
            except BaseException as error:  # noqa: BLE001
                box["error"] = error
            finally:
                finished.set()
                if com_ready and pythoncom is not None:
                    try:
                        pythoncom.CoUninitialize()
                    except Exception:
                        pass

        runner = threading.Thread(target=_runner, name="sw-call-sta", daemon=True)
        runner.start()
        if not finished.wait(timeout_sec + 0.05):
            if lease is not None and not lease.abandon.is_set():
                lease.timed_out = True
                if lease.verified_exclusive:
                    try:
                        terminate_owned_process(lease)
                    except SessionOwnershipError:
                        logger.error("owned-pid terminate refused after timeout")
                    except Exception:
                        logger.exception("owned-pid terminate failed after timeout")
                lease.request_abandon("timeout without waiting on COM")
            raise SwCallTimeoutError(
                f"SolidWorks call timed out ({float(timeout_sec):.0f}s). "
                "Watchdog did not call COM. No process-name kill was issued."
            )
        if box.get("error") is not None:
            error = box["error"]
            if state["timed_out"]:
                raise SwCallTimeoutError(
                    f"SolidWorks call timed out ({float(timeout_sec):.0f}s); "
                    "session was not torn down by process name"
                ) from error
            raise error
        if state["timed_out"]:
            raise SwCallTimeoutError(
                f"SolidWorks call timed out ({float(timeout_sec):.0f}s); "
                "session was not torn down by process name"
            )
        return box.get("result")
    finally:
        finished.set()
        watcher.join(timeout=1.0)


