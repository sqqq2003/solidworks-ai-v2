"""Simulated session-safety tests. No live SolidWorks, no process-name kill."""

from __future__ import annotations

import hashlib
import sys
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
BASELINE = ROOT / "results" / "cursor" / "baseline" / "src"
sys.path.insert(0, str(SRC))

BASELINE_SHA256 = {
    "batch_export.py": "472e86abcfa13cc14ac309592ee2dcf5c64cd83a2c64d578ec7fe9214d3c582f",
    "solidworks_generator.py": "0b1e3d722ce681d0f7fd7a17afe6b8d5594572aff6b39beac4c8e25656d8c7bd",
}


import batch_export  # noqa: E402
import dwg_converter  # noqa: E402
import solidworks_generator as swg  # noqa: E402
import sw_session  # noqa: E402
import turned_part  # noqa: E402
from sw_session import (  # noqa: E402
    ProcessProbeInfo,
    SessionOwnershipError,
    SwCallTimeoutError,
    call_with_watchdog,
    close_all_documents,
    close_owned_document,
    connect_application,
    current_lease,
    exit_owned_application,
    recycle_exclusive_session,
    release_task_documents,
    run_on_task_sta,
)


class _ComError(Exception):
    pass


class _Disconnected(Exception):
    def __init__(self) -> None:
        super().__init__(-2147417848, "The object invoked has disconnected from its clients.")


class _Doc:
    def __init__(self, title: str, nxt: "_Doc | None" = None) -> None:
        self.title = title
        self.nxt = nxt

    def GetTitle(self) -> str:
        return self.title

    def GetNext(self) -> "_Doc | None":
        return self.nxt


class FakeApp:
    def __init__(self, titles: list[str] | None = None) -> None:
        self.titles = list(titles or [])
        self.closed: list[tuple[str, int]] = []
        self.closed_all = False
        self.exited = False
        self.close_error: BaseException | None = None
        self.calls: list[tuple[str, int]] = []

    def GetDocumentCount(self) -> int:
        return len(self.titles)

    def GetFirstDocument(self) -> _Doc | None:
        head: _Doc | None = None
        for title in reversed(self.titles):
            head = _Doc(title, head)
        return head

    def CloseDoc(self, title: str) -> None:
        self.closed.append((str(title), threading.get_ident()))
        self.calls.append(("CloseDoc", threading.get_ident()))
        if self.close_error is not None:
            raise self.close_error

    def CloseAllDocuments(self, _flag: bool) -> None:
        self.closed_all = True
        self.calls.append(("CloseAllDocuments", threading.get_ident()))

    def ExitApp(self) -> None:
        self.exited = True
        self.calls.append(("ExitApp", threading.get_ident()))


class _Client:
    def __init__(
        self,
        *,
        active: FakeApp | None = None,
        active_error: BaseException | None = None,
    ) -> None:
        self.active = active or FakeApp()
        self.active_error = active_error
        self.gets = 0
        self.dispatches = 0

    def GetActiveObject(self, _name: str) -> FakeApp:
        self.gets += 1
        if self.active_error is not None:
            raise self.active_error
        return self.active

    def Dispatch(self, _name: str) -> FakeApp:
        self.dispatches += 1
        return self.active


def _pythoncom() -> types.SimpleNamespace:
    return types.SimpleNamespace(com_error=_ComError)


def _win32(client: _Client) -> types.SimpleNamespace:
    return types.SimpleNamespace(client=client)


def _probe_sldworks(pid: int) -> ProcessProbeInfo:
    return ProcessProbeInfo(pid=pid, alive=True, image="SLDWORKS.exe")


def _make_exclusive(lease, pid: int = 4242) -> None:
    lease.spawn_claimed = True
    lease.spawned_pid = pid
    lease.observed_pid = pid
    lease.attached_existing = False
    lease.created_by_task = True
    lease.foreign_titles = set()
    lease.foreign_titles_known = True
    lease.probe = _probe_sldworks
    lease.poisoned = False
    if not lease.prove_exclusive(pid, _probe_sldworks):
        raise AssertionError("exclusive fixture was not proven")


class SessionSafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        sw_session.reset_for_tests()

    def tearDown(self) -> None:
        sw_session.reset_for_tests()

    @unittest.skipUnless(
        all((BASELINE / name).is_file() for name in BASELINE_SHA256),
        "results/cursor/baseline/src originals are not in the cloud pack; "
        "hash check stays local-only and is not a SolidWorks live test",
    )
    def test_baseline_hashes_match_uploaded_sources(self) -> None:
        for name, expected in BASELINE_SHA256.items():
            digest = hashlib.sha256((BASELINE / name).read_bytes()).hexdigest()
            self.assertEqual(digest, expected, name)

    def test_patched_sources_have_no_process_name_kill(self) -> None:
        for name in ("solidworks_generator.py", "batch_export.py"):
            text = (SRC / name).read_text(encoding="utf-8")
            self.assertNotIn("taskkill", text, name)
            self.assertNotIn("CloseAllDocuments", text, name)
            self.assertNotIn(".ExitApp(", text, name)
            self.assertNotIn("_kill_solidworks_processes", text, name)
        batch = (SRC / "batch_export.py").read_text(encoding="utf-8")
        self.assertNotIn("GetActiveObject", batch)
        self.assertNotIn("ExitApp", batch)
        generator = (SRC / "solidworks_generator.py").read_text(encoding="utf-8")
        self.assertIn("release_task_documents", generator)
        self.assertIn("run_on_task_sta", generator)
        self.assertIn("_connect_task_solidworks", generator)
        self.assertIn("require_model_write", generator)
        for name in ("turned_part.py", "dwg_converter.py"):
            text = (SRC / name).read_text(encoding="utf-8")
            self.assertNotIn("taskkill", text, name)
            self.assertNotIn(".ExitApp(", text, name)
            self.assertNotIn(".CloseDoc(", text, name)
            self.assertIn("require_model_write", text, name)
            self.assertIn("release_task_documents", text, name)

    def test_watchdog_returns_without_killing_or_calling_com(self) -> None:
        app = FakeApp()
        killed: list[int] = []

        def hang() -> None:
            time.sleep(5)

        started = time.monotonic()
        with self.assertRaises(swg._SwWatchdogTimeout):
            swg._call_with_sw_watchdog(0.2, hang)
        self.assertLess(time.monotonic() - started, 2.0)
        self.assertEqual(app.calls, [])
        self.assertEqual(killed, [])

    def test_unproven_inline_timeout_does_not_touch_com(self) -> None:
        app = FakeApp()
        killed: list[tuple[int, int]] = []

        def job() -> None:
            lease = current_lease()
            assert lease is not None
            lease.shared_com_bound = True
            lease.app_for_recycle = app
            lease.killer = lambda pid: killed.append((pid, threading.get_ident()))

            def hang() -> None:
                time.sleep(5)

            call_with_watchdog(0.2, hang)

        started = time.monotonic()
        with self.assertRaises(SwCallTimeoutError) as caught:
            run_on_task_sta(job, timeout=5, task_name="unproven-timeout")
        self.assertLess(time.monotonic() - started, 2.0)
        self.assertIn("cannot prove an exclusive session", str(caught.exception))
        self.assertEqual(app.calls, [])
        self.assertEqual(killed, [])
        worker = sw_session.active_worker()
        assert worker is not None and worker.sta_id is not None
        self.assertTrue(worker.lease.watchdog_thread_ids)
        self.assertNotIn(worker.sta_id, worker.lease.watchdog_thread_ids)
        with self.assertRaises(SessionOwnershipError):
            sw_session.require_model_write(worker.lease)
        started = time.monotonic()
        with self.assertRaises(SessionOwnershipError):
            run_on_task_sta(lambda: None, timeout=5, task_name="after-timeout")
        self.assertLess(time.monotonic() - started, 0.5)

    def test_exclusive_timeout_signals_only_owned_pid_off_sta(self) -> None:
        app = FakeApp()
        killed: list[tuple[int, int]] = []

        def job() -> None:
            lease = current_lease()
            assert lease is not None
            _make_exclusive(lease, 77)
            lease.shared_com_bound = True
            lease.app_for_recycle = app
            lease.killer = lambda pid: killed.append((int(pid), threading.get_ident()))
            call_with_watchdog(0.2, lambda: time.sleep(5))

        started = time.monotonic()
        with self.assertRaises(SwCallTimeoutError):
            run_on_task_sta(job, timeout=5, task_name="owned-timeout")
        self.assertLess(time.monotonic() - started, 2.0)
        self.assertTrue(killed)
        self.assertTrue(all(pid == 77 for pid, _thread in killed))
        worker = sw_session.active_worker()
        assert worker is not None and worker.sta_id is not None
        self.assertTrue(all(thread != worker.sta_id for _pid, thread in killed))
        self.assertEqual(app.calls, [])
        self.assertFalse(app.exited)
        blocked = sw_session.active_worker()
        assert blocked is not None
        with self.assertRaises(SessionOwnershipError):
            sw_session.require_model_write(blocked.lease)

    def test_com_disconnect_does_not_exit_or_kill(self) -> None:
        error = _Disconnected()
        self.assertTrue(swg._is_com_disconnect_error(error))

        def job() -> None:
            lease = current_lease()
            assert lease is not None
            _make_exclusive(lease, 15)
            app = FakeApp()
            app.close_error = error
            lease.app_for_recycle = app
            lease.app_handle_id = id(app)
            lease.bound_app_ids.add(id(app))
            lease.note_owned_document("Part1", handle_id=15)
            release_task_documents(lease, app, title="Part1", close=True)
            self.assertTrue(lease.disconnected)
            self.assertFalse(app.exited)
            self.assertFalse(app.closed_all)
            self.assertEqual([item[0] for item in app.closed], ["Part1"])

        run_on_task_sta(job, timeout=3, task_name="disconnect")

    def test_attached_user_session_cannot_be_torn_down(self) -> None:
        client = _Client(active=FakeApp(["User.SLDPRT"]))

        def job() -> None:
            lease = current_lease()
            assert lease is not None
            app, created = swg._connect_task_solidworks(lease, _win32(client), _pythoncom())
            self.assertFalse(created)
            self.assertFalse(lease.verified_exclusive)
            self.assertEqual(lease.foreign_titles, {"User.SLDPRT"})
            self.assertEqual(client.dispatches, 0)
            lease.note_owned_document("Part9", handle_id=9)
            with self.assertRaises(SessionOwnershipError):
                lease.note_owned_document("User.SLDPRT", handle_id=1)
            with self.assertRaises(SessionOwnershipError):
                close_owned_document(lease, app, "User.SLDPRT")
            close_owned_document(lease, app, "Part9")
            swg._release_generation_session(
                lease,
                app,
                None,
                document_title="Part9",
                close_document=True,
                saved=True,
                model=types.SimpleNamespace(GetTitle=lambda: "User.SLDPRT"),
            )
            self.assertEqual([item[0] for item in app.closed], ["Part9"])
            self.assertFalse(app.exited)
            self.assertFalse(app.closed_all)
            with self.assertRaises(SessionOwnershipError):
                exit_owned_application(lease, app)
            with self.assertRaises(SessionOwnershipError):
                close_all_documents(lease, app, ["Part9", "User.SLDPRT"])

        run_on_task_sta(job, timeout=3, task_name="user-doc")

    def test_dispatch_without_matching_pid_is_not_exclusive(self) -> None:
        client = _Client(active=FakeApp(), active_error=_ComError("absent"))

        def job() -> None:
            lease = current_lease()
            assert lease is not None
            lease.spawn_claimed = True
            lease.spawned_pid = 42
            lease.probe = _probe_sldworks
            _app, created = swg._connect_task_solidworks(
                lease, _win32(client), _pythoncom()
            )
            self.assertTrue(created)
            self.assertFalse(lease.verified_exclusive)
            self.assertEqual(client.dispatches, 1)
            swg._release_generation_session(
                lease,
                _app,
                None,
                document_title=None,
                close_document=False,
                saved=False,
                model=None,
            )
            self.assertFalse(_app.exited)

        run_on_task_sta(job, timeout=3, task_name="dispatch-unproven")

    def test_non_absent_connect_error_is_not_swallowed(self) -> None:
        client = _Client(active_error=RuntimeError("registry failed"))

        def job() -> None:
            lease = current_lease()
            assert lease is not None
            with self.assertRaises(RuntimeError):
                swg._connect_task_solidworks(lease, _win32(client), _pythoncom())
            self.assertEqual(client.dispatches, 0)

        run_on_task_sta(job, timeout=3, task_name="connect-error")

    def test_proven_spawn_can_exit_only_on_sta(self) -> None:
        box: dict[str, object] = {}

        def job() -> None:
            lease = current_lease()
            assert lease is not None
            app = FakeApp()
            _app, created = connect_application(
                lease,
                get_active=lambda: (_ for _ in ()).throw(_ComError("absent")),
                dispatch=lambda: app,
                list_titles=lambda application: application.titles,
                is_absent=lambda error: isinstance(error, _ComError),
                read_pid=lambda _application: 88,
            )
            lease.spawn_claimed = True
            lease.spawned_pid = 88
            lease.probe = _probe_sldworks
            self.assertTrue(created)
            self.assertTrue(lease.prove_exclusive(88, _probe_sldworks))
            lease.note_owned_document("Owned.SLDPRT", handle_id=88)
            self.assertEqual(lease.owned_docs["Owned.SLDPRT"].handle_id, 88)
            close_all_documents(lease, app, ["Owned.SLDPRT"])
            self.assertTrue(app.closed_all)
            exit_owned_application(lease, app)
            self.assertTrue(app.exited)
            self.assertIn(threading.get_ident(), [item[1] for item in app.calls])
            box["lease"] = lease
            box["app"] = FakeApp()

        run_on_task_sta(job, timeout=3, task_name="exclusive-exit")
        fresh = FakeApp()
        lease = box["lease"]
        with self.assertRaises(SessionOwnershipError) as caught:
            exit_owned_application(lease, fresh)
        self.assertIn("STA", str(caught.exception))
        self.assertFalse(fresh.exited)

    def test_wrong_image_or_foreign_doc_blocks_exclusive_kill(self) -> None:
        def notepad(pid: int) -> ProcessProbeInfo:
            return ProcessProbeInfo(pid=pid, alive=True, image="notepad.exe")

        def job() -> None:
            lease = current_lease()
            assert lease is not None
            lease.spawn_claimed = True
            lease.spawned_pid = 5
            lease.observed_pid = 5
            lease.attached_existing = False
            lease.foreign_titles_known = True
            lease.foreign_titles = set()
            self.assertFalse(lease.prove_exclusive(5, notepad))
            with self.assertRaises(SessionOwnershipError):
                sw_session.terminate_owned_process(lease)
            lease.foreign_titles = {"User.SLDPRT"}
            lease.probe = _probe_sldworks
            self.assertFalse(lease.prove_exclusive(5, _probe_sldworks))

        run_on_task_sta(job, timeout=3, task_name="bad-probe")

    def test_concurrent_task_is_refused_without_closing_docs(self) -> None:
        release = threading.Event()
        started = threading.Event()
        box: dict[str, object] = {}

        def hold() -> None:
            lease = current_lease()
            assert lease is not None
            lease.note_owned_document("Owned.SLDPRT", handle_id=7)
            lease.foreign_titles.add("User.SLDPRT")
            box["lease"] = lease
            started.set()
            self.assertTrue(release.wait(5))

        thread = threading.Thread(
            target=lambda: run_on_task_sta(hold, timeout=5, task_name="hold"),
            name="hold-task",
        )
        thread.start()
        try:
            self.assertTrue(started.wait(2))
            started_at = time.monotonic()
            with self.assertRaises(SessionOwnershipError) as caught:
                run_on_task_sta(lambda: None, timeout=2, task_name="second")
            self.assertLess(time.monotonic() - started_at, 0.5)
            self.assertIn("another task holds", str(caught.exception))
            lease = box["lease"]
            self.assertIn("Owned.SLDPRT", lease.owned_docs)
            self.assertEqual(lease.owned_docs["Owned.SLDPRT"].handle_id, 7)
            self.assertIn("User.SLDPRT", lease.foreign_titles)
        finally:
            release.set()
            thread.join(5)
        self.assertFalse(thread.is_alive())

    def test_recycle_without_exclusive_session_returns_immediately(self) -> None:
        calls: list[object] = []

        def boom(*args, **kwargs):
            calls.append(args)
            flat = " ".join(str(part) for part in args)
            if "taskkill" in flat or "SLDWORKS.exe" in flat:
                raise AssertionError(flat)
            raise FileNotFoundError("subprocess disabled in session test")

        original = batch_export._solidworks_memory_mb
        batch_export._solidworks_memory_mb = lambda: (4200.0, 100.0)
        import subprocess

        original_run = subprocess.run
        subprocess.run = boom
        try:
            started = time.monotonic()
            with self.assertRaises(SessionOwnershipError) as caught:
                batch_export._recycle_solidworks_if_heavy()
            self.assertLess(time.monotonic() - started, 0.5)
            self.assertIn("No verified exclusive session", str(caught.exception))
            self.assertEqual(calls, [])
            batch_export._solidworks_memory_mb = lambda: (10.0, 8000.0)
            self.assertFalse(batch_export._recycle_solidworks_if_heavy())
        finally:
            batch_export._solidworks_memory_mb = original
            subprocess.run = original_run

    def test_batch_export_records_refusal_and_still_builds_without_teardown(self) -> None:
        generated: list[str] = []
        messages: list[str] = []

        def fake_generate(*args, **kwargs):
            generated.append("called")
            return types.SimpleNamespace(
                path=Path("made.SLDPRT"),
                auto_bent=False,
                auto_bend_abandoned=False,
                auto_bend_attempts=0,
                bend_count=0,
                auto_bend_failed_count=0,
                cad_imported=False,
                bend_sketch_line_count=0,
            )

        original_memory = batch_export._solidworks_memory_mb
        original_generate = batch_export.generate_sheet_metal_with_relief_retries
        batch_export._solidworks_memory_mb = lambda: (5000.0, 100.0)
        batch_export.generate_sheet_metal_with_relief_retries = fake_generate
        try:
            job = batch_export.SheetPartJob(
                profile_index=0,
                bend_indices=(),
                area_mm2=1.0,
                label="件01",
                quantity=1,
                thickness_mm=2.0,
            )
            with tempfile.TemporaryDirectory() as folder:
                results = batch_export._export_jobs(
                    types.SimpleNamespace(path=Path("drawing.dwg"), bend_lines=[], primitives=(), profiles=()),
                    [(1, job)],
                    Path(folder),
                    2.0,
                    1.0,
                    90.0,
                    False,
                    None,
                    False,
                    messages.append,
                )
            self.assertEqual(generated, ["called"])
            self.assertTrue(results[0].ok)
            self.assertTrue(any("拒绝重启 SolidWorks" in message for message in messages))
        finally:
            batch_export._solidworks_memory_mb = original_memory
            batch_export.generate_sheet_metal_with_relief_retries = original_generate

    def test_generator_entrypoints_refuse_to_touch_com_for_local_errors(self) -> None:
        analysis = types.SimpleNamespace(profiles=[])
        with self.assertRaises(ValueError):
            swg.generate_sheet_metal(
                analysis,
                0,
                (),
                1.0,
                1.0,
                90.0,
                "missing-output.SLDPRT",
            )
        with self.assertRaises(swg.SolidWorksGenerationError) as caught:
            swg.export_flat_pattern_dxf("missing-part.sldprt", "flat.dxf")
        self.assertIn("找不到零件文件", str(caught.exception))

    def test_marshaling_shared_com_to_another_thread_is_refused(self) -> None:
        errors: list[BaseException] = []

        def job() -> None:
            lease = current_lease()
            assert lease is not None
            lease.shared_com_bound = True

            def other() -> None:
                try:
                    call_with_watchdog(1.0, lambda: None, lease=lease)
                except BaseException as error:  # noqa: BLE001
                    errors.append(error)

            thread = threading.Thread(target=other)
            thread.start()
            thread.join(2)

        run_on_task_sta(job, timeout=3, task_name="no-marshal")
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], SessionOwnershipError)
        self.assertIn("marshal", str(errors[0]))

    def test_exclusive_recycle_closes_only_owned_documents(self) -> None:
        def job() -> None:
            lease = current_lease()
            assert lease is not None
            app = FakeApp(["Part1"])
            _make_exclusive(lease, 19)
            lease.note_owned_document("Part1", handle_id=19)
            lease.app_for_recycle = app
            lease.list_open_titles = lambda application: list(application.titles)
            self.assertTrue(
                recycle_exclusive_session(private_mb=4000, commit_free_mb=100)
            )
            self.assertTrue(app.closed_all)
            self.assertTrue(app.exited)
            app.closed_all = False
            app.exited = False
            app.titles = ["Part1", "User.SLDPRT"]
            with self.assertRaises(SessionOwnershipError):
                recycle_exclusive_session(private_mb=4000, commit_free_mb=100)
            self.assertFalse(app.closed_all)
            self.assertFalse(app.exited)

        run_on_task_sta(job, timeout=3, task_name="exclusive-recycle")

    def test_automation_mode_requires_exclusive_proof(self) -> None:
        touched: dict[str, object] = {}

        class _ModeApp:
            @property
            def UserControl(self) -> object:
                return touched.get("user")

            @UserControl.setter
            def UserControl(self, value: object) -> None:
                touched["user"] = value

            @property
            def CommandInProgress(self) -> object:
                return touched.get("command")

            @CommandInProgress.setter
            def CommandInProgress(self, value: object) -> None:
                touched["command"] = value

        app = _ModeApp()

        def unproven() -> None:
            swg._set_sw_automation_mode(app, True)

        with self.assertRaises(SessionOwnershipError):
            run_on_task_sta(unproven, timeout=3, task_name="mode-unproven")
        self.assertNotIn("user", touched)
        self.assertNotIn("command", touched)

        def proven() -> None:
            lease = current_lease()
            assert lease is not None
            _make_exclusive(lease, 9)
            swg._set_sw_automation_mode(app, True)

        run_on_task_sta(proven, timeout=3, task_name="mode-proven")
        self.assertIs(touched["user"], False)
        self.assertIs(touched["command"], True)

    def test_turned_part_and_dwg_import_refuse_without_exclusive_session(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "drawing.dwg"
            source.write_bytes(b"not a real dwg")
            with self.assertRaises(SessionOwnershipError):
                dwg_converter.convert_dwg_with_solidworks(source, root / "drawing.dxf")
            with self.assertRaises(SessionOwnershipError):
                turned_part.generate_turned_part(object(), str(root / "turned.SLDPRT"))


if __name__ == "__main__":
    unittest.main()
