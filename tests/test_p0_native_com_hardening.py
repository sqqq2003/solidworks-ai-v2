"""Offline contracts for the Windows r2 native failures. No SolidWorks process."""
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import sw_session
from part_verification import (
    PostSaveComDisconnect,
    post_save_status,
    rebind_model_after_save,
)
from ql5050px.com_selection import select_by_id
from ql5050px.editable_features import EditableFeaturesMixin
from ql5050px.native_machine import math_transform
from sw_feature_calls import (
    NORMAL_CUT_INDEX,
    sheet_metal_through_cut,
    solid_blind_cut,
    solid_blind_extrude,
)
from sw_math_arrays import create_point, double_array
from sw_owned_launch import bind_spawned
from sw_session import (
    ComSessionDisconnected,
    ProcessProbeInfo,
    SessionOwnershipError,
    is_com_server_disconnect,
    release_task_documents,
)
import solidworks_generator as sw


class _Lifetime:
    pid = 43210
    executable = r"C:\Program Files\SOLIDWORKS\SLDWORKS.exe"

    def probe(self, pid):
        if pid == self.pid:
            return ProcessProbeInfo(self.pid, True, self.executable)
        return None


def _variant_modules():
    client = SimpleNamespace(VARIANT=lambda tag, value: ("variant", tag, value))
    return {
        "pythoncom": SimpleNamespace(VT_ARRAY=0x2000, VT_R8=5, VT_DISPATCH=9),
        "win32com": SimpleNamespace(client=client),
        "win32com.client": client,
    }


class SafeArrayTests(unittest.TestCase):
    def test_double_array_is_typed_and_rejects_bad_values(self):
        with patch.dict(sys.modules, _variant_modules()):
            wrapped = double_array((1, 2.5, 3), 3)
            self.assertEqual(wrapped, ("variant", 0x2005, (1.0, 2.5, 3.0)))
            self.assertIs(type(wrapped[2][0]), float)
            point = create_point(SimpleNamespace(CreatePoint=lambda payload: payload), (4, 5, 6))
            self.assertEqual(point[0], "variant")
            transform = math_transform(
                SimpleNamespace(CreateTransform=lambda payload: payload),
                (1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0),
            )
            self.assertEqual(transform[1], 0x2005)
            self.assertEqual(len(transform[2]), 16)
        for bad in (
            (1, 2),
            (1, float("nan"), 0),
            (True, 0, 0),
            ("1", "2", "3"),
            [1] * 15,
        ):
            with self.assertRaises(ValueError):
                double_array(bad, 3 if len(bad) == 3 else 16)

    def test_generator_point_uses_the_same_helper(self):
        with patch.dict(sys.modules, _variant_modules()):
            self.assertEqual(sw._native_point_array((1, 2, 3)), ("variant", 0x2005, (1.0, 2.0, 3.0)))
        with self.assertRaises(sw.NativeSketchTransformError):
            sw._native_point_array((0, float("nan"), 0))


class PlateBracketCallTests(unittest.TestCase):
    def test_selection_callout_is_null_dispatch(self):
        seen = []

        class Extension:
            def SelectByID2(self, *args):
                seen.append(args)
                return True

        with patch.dict(sys.modules, _variant_modules()):
            self.assertTrue(select_by_id(Extension(), "Front Plane", "PLANE"))
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0][2:5], (0.0, 0.0, 0.0))
        self.assertEqual(seen[0][7], ("variant", 9, None))
        self.assertIs(type(seen[0][8]), int)

    def test_solid_cut_is_not_the_sheet_metal_call(self):
        recorded = {}

        class Manager:
            def FeatureExtrusion2(self, *args):
                recorded["extrude"] = args
                return SimpleNamespace(Name="boss")

            def FeatureCut3(self, *args):
                recorded.setdefault("cuts", []).append(args)
                return SimpleNamespace(Name="hole")

        class Model:
            FeatureManager = Manager()

            class Extension:
                def SelectByID2(self, *args):
                    return True

            def ClearSelection2(self, _flag):
                return None

        class Host(EditableFeaturesMixin):
            model = Model()

            def guard(self):
                return None

        sketch = {"sketch": "profile", "depth_mm": 8}
        with patch.dict(sys.modules, _variant_modules()):
            Host().create_editable_feature(
                {"id": "base", "kind": "extrude", "confirmed": True, "evidence": "reviewed", "parameters": sketch}
            )
            Host().create_editable_feature(
                {
                    "id": "holes",
                    "kind": "cut",
                    "confirmed": True,
                    "evidence": "reviewed",
                    "parameters": {**sketch, "reverse": False},
                }
            )
        extrude = recorded["extrude"]
        self.assertIs(extrude[17], False)
        self.assertIs(type(extrude[5]), float)
        self.assertIs(type(extrude[6]), float)
        self.assertIs(type(extrude[21]), float)
        cut = recorded["cuts"][0]
        self.assertIs(cut[NORMAL_CUT_INDEX], False)
        for index in (5, 6, 11, 12, 24):
            self.assertIs(type(cut[index]), float)
        sheet = []
        sheet_metal_through_cut(SimpleNamespace(FeatureCut3=lambda *args: sheet.append(args) or object()))
        self.assertIs(sheet[0][NORMAL_CUT_INDEX], True)
        self.assertIs(cut[NORMAL_CUT_INDEX], False)
        with self.assertRaises(TypeError):
            solid_blind_cut(Manager(), "8", reverse=False)
        with self.assertRaises(TypeError):
            solid_blind_extrude(Manager(), 0.01, merge=1)

    def test_r2_hresult_is_a_disconnect(self):
        error = RuntimeError(-2147220995, "unspecified", None, None)
        self.assertTrue(is_com_server_disconnect(error))
        self.assertTrue(sw._is_com_disconnect_error(error))
        self.assertTrue(is_com_server_disconnect(RuntimeError("对象没有连接到服务器")))


class ShaftRebindTests(unittest.TestCase):
    def test_stale_pointer_after_save_is_not_a_pass(self):
        class DeadApp:
            def ActiveDoc(self):
                raise RuntimeError(-2147220995, "对象没有连接到服务器", None, None)

        lease = SimpleNamespace(disconnected=False, writes_blocked=False, verified_exclusive=True)
        with self.assertRaises(PostSaveComDisconnect) as caught:
            rebind_model_after_save(
                DeadApp(),
                lambda app: app.ActiveDoc(),
                lambda model: model.GetTitle(),
                lease=lease,
            )
        self.assertTrue(lease.disconnected)
        self.assertTrue(lease.writes_blocked)
        self.assertIn("post-save", str(caught.exception))
        status = post_save_status(saved=True, disconnected=True)
        self.assertFalse(status["passed"])
        self.assertEqual(status["status"], "post_save_com_disconnected")
        self.assertEqual(status["native_acceptance"], "pending_windows_validation")
        self.assertFalse(status["exit_app"])
        self.assertFalse(status["process_killed"])
        with self.assertRaises(AssertionError):
            post_save_status(saved=True, disconnected=True, exit_app=True)

    def test_rebind_returns_the_live_document_not_the_pre_save_pointer(self):
        fresh = SimpleNamespace(title="SavedPart")
        stale = SimpleNamespace(title="Part1")
        model, title = rebind_model_after_save(
            SimpleNamespace(ActiveDoc=lambda: fresh),
            lambda app: app.ActiveDoc(),
            lambda rebound: rebound.title,
            lease=None,
        )
        self.assertIs(model, fresh)
        self.assertIsNot(model, stale)
        self.assertEqual(title, "SavedPart")
        pending = post_save_status(saved=True, disconnected=False)
        self.assertFalse(pending["passed"])
        self.assertEqual(pending["status"], "saved_pending_reopen")

    def test_close_after_objnotconnected_does_not_exit_app(self):
        class App:
            def __init__(self):
                self.exited = False

            def CloseDoc(self, _title):
                raise RuntimeError(-2147220995, "unspecified", None, None)

            def ExitApp(self):
                self.exited = True

        app = App()

        def job():
            lease = sw_session.current_lease()
            lease.spawn_claimed = True
            lease.spawned_pid = 77
            lease.observed_pid = 77
            lease.attached_existing = False
            lease.created_by_task = True
            lease.foreign_titles = set()
            lease.foreign_titles_known = True
            lease.poisoned = False
            lease.probe = lambda pid: ProcessProbeInfo(pid, True, "SLDWORKS.exe")
            self.assertTrue(lease.prove_exclusive(77, lease.probe))
            lease.keep_application_open = False
            lease.note_bound_application(app)
            lease.note_owned_document("Part1")
            lease.list_open_titles = lambda _application: []
            release_task_documents(lease, app, title="Part1", close=True)
            self.assertTrue(lease.disconnected)
            self.assertFalse(app.exited)
            self.assertIsInstance(
                ComSessionDisconnected("marker"),
                SessionOwnershipError,
            )

        sw_session.reset_for_tests()
        self.addCleanup(sw_session.reset_for_tests)
        sw_session.run_on_task_sta(job, timeout=5, task_name="p0-objnotconnected")


class OwnedLaunchGateTests(unittest.TestCase):
    def test_gate_stays_strict_and_has_no_retest_attach_bypass(self):
        text = (ROOT / "src" / "sw_owned_launch.py").read_text(encoding="utf-8")
        self.assertNotIn("P0_RETEST_ATTACH", text)
        self.assertNotIn("taskkill", text)
        self.assertNotIn(".kill(", text)

        def job():
            lifetime = _Lifetime()
            bind_spawned(lifetime, lambda pid: object(), lambda app: lifetime.pid, lambda app: [], timeout=1)
            with self.assertRaises(SessionOwnershipError):
                bind_spawned(lifetime, lambda pid: object(), lambda app: lifetime.pid, lambda app: [], timeout=1)
            self.assertFalse(sw_session.current_lease().attached_existing)

        sw_session.reset_for_tests()
        self.addCleanup(sw_session.reset_for_tests)
        sw_session.run_on_task_sta(job, timeout=5, task_name="p0-owned-gate")

        def foreign():
            with self.assertRaises(SessionOwnershipError):
                bind_spawned(_Lifetime(), lambda pid: object(), lambda app: 1, lambda app: [], timeout=0.01)

        sw_session.reset_for_tests()
        sw_session.run_on_task_sta(foreign, timeout=5, task_name="p0-foreign-pid")


if __name__ == "__main__":
    unittest.main()
