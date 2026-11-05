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
from dataclasses import dataclass
from pathlib import PureWindowsPath

logger = logging.getLogger(__name__)

# DDD 2026-10-25: a 2s wait returned before SLDWORKS.exe actually exited.
DEFAULT_EXIT_POLL_SECONDS = 20.0
_TRANSIENT_INVENTORY_ATTEMPTS = 20
_TRANSIENT_INVENTORY_PAUSE_SEC = 0.1
_OTHER_INVENTORY_ATTEMPTS = 3
_OTHER_INVENTORY_PAUSE_SEC = 0.05
# A large assembly walk can drop one document proxy and recover on a rebind.
_INVENTORY_DISCONNECT_ATTEMPTS = 3

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


def _inventory_rewalk(exc: BaseException) -> bool:
    """True when a listing should rebind this PID and start the walk over.

    Disconnects and mid-walk ``DISP_E_MEMBERNOTFOUND`` both do. A missing member
    on ``GetNext`` is not a foreign document and is not left as a hard
    inventory-unavailable failure.
    """
    from sw_session import InventoryWalkDisconnected, is_com_server_disconnect

    if isinstance(exc, InventoryWalkDisconnected) or is_com_server_disconnect(exc):
        return True
    from part_verification import is_member_not_found

    return is_member_not_found(exc)


def _transient_inventory_error(exc: BaseException) -> bool:
    from sw_session import is_com_server_disconnect

    if is_com_server_disconnect(exc):
        return False
    text = str(exc)
    return any(needle in text for needle in _TRANSIENT_INVENTORY_TEXT)


def read_owned_inventory(
    list_titles,
    app,
    *,
    transient_attempts=None,
    pause=None,
    rebind=None,
    disconnect_attempts=None,
):
    """List titles, retrying startup races and a transient document-walk drop.

    ``rebind`` returns a replacement application for this same PID, or None.
    A disconnect with no rebind callback still fails immediately so an unproven
    spawn is not retried into a claim. ExitApp is not involved.
    """
    transient_attempts = (
        _TRANSIENT_INVENTORY_ATTEMPTS if transient_attempts is None else transient_attempts
    )
    disconnect_attempts = (
        _INVENTORY_DISCONNECT_ATTEMPTS
        if disconnect_attempts is None
        else disconnect_attempts
    )
    pause = _TRANSIENT_INVENTORY_PAUSE_SEC if pause is None else pause
    transient_used = 0
    other_used = 0
    disconnect_used = 0
    current = app
    while True:
        try:
            raw = list_titles(current)
            return [str(title) for title in (raw or []) if str(title).strip()]
        except Exception as exc:
            if _inventory_rewalk(exc):
                if rebind is None or disconnect_used >= disconnect_attempts:
                    if not isinstance(exc, InventoryWalkDisconnected):
                        from sw_session import InventoryWalkDisconnected

                        raise InventoryWalkDisconnected(
                            "document inventory walk disconnected during GetNext; "
                            "writes refused; ExitApp was not called"
                        ) from exc
                    raise
                disconnect_used += 1
                rebound = rebind()
                if rebound is not None:
                    current = rebound
                time.sleep(_OTHER_INVENTORY_PAUSE_SEC)
                continue
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


_MODEL_SUFFIXES = (".sldprt", ".sldasm", ".slddrw", ".slddrt")


def _norm_key(value) -> str:
    text = str(value or "").strip().rstrip("*").casefold()
    for suffix in _MODEL_SUFFIXES:
        if text.endswith(suffix):
            text = text[: -len(suffix)]
            break
    return text


def _norm_path(value) -> str:
    text = str(value or "").strip().strip('"')
    if not text:
        return ""
    return text.replace("/", "\\").casefold()


def _looks_like_path(value) -> bool:
    text = str(value or "")
    folded = text.casefold()
    return "\\" in text or "/" in text or folded.endswith(_MODEL_SUFFIXES)


def _split_dependency_tokens(tokens) -> tuple[set[str], set[str]]:
    """Return normalized paths and name keys from a dependency listing."""
    values = [str(item).strip() for item in (tokens or []) if str(item).strip()]
    paths: set[str] = set()
    names: set[str] = set()

    def add_path(raw: str) -> None:
        norm = _norm_path(raw)
        if not norm:
            return
        paths.add(norm)
        names.add(_norm_key(PureWindowsPath(raw.replace("/", "\\")).name))

    def add_name(raw: str) -> None:
        key = _norm_key(raw)
        if key:
            names.add(key)

    paired = (
        len(values) >= 2
        and len(values) % 2 == 0
        and _looks_like_path(values[1])
        and not _looks_like_path(values[0])
    )
    if paired:
        for index in range(0, len(values), 2):
            add_name(values[index])
            add_path(values[index + 1])
    else:
        for value in values:
            if _looks_like_path(value):
                add_path(value)
            else:
                add_name(value)
    return paths, names


@dataclass(frozen=True)
class OpenDocumentFact:
    title: str
    path: str = ""
    dependency_tokens: tuple[str, ...] = ()


@dataclass(frozen=True)
class LeasedReferenceAdoption:
    """Titles to own, and one pre-save title that SaveAs renamed."""

    note_titles: tuple[str, ...] = ()
    rename: tuple[str, str] | None = None


def _fact_identity(fact: OpenDocumentFact) -> tuple[str, str, str]:
    path = _norm_path(fact.path)
    file_key = _norm_key(PureWindowsPath(fact.path.replace("/", "\\")).name) if path else ""
    return path, _norm_key(fact.title), file_key


def _matches_dependency(fact: OpenDocumentFact, paths: set[str], names: set[str]) -> bool:
    """True when this open document is one of the listed references.

    A saved file must match a dependency path. A same-named file from another
    folder does not. An unsaved or virtual document may match a dependency
    name only when it has no path of its own.
    """
    path, title_key, file_key = _fact_identity(fact)
    if path and path in paths:
        return True
    if path:
        return False
    return bool(title_key) and (title_key in names or file_key in names)


def _referenced_by(fact: OpenDocumentFact, other: OpenDocumentFact) -> bool:
    paths, names = _split_dependency_tokens(other.dependency_tokens)
    return _matches_dependency(fact, paths, names)


def classify_leased_references(owned_titles, facts) -> LeasedReferenceAdoption:
    """Pick reference documents of the leased work, not another session's files.

    A title is a child only when an owned document, or the saved document that
    replaced one owned title, lists its path. A file that merely shares a
    folder, or a document that was never referenced, stays foreign.
    """
    owned = {str(title) for title in owned_titles}
    documents = [
        fact if isinstance(fact, OpenDocumentFact) else OpenDocumentFact(*fact)
        for fact in facts
    ]
    open_titles = {fact.title for fact in documents}
    if not owned or not documents:
        return LeasedReferenceAdoption()

    owned_open = [fact for fact in documents if fact.title in owned]
    dep_paths: set[str] = set()
    dep_names: set[str] = set()
    for fact in owned_open:
        paths, names = _split_dependency_tokens(fact.dependency_tokens)
        dep_paths.update(paths)
        dep_names.update(names)
    children = [
        fact.title
        for fact in documents
        if fact.title not in owned and _matches_dependency(fact, dep_paths, dep_names)
    ]
    child_set = set(children)
    missing = [title for title in owned if title not in open_titles]
    remaining = [
        fact for fact in documents
        if fact.title not in owned and fact.title not in child_set
    ]
    rename = None
    # SaveAs replaces an unsaved title (Drawing1 / 工程图1) with the filename.
    # A saved owned title that disappeared is not retargeted onto someone else's model.
    missing_unsaved = len(missing) == 1 and not str(missing[0]).casefold().endswith(_MODEL_SUFFIXES)
    if missing_unsaved and remaining:
        tops = [
            fact for fact in remaining
            if (_norm_path(fact.path) or str(fact.title).casefold().endswith(_MODEL_SUFFIXES))
            and not any(_referenced_by(fact, other) for other in documents)
            and any(_referenced_by(other, fact) for other in documents if other is not fact)
        ]
        if len(tops) == 1:
            top = tops[0]
            top_paths, top_names = _split_dependency_tokens(top.dependency_tokens)
            extras = [fact for fact in remaining if fact is not top]
            if extras and all(_matches_dependency(fact, top_paths, top_names) for fact in extras):
                rename = (missing[0], top.title)
                children.extend(fact.title for fact in extras)
    # Preserve first-seen order and drop duplicates.
    noted: list[str] = []
    for title in children:
        if title not in noted and title not in owned and (rename is None or title != rename[1]):
            noted.append(title)
    return LeasedReferenceAdoption(note_titles=tuple(noted), rename=rename)


def adopt_leased_reference_documents(lease, app) -> LeasedReferenceAdoption:
    """Own reference documents that this leased drawing or assembly loaded.

    Documents already marked foreign stay foreign. A walk that cannot prove a
    reference adopts nothing. ExitApp is not called and nothing is closed here;
    CloseDoc still runs later for titles this task owns.
    """
    if app is None or not getattr(lease, "owned_docs", None):
        return LeasedReferenceAdoption()
    if not (
        hasattr(app, "GetDocumentCount")
        or isinstance(getattr(type(app), "GetDocumentCount", None), property)
    ):
        return LeasedReferenceAdoption()
    from sw_session import InventoryWalkDisconnected, SessionOwnershipError, is_com_server_disconnect

    try:
        from solidworks_generator import open_document_facts

        raw = open_document_facts(app)
    except InventoryWalkDisconnected:
        raise
    except SessionOwnershipError:
        return LeasedReferenceAdoption()
    except Exception as exc:
        if is_com_server_disconnect(exc):
            raise
        from part_verification import is_member_not_found

        if is_member_not_found(exc):
            raise
        logger.info("could not prove leased reference documents: %s", exc)
        return LeasedReferenceAdoption()
    decision = classify_leased_references(lease.owned_docs, raw)
    if decision.rename is not None:
        old, new = decision.rename
        if old in lease.owned_docs and new not in lease.foreign_titles and new not in lease.owned_docs:
            lease.rename_owned(old, new)
            logger.info("owned document %r was saved as %r", old, new)
    adopted: list[str] = []
    for title in decision.note_titles:
        if title in lease.foreign_titles or title in lease.owned_docs:
            continue
        lease.note_owned_document(title)
        adopted.append(title)
    if adopted:
        sample = ", ".join(adopted[:8])
        logger.info(
            "owned %s referenced document(s) loaded by the leased model: %s",
            len(adopted),
            sample,
        )
    return decision


def prepare_owned_inventory(lease, app, list_titles, *, rebind=None):
    """Retry listing. Adopt and close only unsaved default parts, then re-list."""
    titles: list[str] = []
    for _ in range(4):
        titles = read_owned_inventory(list_titles, app, rebind=rebind)
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
    return read_owned_inventory(list_titles, app, rebind=rebind)


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


def _open_titles(binding, lease=None) -> list[str]:
    def rebind():
        rebound = getattr(binding, "rebind_for_inventory", None)
        if lease is None or rebound is None:
            return None
        if rebound(lease):
            return binding.app
        return None

    return read_owned_inventory(binding.list_titles, binding.app, rebind=rebind)


def cleanup_mentions_foreign_documents(error) -> bool:
    """True when cleanup found a document this task does not own.

    That still fails the session. An inventory/COM drop after a saved part
    does not.
    """
    folded = str(error or "").casefold()
    return (
        "unowned document" in folded
        or "preserve session" in folded
        or "does not own" in folded
    )


def _warn_and_leave(binding, exc):
    """Disconnect after save or during keep-alive. Do not raise and do not ExitApp."""
    binding.cleanup_status = "left_open_keepalive"
    binding.cleanup_error = None
    binding.cleanup_disconnect = type(exc).__name__ + ": " + str(exc)
    logger.warning(
        "COM disconnect during CloseDoc keep-alive; left the owned process open: %s",
        binding.cleanup_disconnect,
    )


def finish_owned_session(lease, binding, *, exit_poll_seconds=None):
    """Close documents this task owns. Never call ExitApp.

    A COM disconnect is probed once via the owned PID. If that rebind fails
    and a part was already saved, or the session is keep-alive, the context
    ends with a warning. The caller's generation result stays intact.
    """
    from sw_session import (
        SessionOwnershipError,
        close_owned_document,
    )

    if exit_poll_seconds is None:
        exit_poll_seconds = DEFAULT_EXIT_POLL_SECONDS
    # Cleanup does not call ExitApp. The argument remains so older callers
    # still import; a nonzero code already on the process is reported below.
    _ = exit_poll_seconds
    code = poll_exit(binding)
    if type(code) is int and code != 0:
        binding.cleanup_status = "process_exit_failed"
        binding.cleanup_error = "owned process exited abnormally: " + str(code)
        return
    if type(code) is int and code == 0:
        binding.cleanup_status = "process_exited_cleanly"
        binding.cleanup_error = None
        return
    try:
        binding.validate(lease)
        foreign = [title for title in _open_titles(binding, lease) if title not in lease.owned_docs]
        if foreign and not getattr(binding, "preserve_foreign_documents", False):
            raise SessionOwnershipError(
                "unowned documents remain; preserve session: " + ", ".join(foreign)
            )
        if foreign:
            logger.info(
                "attached session left %s pre-existing document(s) open: %s",
                len(foreign),
                ", ".join(foreign[:8]),
            )
        for title in [name for name in list(lease.owned_docs) if name in set(_open_titles(binding, lease))]:
            close_owned_document(lease, binding.app, title)
        binding.cleanup_status = "left_open_keepalive"
        binding.cleanup_error = None
        logger.info(
            "owned session left open after CloseDoc; ExitApp was not called pid=%s",
            getattr(lease, "spawned_pid", None),
        )
    except Exception as exc:
        from sw_session import normalize_com_disconnect
        normalized = normalize_com_disconnect(exc)
        if normalized is not None and not binding.rebind_attempted:
            binding.rebind_owned_pid(lease)
        saved = bool(getattr(lease, "generation_saved", False))
        if normalized is not None and saved:
            binding.cleanup_status = "saved_com_disconnected_after_generation"
            binding.cleanup_error = None
            binding.cleanup_disconnect = type(normalized).__name__ + ": " + str(normalized)
            if getattr(lease, "post_save_outcome", None) is None:
                lease.post_save_outcome = "partial_com_disconnect"
            logger.warning(
                "COM disconnect after the part was saved; ExitApp was not called: %s",
                binding.cleanup_disconnect,
            )
            return
        if saved and not cleanup_mentions_foreign_documents(exc):
            # Inventory/validate COM failures are not a disconnect HRESULT, but
            # the part is already on disk. Do not replace the caller's result.
            binding.cleanup_status = "partial_com_disconnect"
            binding.cleanup_error = None
            binding.cleanup_disconnect = type(exc).__name__ + ": " + str(exc)
            if getattr(lease, "post_save_outcome", None) is None:
                lease.post_save_outcome = "partial_com_disconnect"
            logger.warning(
                "saved part kept after cleanup/inventory COM failure; "
                "ExitApp was not called: %s",
                binding.cleanup_disconnect,
            )
            return
        if normalized is not None and lease.keep_application_open:
            _warn_and_leave(binding, normalized)
            return
        binding.cleanup_status = "left_open_for_recovery"
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
