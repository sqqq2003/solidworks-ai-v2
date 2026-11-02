"""Callout fallback and attach-only acceptance. No SolidWorks process is started."""
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import sw_owned_launch as launch
import sw_session
from owned_document_lifetime import finish_owned_session
from ql5050px.com_selection import (
    CALLOUT_POLICY_NOTE,
    callout_pair,
    callout_status,
    is_gen_py_early_bound,
    reset_callout_state_for_tests,
    select_by_id,
)
from sw_session import ProcessProbeInfo, SessionOwnershipError


def _modules(nothing):
    client = SimpleNamespace(VARIANT=lambda tag, value: ("variant", tag, value))
    return {
        "pythoncom": SimpleNamespace(VT_DISPATCH=9, Nothing=nothing),
        "win32com": SimpleNamespace(client=client),
        "win32com.client": client,
    }


def _early_extension(select):
    class Extension:
        def SelectByID2(self, *args):
            return select(*args)
    Extension.__module__ = "win32com.gen_py.fixture"
    return Extension()


class CalloutPolicyTests(unittest.TestCase):
    def setUp(self):
        reset_callout_state_for_tests()
        self.addCleanup(reset_callout_state_for_tests)

    def test_early_bound_uses_none_and_late_bound_uses_nothing(self):
        self.assertIn("win32com.gen_py", CALLOUT_POLICY_NOTE)
        self.assertIn("pythoncom.Nothing", CALLOUT_POLICY_NOTE)
        self.assertIn("once", CALLOUT_POLICY_NOTE)
        late_seen = []

        class Late:
            def SelectByID2(self, *args):
                late_seen.append(args)
                return True

        nothing = object()
        self.assertFalse(is_gen_py_early_bound(Late()))
        self.assertEqual(callout_pair(Late()), ("nothing", "bare_none"))
        with patch.dict(sys.modules, _modules(nothing)):
            self.assertTrue(select_by_id(Late(), "Front Plane", "PLANE"))
        self.assertEqual(len(late_seen), 1)
        self.assertIs(late_seen[0][7], nothing)
        self.assertEqual(callout_status()["accepted"], "nothing")

        reset_callout_state_for_tests()
        early_seen = []

        def early_select(*args):
            early_seen.append(args)
            return True

        early = _early_extension(early_select)
        self.assertTrue(is_gen_py_early_bound(early))
        self.assertEqual(callout_pair(early), ("bare_none", "nothing"))
        with patch.dict(sys.modules, _modules(nothing)):
            self.assertTrue(select_by_id(early, "Front Plane", "PLANE"))
        self.assertEqual(len(early_seen), 1)
        self.assertIsNone(early_seen[0][7])
        self.assertEqual(callout_status()["accepted"], "bare_none")

    def test_early_bound_swaps_to_nothing_once_when_none_cannot_marshal(self):
        nothing = object()
        seen = []

        def select(*args):
            if args[7] is None:
                raise ValueError("The Python instance can not be converted to a COM object")
            seen.append(args[7])
            return True

        with patch.dict(sys.modules, _modules(nothing)):
            self.assertTrue(select_by_id(_early_extension(select), "Front Plane", "PLANE"))
            self.assertTrue(select_by_id(_early_extension(select), "Top Plane", "PLANE"))
        self.assertEqual(seen, [nothing, nothing])

    def test_late_bound_swaps_to_none_once_on_type_mismatch(self):
        nothing = object()
        seen = []

        class Late:
            def SelectByID2(self, *args):
                if args[7] is nothing:
                    raise OSError(-2147352571, "Type mismatch.", None, None)
                seen.append(args[7])
                return True

        with patch.dict(sys.modules, _modules(nothing)):
            self.assertTrue(select_by_id(Late(), "Front Plane", "PLANE"))
        self.assertEqual(seen, [None])

    def test_false_and_other_errors_do_not_swap(self):
        nothing = object()
        calls = []

        class Late:
            def SelectByID2(self, *args):
                calls.append(args[7])
                return False

        with patch.dict(sys.modules, _modules(nothing)):
            self.assertIs(select_by_id(Late(), "Front Plane", "PLANE"), False)
        self.assertEqual(calls, [nothing])

        class Hard:
            def SelectByID2(self, *args):
                calls.append("hard")
                raise RuntimeError(-2147220995, "unspecified", None, None)

        calls.clear()
        with patch.dict(sys.modules, _modules(nothing)):
            with self.assertRaises(RuntimeError) as caught:
                select_by_id(Hard(), "Front Plane", "PLANE")
        self.assertEqual(calls, ["hard"])
        self.assertIsInstance(caught.exception.__cause__, RuntimeError)
        self.assertIn(CALLOUT_POLICY_NOTE, str(caught.exception))

    def test_both_sentinels_rejected_names_only_the_pair(self):
        class Late:
            def SelectByID2(self, *args):
                raise ValueError("The Python instance can not be converted to a COM object")

        with patch.dict(sys.modules, _modules(object())):
            with self.assertRaises(RuntimeError) as caught:
                select_by_id(Late(), "Front Plane", "PLANE")
        message = str(caught.exception)
        self.assertIn("callout tried nothing, bare_none", message)
        self.assertNotIn("vt_dispatch_none", message)
        self.assertIn(CALLOUT_POLICY_NOTE, message)


class AttachReuseTests(unittest.TestCase):
    def setUp(self):
        sw_session.reset_for_tests()
        self.addCleanup(sw_session.reset_for_tests)
        reset_callout_state_for_tests()
        self.addCleanup(reset_callout_state_for_tests)

    def test_acceptance_runner_source_attaches_and_does_not_spawn(self):
        api = (ROOT / "src" / "modeling_domain" / "api.py").read_text(encoding="utf-8")
        launch_source = (ROOT / "src" / "sw_owned_launch.py").read_text(encoding="utf-8")
        self.assertIn("attached_solidworks", api)
        self.assertNotIn("owned_solidworks", api)
        self.assertNotIn("new_process_alongside_existing", api)
        self.assertNotIn("taskkill", launch_source)
        self.assertNotIn(".kill(", launch_source)
        self.assertNotIn("P0_RETEST_ATTACH", launch_source)

    def test_bind_reuses_one_pid_closes_only_task_documents_and_refuses_exit(self):
        listing = ["装配体1"]
        closed = []
        killed = []

        def close_doc(title):
            closed.append(title)
            if title in listing:
                listing.remove(title)

        def exit_app():
            closed.append("exit")

        app = SimpleNamespace(
            GetProcessID=lambda: 43210,
            RevisionNumber="30.5.0",
            UserControl=True,
            CloseDoc=close_doc,
            ExitApp=exit_app,
        )
        lifetime = SimpleNamespace(
            pid=43210,
            executable=r"C:\Program Files\SOLIDWORKS\SLDWORKS.exe",
            process=SimpleNamespace(poll=lambda: None),
            probe=lambda pid: ProcessProbeInfo(
                43210, True, r"C:\Program Files\SOLIDWORKS\SLDWORKS.exe") if pid == 43210 else None,
            close=lambda: None,
        )

        def job():
            binding = launch.bind_attached(
                lifetime, lambda pid: app, lambda _app: 43210, lambda _app: list(listing), timeout=1)
            lease = sw_session.current_lease()
            self.assertTrue(lease.verified_exclusive)
            self.assertTrue(lease.attached_existing)
            self.assertTrue(lease.reuse_attached)
            self.assertTrue(lease.close_doc_only)
            self.assertFalse(lease.spawn_claimed)
            self.assertFalse(lease.created_by_task)
            self.assertEqual(lease.foreign_titles, set())
            self.assertEqual(lease.owned_docs, {})
            self.assertEqual(binding.closed_before_write, ["装配体1"])
            sw_session.require_model_write()
            got, created = binding.reconnect(lease)
            self.assertIs(got, app)
            self.assertFalse(created)
            evidence = binding.evidence()
            self.assertEqual(evidence["instance_mode"], "attach_existing_sldworks")
            self.assertFalse(evidence["spawn_alongside"])
            self.assertFalse(evidence["spawned"])
            self.assertFalse(evidence["exit_app"])
            self.assertFalse(evidence["process_killed"])
            self.assertEqual(evidence["native_verification"], "session_only_not_cad_acceptance")
            self.assertIn("win32com.gen_py", evidence["callout"]["policy"])
            self.assertEqual(evidence["closed_before_write"], ["装配体1"])
            listing.append("Work.SLDPRT")
            lease.note_owned_document("Work.SLDPRT")
            lease.close_doc_only = False
            with self.assertRaisesRegex(SessionOwnershipError, "CloseDoc-only"):
                sw_session.terminate_owned_process(lease, killer=killed.append)
            with self.assertRaisesRegex(SessionOwnershipError, "CloseDoc-only"):
                sw_session.exit_owned_application(lease, app)
            self.assertEqual(killed, [])
            self.assertEqual(closed, ["装配体1"])
            finish_owned_session(lease, binding)
            self.assertEqual(closed, ["装配体1", "Work.SLDPRT"])
            self.assertEqual(binding.cleanup_status, "left_open_keepalive")
            self.assertIsNone(binding.cleanup_error)
            self.assertNotIn("exit", closed)

        sw_session.run_on_task_sta(job, timeout=5, task_name="attach-reuse")

    def test_new_unowned_document_stops_writes_and_is_not_closed(self):
        listing = ["装配体1"]
        closed = []

        def close_doc(title):
            closed.append(title)
            if title in listing:
                listing.remove(title)

        app = SimpleNamespace(
            GetProcessID=lambda: 43210,
            RevisionNumber="33.0.0",
            UserControl=True,
            CloseDoc=close_doc,
            ExitApp=lambda: closed.append("exit"),
        )
        lifetime = SimpleNamespace(
            pid=43210,
            executable=r"C:\Program Files\SOLIDWORKS\SLDWORKS.exe",
            process=SimpleNamespace(poll=lambda: None),
            probe=lambda pid: ProcessProbeInfo(43210, True, "SLDWORKS.exe") if pid == 43210 else None,
        )

        def job():
            launch.bind_attached(
                lifetime, lambda pid: app, lambda _app: 43210, lambda _app: list(listing), timeout=1)
            self.assertEqual(closed, ["装配体1"])
            listing.append("Mystery.SLDPRT")
            with self.assertRaisesRegex(SessionOwnershipError, "left open and not closed"):
                sw_session.require_model_write()
            self.assertEqual(closed, ["装配体1"])
            self.assertNotIn("exit", closed)

        sw_session.run_on_task_sta(job, timeout=5, task_name="attach-unknown-doc")

    def test_zero_or_many_processes_do_not_spawn(self):
        opened = []

        def job(pids, pattern):
            with tempfile.TemporaryDirectory() as folder:
                exe = Path(folder) / "SLDWORKS.exe"
                exe.write_bytes(b"")
                with patch.object(launch.sys, "platform", "win32"), \
                     patch.object(launch, "_matching_sldworks_pids", return_value=pids), \
                     patch.object(launch, "_open_query_lifetime", side_effect=lambda *args: opened.append(args)), \
                     patch.object(launch, "WindowsProcessLifetime", side_effect=AssertionError("spawn")):
                    with self.assertRaisesRegex(SessionOwnershipError, pattern):
                        with launch.attached_solidworks(exe):
                            pass
            self.assertEqual(opened, [])

        sw_session.run_on_task_sta(lambda: job([], "will not start another"), timeout=5, task_name="attach-none")
        sw_session.reset_for_tests()
        sw_session.run_on_task_sta(lambda: job([4, 5], "refusing to guess"), timeout=5, task_name="attach-many")

    def test_one_process_uses_query_lifetime_not_a_new_process(self):
        lifetime = SimpleNamespace(pid=43210, close=lambda: setattr(lifetime, "closed", True), closed=False)
        binding = SimpleNamespace(cleanup_error=None, evidence=lambda: {"instance_mode": "attach_existing_sldworks"})

        def job():
            with tempfile.TemporaryDirectory() as folder:
                exe = Path(folder) / "SLDWORKS.exe"
                exe.write_bytes(b"")
                pythoncom = SimpleNamespace(PumpWaitingMessages=lambda: None)
                with patch.dict(sys.modules, {"pythoncom": pythoncom}), \
                     patch.object(launch.sys, "platform", "win32"), \
                     patch.object(launch, "_matching_sldworks_pids", return_value=[43210]), \
                     patch.object(launch, "_open_query_lifetime", return_value=lifetime) as opened, \
                     patch.object(launch, "bind_attached", return_value=binding) as bound, \
                     patch.object(launch, "WindowsProcessLifetime", side_effect=AssertionError("spawn")), \
                     patch("owned_document_lifetime.finish_owned_session") as finish, \
                     patch("owned_document_lifetime.release_closed_session_references"):
                    with launch.attached_solidworks(exe) as got:
                        self.assertIs(got, binding)
                    opened.assert_called_once()
                    bound.assert_called_once()
                    finish.assert_called_once()
                    self.assertTrue(lifetime.closed)

        sw_session.run_on_task_sta(job, timeout=5, task_name="attach-one")

    def test_discover_does_not_dispatch_a_progid(self):
        client = SimpleNamespace(
            GetActiveObject=lambda progid: SimpleNamespace(GetProcessID=lambda: 43210),
            Dispatch=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("Dispatch must not start SolidWorks")),
        )
        com = SimpleNamespace(
            GetRunningObjectTable=lambda: SimpleNamespace(EnumRunning=lambda: []),
            CreateBindCtx=lambda _flags: object(),
            IID_IDispatch=object(),
        )
        modules = {"pythoncom": com, "win32com": SimpleNamespace(client=client), "win32com.client": client}
        with patch.dict(sys.modules, modules):
            found = launch._discover_attached(43210)
        self.assertEqual(found.GetProcessID(), 43210)
        client = SimpleNamespace(
            GetActiveObject=lambda progid: SimpleNamespace(GetProcessID=lambda: 7),
            Dispatch=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("Dispatch must not start SolidWorks")),
        )
        modules["win32com"] = SimpleNamespace(client=client)
        modules["win32com.client"] = client
        with patch.dict(sys.modules, modules):
            self.assertIsNone(launch._discover_attached(43210))
        client = SimpleNamespace(
            GetActiveObject=lambda progid: (_ for _ in ()).throw(OSError("absent")),
            Dispatch=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("Dispatch must not start SolidWorks")),
        )
        modules["win32com"] = SimpleNamespace(client=client)
        modules["win32com.client"] = client
        with patch.dict(sys.modules, modules):
            self.assertIsNone(launch._discover_attached(43210))


if __name__ == "__main__":
    unittest.main()
