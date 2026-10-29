"""Stage checkpoints, crash-safe locks, orphan staging quarantine, teardown logging.

Issue #19, stage 2 (cloud side only). This module is pure standard library so
it can be unit-tested on Linux without SolidWorks or pywin32.

pending_windows_validation: every Windows behavior described here (COM release
order, ExitApp exit codes, owned-process teardown) is unvalidated on real
SolidWorks hardware until Gork runs the validation checklist in the PR.
Mock success is never native acceptance.

Design notes (see issue #19 P0-B):
- A hard process crash (EXIT=139 / 0xC0000005 during COM teardown) skips
  every ``except``/``finally`` block, so evidence must be written DURING the
  run, not only at the end: one atomic checkpoint JSON per stage.
- A crash leaves two things behind: the publish lock directory and the
  staging directory. The next run must never silently delete either one:
  a stale lock is archived, orphan staging is quarantined under ``orphaned/``.
- The SAFEARRAY bridge for SW2022 math calls lives in ``sw_math_arrays.py``
  (PR #20). This module deliberately does NOT duplicate it.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import sys
import tempfile
import time
import uuid
from pathlib import Path, PurePosixPath, PureWindowsPath

logger = logging.getLogger(__name__)

# Stage order for the sheet-metal run_plan pipeline. S5 is the teardown report;
# the process exit code itself is recorded by the session owner
# (``sw_owned_launch.OwnedBinding.evidence``), not here.
STAGE_ORDER = ("S0", "S1", "S2", "S3", "S4", "S5")

# Default staleness bound for a publish lock: 2x the session call timeout
# (``sw_session.SW_SESSION_CALL_TIMEOUT_SEC`` = 600 s). A lock whose owner
# process is confirmed dead may be treated as a crash leftover. Heartbeat
# age is diagnostic only: a live or unprobeable owner is NEVER stolen.
DEFAULT_LOCK_STALE_SECONDS = 1200.0


def sha256_file(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def atomic_write_json(path, data) -> Path:
    """Write JSON via temp file + os.replace, so a crash never leaves a half file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".tmp-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(data, ensure_ascii=False, indent=2, default=str,
                                    allow_nan=False) + "\n")
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return path


def checkpoint_filename(stage: str) -> str:
    return "ckpt-" + stage + ".json"


def write_checkpoint(ckpt_dir, stage, *, plan_id, code_sha256, products=(),
                     evidence=None) -> dict:
    """Atomically record one completed stage.

    ``products`` is a list of ``{'name': ..., 'sha256': ...}`` for files that
    must still exist, byte-identical, for a later run to resume past this
    stage. ``evidence`` is a small JSON-safe summary (never a COM object).
    """
    if stage not in STAGE_ORDER:
        raise ValueError("unknown checkpoint stage: " + repr(stage))
    payload = {
        "schema_version": 1,
        "stage": stage,
        "plan_id": plan_id,
        "code_sha256": code_sha256,
        "timestamp": time.time(),
        "products": [{"name": str(p["name"]), "sha256": str(p["sha256"])}
                     for p in products],
        "evidence": evidence or {},
    }
    atomic_write_json(Path(ckpt_dir) / checkpoint_filename(stage), payload)
    return payload


def read_checkpoints(ckpt_dir) -> dict:
    """Read every well-formed checkpoint JSON in a directory, keyed by stage."""
    ckpts = {}
    ckpt_dir = Path(ckpt_dir)
    if not ckpt_dir.is_dir():
        return ckpts
    for stage in STAGE_ORDER:
        path = ckpt_dir / checkpoint_filename(stage)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(payload, dict) and payload.get("stage") == stage:
            ckpts[stage] = payload
    return ckpts


def validate_checkpoint_chain(ckpt_dir, *, plan_id, code_sha256, base_dir):
    """Return ``(resume_stage, checkpoints)`` for a contiguous, intact chain.

    The chain must start at S0 with no gaps, and every stage must match the
    current plan id and code hash (this is the "modified or stale plan;
    regenerate" discipline). Product files are verified only for the LATEST
    stage in the chain: earlier stages' products are superseded by later
    stages, and a later stage may legitimately rewrite a product. If the
    latest stage's products are missing or changed, fall back to the previous
    stage and re-verify, until the chain is empty (``(None, {})``).
    """
    ckpts = read_checkpoints(ckpt_dir)
    chain = []
    for stage in STAGE_ORDER:
        payload = ckpts.get(stage)
        if payload is None:
            break
        if payload.get("plan_id") != plan_id or payload.get("code_sha256") != code_sha256:
            break
        chain.append(stage)
    while chain:
        latest = ckpts[chain[-1]]
        intact = True
        for product in latest.get("products", []):
            name=product.get('name')
            if not isinstance(name,str) or PurePosixPath(name).root or PureWindowsPath(name).root or PureWindowsPath(name).drive or '\\' in name or '..' in PurePosixPath(name).parts:
                intact=False
                break
            candidate = (Path(base_dir) / name).resolve()
            if (not candidate.is_relative_to(Path(base_dir).resolve()) or not candidate.is_file()
                    or sha256_file(candidate) != product["sha256"]):
                intact = False
                break
        if intact:
            return chain[-1], ckpts
        chain.pop()
    return None, {}


def _windows_pid_alive(pid) -> bool | None:
    """Non-destructive Windows liveness query. Never send a signal."""
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE only
    if not handle:
        return False if ctypes.get_last_error() == 87 else None
    try:
        state = kernel.WaitForSingleObject(handle, 0)
        return True if state == 258 else (False if state == 0 else None)
    finally:
        kernel.CloseHandle(handle)


def _pid_alive(pid) -> bool | None:
    if type(pid) is not int or pid<=0:
        return None
    if sys.platform == "win32":
        try:
            return _windows_pid_alive(pid)
        except (OSError, ValueError, OverflowError):
            return None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except (OSError, ValueError, OverflowError):
        return None
    return True


class RunLock:
    """Crash-safe single-publisher lock for one plan label.

    The lock is a directory holding ``owner.json`` (token, pid, plan id,
    heartbeat). It is NEVER removed while another live run owns it; a stale
    lock is archived (renamed), never deleted, so a crash scene stays
    inspectable.
    """

    def __init__(self, root, label, *, plan_id,
                 stale_after_seconds=DEFAULT_LOCK_STALE_SECONDS):
        self.root = Path(root)
        self.label = label
        self.plan_id = plan_id
        self.stale_after_seconds = float(stale_after_seconds)
        self.lock_dir = self.root / ("." + label + ".lock")
        self.token = uuid.uuid4().hex
        self.acquired = False
        self.archived_from = None

    def _owner_path(self):
        return self.lock_dir / "owner.json"

    def _write_owner(self):
        now = time.time()
        atomic_write_json(self._owner_path(), {
            "schema_version": 1,
            "token": self.token,
            "pid": os.getpid(),
            "plan_id": self.plan_id,
            "started": now,
            "heartbeat": now,
        })

    def acquire(self) -> str:
        """Return 'acquired', or 'recovered_stale_lock' after archiving a stale one.

        Raises RuntimeError when a live run holds the lock, or when the
        existing lock's owner cannot be read (an unreadable owner is never
        assumed stale).
        """
        try:
            self.lock_dir.mkdir()
        except FileExistsError:
            pass
        else:
            self._write_owner()
            self.acquired = True
            return "acquired"
        try:
            owner = json.loads(self._owner_path().read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise RuntimeError(
                "publish lock held but owner unreadable; refusing to steal it: "
                + str(self.lock_dir)) from exc
        alive = _pid_alive(owner.get("pid"))
        age = time.time() - float(owner.get("heartbeat", 0) or 0)
        if alive is not False:
            raise RuntimeError(
                "publish lock owner live or unverified pid=%s plan=%s age=%.1fs; "
                "refusing to steal it" % (owner.get("pid"), owner.get("plan_id"), age))
        stamp = time.strftime("%Y%m%d_%H%M%S") + "-" + uuid.uuid4().hex[:8]
        archived = self.root / (self.lock_dir.name + ".archived-" + stamp)
        os.rename(self.lock_dir, archived)
        self.archived_from = archived
        self.lock_dir.mkdir()
        self._write_owner()
        self.acquired = True
        logger.info("recovered stale publish lock from %s (pid=%s alive=%s age=%.1fs)",
                    archived, owner.get("pid"), alive, age)
        return "recovered_stale_lock"

    def heartbeat(self) -> bool:
        """Refresh the heartbeat timestamp. Returns False if this lock is gone
        or no longer ours; a failed heartbeat never kills a run by itself."""
        try:
            owner = json.loads(self._owner_path().read_text(encoding="utf-8"))
            if owner.get("token") != self.token:
                logger.error("publish lock token mismatch; lock no longer ours")
                return False
            owner["heartbeat"] = time.time()
            atomic_write_json(self._owner_path(), owner)
            return True
        except (OSError, ValueError) as exc:
            logger.warning("publish lock heartbeat failed: %s", exc)
            return False

    def release(self) -> bool:
        """Remove only a lock this instance owns. Returns False if already gone."""
        if not self.acquired:
            return False
        try:
            owner = json.loads(self._owner_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        if owner.get("token") != self.token:
            raise RuntimeError("refusing to release a publish lock owned by another run")
        try:
            self._owner_path().unlink()
            self.lock_dir.rmdir()
        except OSError:
            return False
        self.acquired = False
        return True


def quarantine_orphan_staging(root, label, *, is_resumable):
    """Sort staging dirs left by crashed runs.

    ``is_resumable(dir)`` decides whether a ``.<label>-*`` staging directory
    still holds a usable checkpoint chain. Resumable dirs are returned
    untouched; every other one is moved under ``orphaned/`` (never deleted),
    preserving the crash scene for inspection.
    """
    root = Path(root)
    orphaned_root = root / "orphaned"
    resumable, quarantined = [], []
    for candidate in sorted(root.iterdir()):
        if not candidate.is_dir() or not candidate.name.startswith("." + label + "-"):
            continue
        if is_resumable(candidate):
            resumable.append(candidate)
            continue
        orphaned_root.mkdir(parents=True, exist_ok=True)
        target = orphaned_root / (candidate.name + "-" + uuid.uuid4().hex[:8])
        os.rename(candidate, target)
        quarantined.append(target)
        logger.info("quarantined orphan staging %s -> %s", candidate, target)
    return resumable, quarantined


def write_crash_package(root, *, plan_id, error, checkpoints, products,
                        log_tail=()) -> Path:
    """Write a ``crash-<uuid>.json`` evidence bundle next to the failure file.

    This is written BEFORE staging cleanup on a soft failure, and the
    checkpoint directory itself survives a hard crash, so a later accept
    never has to be reconstructed from logs and disk files alone.
    """
    payload = {
        "schema_version": 1,
        "plan_id": plan_id,
        "error": str(error),
        "timestamp": time.time(),
        "last_checkpoints": checkpoints,
        "products": products,
        "log_tail": list(log_tail),
    }
    path = Path(root) / ("crash-" + uuid.uuid4().hex + ".json")
    atomic_write_json(path, payload)
    return path


class TeardownRecorder:
    """Structured S5 teardown log: one line per step, owned-docs before/after.

    Steps, in order: close_doc, enumerate_open_titles, exit_app,
    release_com_wrappers, process_exit_code.
    """

    def __init__(self, *, pid=None):
        self.pid = pid
        self.steps = []

    def record(self, step, *, status, owned_docs_before=(), owned_docs_after=(),
               elapsed_ms=None, detail=None):
        entry = {
            "step": step,
            "status": status,
            "owned_docs_before": list(owned_docs_before),
            "owned_docs_after": list(owned_docs_after),
            "pid": self.pid,
            "elapsed_ms": elapsed_ms,
            "detail": detail,
            "timestamp": time.time(),
        }
        self.steps.append(entry)
        return entry

    def report(self):
        return {
            "schema_version": 1,
            "pid": self.pid,
            "ok": all(step["status"] == "ok" for step in self.steps),
            "steps": self.steps,
        }


def assert_release_order(events) -> bool:
    """Mock-checkable release rule: every ``release:*`` must precede ``uninitialize``.

    ``events`` is a recorded sequence such as
    ``['release:model', 'release:feature', 'uninitialize']``. A release
    recorded after ``uninitialize`` raises AssertionError.
    """
    if "uninitialize" not in events:
        return True
    index = events.index("uninitialize")
    late = [event for event in events[index + 1:] if event.startswith("release:")]
    if late:
        raise AssertionError(
            "COM wrappers released after CoUninitialize (teardown AV risk): " + ", ".join(late))
    return True


def release_wrappers_in_order(wrappers, uninitialize, *, recorder=None) -> dict:
    """Release COM wrappers in order, then unload COM last.

    ``wrappers`` is a list of ``(name, release_callable)`` in release order
    (reverse creation order). A failing release is recorded and does not
    skip the remaining releases or the final uninitialize; the report's
    ``ok`` flag is False in that case. pending_windows_validation: the
    real-SolidWorks effect of this order is unvalidated until Gork runs it.
    """
    order = []
    failed = []
    for name, release in wrappers:
        try:
            release()
            order.append("release:" + name)
            if recorder is not None:
                recorder.record("release_" + name, status="ok")
        except Exception as exc:  # noqa: BLE001 - teardown must not mask the cause
            failed.append(name)
            order.append("release:" + name + ":failed")
            if recorder is not None:
                recorder.record("release_" + name, status="failed", detail=str(exc))
    try:
        uninitialize()
        order.append("uninitialize")
        if recorder is not None:
            recorder.record("uninitialize", status="ok")
    except Exception as exc:  # noqa: BLE001 - report, do not raise from teardown
        failed.append("uninitialize")
        order.append("uninitialize:failed")
        if recorder is not None:
            recorder.record("uninitialize", status="failed", detail=str(exc))
    assert_release_order(order)
    return {"order": order, "failed": failed, "ok": not failed}


def run_teardown_sequence(steps, *, recorder=None, pid=None) -> dict:
    """Run the 5 S5 teardown steps in order, recording each, never aborting early.

    ``steps`` maps step names to callables:
    ``close_docs`` -> per-doc outcomes, ``enumerate_titles`` -> open titles,
    ``exit_app`` -> anything, ``release`` -> release report,
    ``poll_exit_code`` -> int exit code or None when still running.
    A failing step is recorded and the sequence continues, so a teardown
    failure can never hide which later steps were skipped.
    """
    own_recorder = TeardownRecorder(pid=pid)
    record = recorder.record if recorder is not None else own_recorder.record
    started = time.monotonic()
    exit_code = None
    close_succeeded = False
    titles_empty = False
    for step in ("close_docs", "enumerate_titles", "exit_app", "release",
                 "poll_exit_code"):
        fn = steps.get(step)
        if fn is None:
            record(step, status="skipped", elapsed_ms=0)
            continue
        if step == "exit_app" and not (close_succeeded and titles_empty):
            record(step,status="skipped",elapsed_ms=0,detail="close or zero-document inventory not established; no ExitApp")
            continue
        step_started = time.monotonic()
        try:
            result = fn()
            if step == "close_docs":
                if isinstance(result,dict) and result.get("ok") is False:raise RuntimeError("document close report failed")
                close_succeeded = True
            if step == "enumerate_titles":
                if not isinstance(result,(list,tuple,set)) or result:raise RuntimeError("document inventory unavailable or nonempty; refuse ExitApp")
                titles_empty = True
            if step == "release" and isinstance(result,dict) and result.get("ok") is False:
                raise RuntimeError("COM wrapper release report failed")
            if step == "poll_exit_code":
                exit_code = result
                if type(result) is not int or result != 0:
                    record(step,status="pending" if result is None else "failed",elapsed_ms=int((time.monotonic()-step_started)*1000),detail="observed exit_code="+repr(result))
                    continue
            record(step, status="ok",
                   elapsed_ms=int((time.monotonic() - step_started) * 1000),
                   detail=None if step == "poll_exit_code" else str(result)[:500])
        except Exception as exc:  # noqa: BLE001 - teardown evidence, not control flow
            record(step, status="failed",
                   elapsed_ms=int((time.monotonic() - step_started) * 1000),
                   detail=str(exc)[:500])
    report = (recorder.report() if recorder is not None else own_recorder.report())
    report["exit_code"] = exit_code
    report["elapsed_ms"] = int((time.monotonic() - started) * 1000)
    return report


def run_minimal_teardown(callables, *, repeat=1, pid=None) -> dict:
    """Minimal teardown repro, injectable so it runs on Linux with fakes.

    ``callables`` provides ``spawn`` plus the five teardown callables of
    :func:`run_teardown_sequence`. Each repetition spawns fresh, then runs
    the teardown sequence. Real SolidWorks wiring lives in :func:`main`
    (Windows only); everything asserted here is pending_windows_validation.
    """
    repetitions = []
    for _ in range(max(1, int(repeat))):
        spawn = callables.get("spawn")
        if spawn is None:
            raise ValueError("minimal teardown requires a spawn callable")
        spawned = spawn()
        steps = {name: callables[name] for name in
                 ("close_docs", "enumerate_titles", "exit_app", "release",
                  "poll_exit_code") if callables.get(name) is not None}
        report = run_teardown_sequence(steps, pid=pid)
        report["spawned"] = str(spawned)[:500]
        repetitions.append(report)
    return {
        "schema_version": 1,
        "mode": "minimal_teardown",
        "repetitions": repetitions,
        "ok": all(rep["ok"] and rep["exit_code"] == 0 for rep in repetitions),
        "pending_windows_validation": True,
    }


def main(argv=None) -> int:
    """Minimal teardown repro entry point (Windows only).

    Spawns an owned SolidWorks process, creates no documents, lets the
    owned launcher run its normal teardown (zero-document check + ExitApp),
    and reports the process exit code. Repeat 3 times by default, per the
    Gork checklist: a nonzero/AV exit here proves the crash is in teardown
    itself, not in modeling. pending_windows_validation: this entry point
    has never run on real SolidWorks hardware.
    """
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sw-exe", required=True,
                        help="installed SLDWORKS.exe absolute path")
    parser.add_argument("--repeat", type=int, default=3,
                        help="spawn/teardown repetitions (default 3)")
    parser.add_argument("--output-dir",help="new log directory for the multi-process repetition batch")
    args = parser.parse_args(argv)
    if sys.platform != "win32":
        print(json.dumps({
            "status": "refused",
            "reason": "SolidWorks native execution requires Windows",
            "pending_windows_validation": True,
        }, ensure_ascii=False))
        return 2
    if args.repeat>1:
        from minimal_session_batch import run_batch
        directory=Path(args.output_dir) if args.output_dir else Path(tempfile.gettempdir())/('sw-minimal-'+uuid.uuid4().hex)
        result=run_batch(args.sw_exe,args.repeat,directory)
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 0 if result['status']=='teardown_clean' else 1
    sys.path[:0] = [str(Path(__file__).resolve().parent)]
    from sw_session import run_on_task_sta
    from sw_owned_launch import owned_solidworks
    reports = []
    for _ in range(max(1, int(args.repeat))):
        def live_job():
            with owned_solidworks(args.sw_exe) as binding:
                pass  # No documents: teardown-only repro, no modeling.
            code = None
            for _ in range(30):
                code = binding.lifetime.process.poll()
                if code is not None:
                    break
                time.sleep(1)
            return {
                "exit_code": code,
                "session": binding.evidence(),
                "note": ("process still running after ExitApp; left open for "
                         "recovery" if code is None else "process exited"),
            }
        reports.append(run_on_task_sta(live_job, timeout=300,
                                       task_name="minimal-teardown"))
    ok = all(type(rep["exit_code"]) is int and rep["exit_code"] == 0 and not rep["session"].get("cleanup_error") and rep["session"].get("cleanup_status") in {"exit_requested","process_exited_cleanly"} for rep in reports)
    print(json.dumps({
        "status": "teardown_clean" if ok else "teardown_failed",
        "repetitions": reports,
        "pending_windows_validation": True,
    }, indent=2, ensure_ascii=False, default=str))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())



