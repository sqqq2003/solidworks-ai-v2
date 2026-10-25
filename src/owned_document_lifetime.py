"""Owned-session inventory and teardown.

A proved spawn stays successful when the session is kept alive or when the
only documents are SolidWorks startup blanks from that same process. ExitApp
is optional. A clean exit observed after the request is success. Nothing here
attaches to a foreign process or kills SLDWORKS. Native CAD stays unverified.
"""
from __future__ import annotations

import logging
import re
import subprocess
import time

logger = logging.getLogger(__name__)

# DDD 2026-10-25: a 2s wait returned before SLDWORKS.exe actually exited.
DEFAULT_EXIT_POLL_SECONDS = 20.0
_TRANSIENT_INVENTORY_ATTEMPTS = 20
_TRANSIENT_INVENTORY_PAUSE_SEC = 0.1
_OTHER_INVENTORY_ATTEMPTS = 3
_OTHER_INVENTORY_PAUSE_SEC = 0.05

# Untitled default parts created by SolidWorks itself. Saved files carry an
# extension or a path and must not match.
_STARTUP_BLANK_TITLE = re.compile(r"^(?:零件|Part)\d+\*?$")
_TRANSIENT_INVENTORY_TEXT = (
    "invalid document count",
    "document enumeration shorter",
    "document enumeration longer",
    "empty/ambiguous",
)


def is_startup_blank_title(title) -> bool:
    """True for an unsaved default part name such as 零件2 or Part1."""
    return bool(_STARTUP_BLANK_TITLE.fullmatch(str(title).strip()))


def _transient_inventory_error(exc: BaseException) -> bool:
    from sw_session import is_com_server_disconnect

    if is_com_server_disconnect(exc):
        return False
    text = str(exc)
    return any(needle in text for needle in _TRANSIENT_INVENTORY_TEXT)


def read_owned_inventory(list_titles, app, *, transient_attempts=None, pause=None):
    """List titles, retrying the enumeration races seen on a fresh SLDWORKS."""
    from sw_session import is_com_server_disconnect

    transient_attempts = (
        _TRANSIENT_INVENTORY_ATTEMPTS if transient_attempts is None else transient_attempts
    )
    pause = _TRANSIENT_INVENTORY_PAUSE_SEC if pause is None else pause
    transient_used = 0
    other_used = 0
    while True:
        try:
            raw = list_titles(app)
            return [str(title) for title in (raw or []) if str(title).strip()]
        except Exception as exc:
            if is_com_server_disconnect(exc):
                raise
            if _transient_inventory_error(exc):
                transient_used += 1
                if transient_used >= transient_attempts:
                    raise
                time.sleep(pause)
                continue
            other_used += 1
            if other_used >= _OTHER_INVENTORY_ATTEMPTS:
                raise
            time.sleep(_OTHER_INVENTORY_PAUSE_SEC)


def adopt_and_close_startup_blanks(lease, app, titles) -> None:
    """Own and CloseDoc startup blanks that belong to this spawned process.

    User documents are not in ``titles`` filtering here; callers must pass only
    the blank names. Close uses the application directly so the write gate can
    settle a blank without re-entering require_model_write.
    """
    blanks = []
    for title in titles:
        name = str(title).strip()
        if not is_startup_blank_title(name):
            continue
        if name in lease.foreign_titles or name in lease.owned_docs:
            continue
        blanks.append(name)
    if not blanks:
        return
    logger.info("adopting startup blank documents into the owned session: %s", blanks)
    try:
        current = getattr(app, "UserControl", None)
        current = current() if callable(current) else current
        if current is not True:
            app.UserControl = True
    except Exception:
        logger.exception(
            "could not set UserControl before closing a startup blank; close still attempted"
        )
    for title in blanks:
        lease.note_owned_document(title)
        try:
            app.CloseDoc(title)
        except Exception:
            logger.exception("startup blank %r stayed open and owned", title)
            continue
        logger.info("closed owned startup blank %r", title)


def prepare_owned_inventory(lease, app, list_titles):
    """Retry listing. Adopt and close only unsaved default parts, then re-list."""
    titles: list[str] = []
    for _ in range(4):
        titles = read_owned_inventory(list_titles, app)
        open_now = set(titles)
        for name in list(lease.owned_docs):
            if is_startup_blank_title(name) and name not in open_now:
                lease.owned_docs.pop(name, None)
        foreign = [
            title for title in titles
            if title not in lease.owned_docs and not is_startup_blank_title(title)
        ]
        if foreign:
            return titles
        blanks = [
            title for title in titles
            if is_startup_blank_title(title) and title not in lease.owned_docs
        ]
        if not blanks:
            return titles
        adopt_and_close_startup_blanks(lease, app, titles)
    return read_owned_inventory(list_titles, app)


def poll_exit(binding, timeout=0):
    """Return the spawned process exit code, or None while it is still running.

    ``wait`` can time out in the same moment the process exits. A follow-up
    ``poll`` picks up that code so a clean exit is not reported as missing.
    """
    process = getattr(getattr(binding, "lifetime", None), "process", None)
    if process is None:
        return None
    code = process.poll()
    if code is None and timeout:
        try:
            code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            code = process.poll()
    return code


def _open_titles(binding) -> list[str]:
    raw = binding.list_titles(binding.app)
    return [str(title) for title in (raw or []) if str(title).strip()]


def finish_owned_session(lease, binding, *, exit_poll_seconds=None):
    """Finish a proved spawn without requiring ExitApp.

    Keep-alive (CloseDoc only) is success. When ExitApp is requested, wait
    ``exit_poll_seconds`` and treat exit code 0 as success. A still-running
    process with an empty document list is left open and is not a probe failure.
    Nonzero exits stay failures. Foreign documents stay failures.
    """
    from sw_session import (
        SessionOwnershipError,
        _exception_is_disconnect,
        exit_owned_application,
        require_model_write,
    )

    if exit_poll_seconds is None:
        exit_poll_seconds = DEFAULT_EXIT_POLL_SECONDS
    exit_requested = False
    try:
        binding.validate(lease)
        require_model_write(lease)
        if lease.keep_application_open:
            foreign = [title for title in _open_titles(binding) if title not in lease.owned_docs]
            if foreign:
                raise SessionOwnershipError(
                    "unowned documents remain; preserve session: " + ", ".join(foreign)
                )
            binding.cleanup_status = "left_open_keepalive"
            binding.cleanup_error = None
            logger.info(
                "owned session left open after CloseDoc; ExitApp not required pid=%s",
                getattr(lease, "spawned_pid", None),
            )
            return
        titles = set(_open_titles(binding))
        anchor = getattr(lease, "keepalive_document_title", None)
        extra = titles - ({anchor} if anchor else set())
        if extra:
            raise SessionOwnershipError(
                "task/foreign documents remain; no final cleanup or ExitApp"
            )
        if anchor:
            if anchor not in titles or anchor not in lease.owned_docs:
                raise SessionOwnershipError("keepalive document ownership/inventory differs")
            from sw_session import close_owned_document

            close_owned_document(lease, binding.app, anchor)
            lease.keepalive_document_title = None
            binding.anchor_closed = True
            code = poll_exit(binding)
            if code is not None:
                if type(code) is not int or code != 0:
                    raise RuntimeError(
                        "owned process exited abnormally after anchor close: " + str(code)
                    )
                binding.cleanup_status = "process_exited_cleanly"
                binding.cleanup_error = None
                return
        binding.validate(lease)
        require_model_write(lease)
        if _open_titles(binding):
            raise SessionOwnershipError("documents remain; ExitApp refused")
        code = poll_exit(binding)
        if type(code) is int:
            if code != 0:
                raise RuntimeError("owned process exited abnormally: " + str(code))
            binding.cleanup_status = "process_exited_cleanly"
            binding.cleanup_error = None
            return
        exit_owned_application(lease, binding.app)
        exit_requested = True
        binding.cleanup_status = "exit_requested"
        code = poll_exit(binding, timeout=exit_poll_seconds)
        if type(code) is int:
            if code != 0:
                raise RuntimeError("owned process exited abnormally: " + str(code))
            binding.cleanup_status = "process_exited_cleanly"
            binding.cleanup_error = None
            return
        # Exit was requested but not observed yet. An empty inventory is the
        # DDD keep-open case: the process can finish exiting after this call.
        try:
            still_open = _open_titles(binding)
        except Exception:
            still_open = ["<unlisted>"]
        if not still_open:
            binding.cleanup_status = "left_open_for_recovery"
            binding.cleanup_error = None
            logger.info(
                "ExitApp exit code still unobserved; empty inventory is not a probe failure"
            )
            return
        binding.cleanup_status = "left_open_for_recovery"
        binding.cleanup_error = (
            "owned process exit remains unobserved after exit request; preserve session"
        )
    except Exception as exc:
        from sw_session import ComSessionDisconnected, is_com_server_disconnect
        if lease.keep_application_open and (
            isinstance(exc, ComSessionDisconnected) or is_com_server_disconnect(exc)
        ):
            # CloseDoc / keep-alive lost the proxy after the body finished.
            # Leave the process alone. The caller keeps any saved part.
            binding.cleanup_status = "left_open_keepalive"
            binding.cleanup_error = None
            binding.cleanup_disconnect = type(exc).__name__ + ": " + str(exc)
            logger.info(
                "COM disconnect during keep-alive; ExitApp was not called pid=%s",
                getattr(lease, "spawned_pid", None),
            )
            return
        code = poll_exit(binding, timeout=exit_poll_seconds if exit_requested else 0)
        if type(code) is int and code == 0 and (exit_requested or _exception_is_disconnect(exc)):
            binding.cleanup_status = "process_exited_cleanly"
            binding.cleanup_error = None
            return
        binding.cleanup_status = (
            "left_open_for_recovery" if code is None else "process_exit_failed"
        )
        binding.cleanup_error = type(exc).__name__ + ": " + str(exc)


def release_closed_session_references(lease, binding):
    """Drop app references only after a confirmed clean process exit."""
    if binding.cleanup_error or binding.cleanup_status != "process_exited_cleanly":
        return
    from sw_session import SessionOwnershipError, on_task_sta

    if not on_task_sta():
        raise SessionOwnershipError("COM references must be released on the task STA")
    lease.app_for_recycle = None
    if lease.native_launch is not None:
        lease.native_launch.app = None
    lease.bound_app_ids.clear()
    lease.app_handle_id = None
    lease.verified_exclusive = False
    lease.writes_blocked = True
