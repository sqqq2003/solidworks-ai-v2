"""Bridge build / reopen methods wired into run_plan S1/S2 (Issue #25 batch 2).

Mock only, Linux-safe: no SolidWorks, no named pipes, no C# compile.
The fake client below mirrors bridge_client.BridgeClient (call / teardown)
plus the new build / reopen methods; it is NOT the real client.
Mock success here is never native acceptance.

Two fake flavours:
- FakeBridgeClient: supports build / reopen (writes a mock part file on
  build, exactly as the contract requires the bridge to save to part_path).
- OldFakeBridgeClient: predates build / reopen (raises unknown method),
  proving run_plan keeps the old session-proof evidence shape.
"""
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'src')]
sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'csharp-bridge' / 'python')]
import ezdxf
from bridge_wiring import (BridgeWiring, TEARDOWN_STEPS, idempotency_key,
                           validate_bridge_evidence)
from bridge_client import (BridgeClient, MockTransport, MissingParameterError,
                           BridgeTimeoutError, MOCK_READBACK)
from cad_analyzer import analyze_dxf
from run_recovery import read_checkpoints, validate_checkpoint_chain
from sheet_metal_pipeline import (build_plan, run_plan, validate_native,
                                  MockSheetMetalPort)


class FakeBridgeClient:
    """Scripted stand-in for bridge_client.BridgeClient with build/reopen."""

    def __init__(self, *, exit_code=0, fail_hello=None, fail_spawn=None,
                 fail_build=None, fail_reopen=None, write_part=True):
        self.exit_code = exit_code
        self.fail_hello = fail_hello
        self.fail_spawn = fail_spawn
        self.fail_build = fail_build
        self.fail_reopen = fail_reopen
        self.write_part = write_part
        self.owned_titles = set()
        self.pid = 424242
        self.build_results = {}
        self.last_build_params = None

    def call(self, method, params=None):
        params = params or {}
        if method == "hello":
            if self.fail_hello:
                raise RuntimeError(self.fail_hello)
            return {"bridge": "fake", "protocol": "sw-bridge/1"}
        if method == "spawn":
            if self.fail_spawn:
                raise RuntimeError(self.fail_spawn)
            return {"pid": self.pid, "owned": True}
        if method == "list_titles":
            return {"titles": sorted(self.owned_titles)}
        if method == "build":
            if self.fail_build:
                raise RuntimeError(self.fail_build)
            key = params.get("idempotency_key")
            if key in self.build_results:
                return self.build_results[key]
            title = params["title"]
            self.owned_titles.add(title)
            self.last_build_params = dict(params)
            if self.write_part:
                Path(params["part_path"]).write_text(
                    json.dumps({"mock": True, "title": title}))
            result = {"title": title, "owned": True,
                      "bend_count": params["bend_count"],
                      "auto_bent": True, "auto_bend_failed_count": 0,
                      "part": title}
            self.build_results[key] = result
            return result
        if method == "reopen":
            if self.fail_reopen:
                raise RuntimeError(self.fail_reopen)
            result = dict(MOCK_READBACK)
            result["title"] = params["title"]
            return result
        if method == "exit_app":
            if self.owned_titles:
                raise RuntimeError("refusing ExitApp while documents remain")
            return {"exit_requested": True}
        if method == "teardown_report":
            return {"exit_code": self.exit_code}
        raise ValueError("unknown method %r" % (method,))

    def teardown(self, owned_titles=()):
        steps = []
        for event in TEARDOWN_STEPS:
            entry = {"stage": "S5", "event": event, "owned_docs": [],
                     "pid": self.pid, "elapsed_ms": 1}
            if event == "process_exit":
                entry["exit_code"] = self.exit_code
            steps.append(entry)
        return {"steps": steps, "exit_code": self.exit_code}


class OldFakeBridgeClient:
    """Predates build / reopen: call raises unknown method for them."""

    def __init__(self):
        self.owned_titles = set()
        self.pid = 424242
        self.exit_code = 0

    def call(self, method, params=None):
        if method == "hello":
            return {"bridge": "fake", "protocol": "sw-bridge/1"}
        if method == "spawn":
            return {"pid": self.pid, "owned": True}
        if method == "list_titles":
            return {"titles": sorted(self.owned_titles)}
        if method == "exit_app":
            return {"exit_requested": True}
        if method == "teardown_report":
            return {"exit_code": self.exit_code}
        raise ValueError("unknown method %r" % (method,))

    def teardown(self, owned_titles=()):
        steps = [{"stage": "S5", "event": event, "owned_docs": [],
                  "pid": self.pid, "elapsed_ms": 1} for event in TEARDOWN_STEPS]
        steps[-1]["exit_code"] = self.exit_code
        return {"steps": steps, "exit_code": self.exit_code}


class BuildReopenTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'synthetic.dxf'
        doc = ezdxf.new('R2010')
        doc.units = ezdxf.units.MM
        space = doc.modelspace()
        space.add_lwpolyline([(0, 0), (100, 0), (100, 80), (0, 80)], close=True)
        space.add_circle((20, 20), 4)
        doc.layers.new('BEND', dxfattribs={'color': 1})
        space.add_line((50, 0), (50, 80), dxfattribs={'layer': 'BEND', 'color': 1})
        doc.saveas(self.source)
        self.analysis = analyze_dxf(self.source)
        self.outer = max(range(len(self.analysis.profiles)),
                         key=lambda i: len(self.analysis.profiles[i].points)
                         if self.analysis.profiles[i].kind != 'CIRCLE' else 0)

    def plan(self):
        # Parameters deliberately equal the mock canned readback so a
        # bridge readback passes validate_native on purpose.
        return build_plan(self.analysis, profile_index=self.outer,
                          thickness_mm=2.5, radius_mm=1, angle_degrees=90,
                          k_factor=.4, flip_direction=False, bends_confirmed=True)

    def ckpt_dir(self, result):
        out = Path(result['output_dir'])
        return out.parent / ('.' + out.name + '.ckpt')

    def ckpt(self, result, stage):
        return json.loads((self.ckpt_dir(result) / ('ckpt-' + stage + '.json')).read_text())

    # --- Python client: build / reopen contract ----------------------

    def test_client_build_missing_parameter_is_pending_not_default(self):
        client = BridgeClient(MockTransport())
        with self.assertRaises(MissingParameterError) as ctx:
            client.build(plan_id="p", title="t.SLDPRT", part_path="/tmp/x",
                         thickness_mm=2.5, radius_mm=1, angle_degrees=90,
                         k_factor=None, flip_direction=False, bend_count=1)
        self.assertEqual(ctx.exception.status, "pending_confirmation")
        self.assertIn("k_factor", ctx.exception.missing)

    def test_client_build_rejects_out_of_range(self):
        client = BridgeClient(MockTransport())
        with self.assertRaises(ValueError):
            client.build(plan_id="p", title="t.SLDPRT", part_path="/tmp/x",
                         thickness_mm=2.5, radius_mm=1, angle_degrees=90,
                         k_factor=1.5, flip_direction=False, bend_count=1)
        with self.assertRaises(ValueError):
            client.build(plan_id="p", title="t.SLDPRT", part_path="/tmp/x",
                         thickness_mm=2.5, radius_mm=1, angle_degrees=90,
                         k_factor=.4, flip_direction="yes", bend_count=1)

    def test_client_build_roundtrip_and_idempotency(self):
        transport = MockTransport()
        client = BridgeClient(transport)
        kwargs = dict(plan_id="p", title="t.SLDPRT", part_path="/tmp/x",
                      thickness_mm=2.5, radius_mm=1, angle_degrees=90,
                      k_factor=.4, flip_direction=False, bend_count=1,
                      idempotency_key="key-1")
        first = client.build(**kwargs)
        self.assertEqual(first["title"], "t.SLDPRT")
        self.assertTrue(first["auto_bent"])
        self.assertEqual(first["auto_bend_failed_count"], 0)
        second = client.build(**kwargs)
        self.assertEqual(second, first)
        self.assertEqual(len(transport.build_results), 1)
        self.assertEqual(transport.last_build_params["part_path"], "/tmp/x")

    def test_client_build_timeout(self):
        client = BridgeClient(MockTransport(slow_s=0.05), timeout_s=0.01)
        with self.assertRaises(BridgeTimeoutError):
            client.build(plan_id="p", title="t.SLDPRT", part_path="/tmp/x",
                         thickness_mm=2.5, radius_mm=1, angle_degrees=90,
                         k_factor=.4, flip_direction=False, bend_count=1)

    def test_client_reopen_shape_and_validate_native_pass(self):
        client = BridgeClient(MockTransport())
        readback = client.reopen(plan_id="p", title="t.SLDPRT",
                                 part_path="/tmp/x")
        for key in ("reopened", "rebuilt", "feature_types", "editable",
                    "thickness_mm", "radius_mm", "k_factor"):
            self.assertIn(key, readback)
        validate_native(self.plan(), readback)  # must not raise

    def test_validate_native_rejects_mismatched_readback(self):
        readback = dict(MOCK_READBACK)
        readback["k_factor"] = 0.5
        with self.assertRaises(RuntimeError):
            validate_native(self.plan(), readback)

    # --- run_plan wiring ----------------------------------------------

    def test_bridge_build_and_reopen_execute_via_bridge(self):
        fake = FakeBridgeClient()
        wiring = BridgeWiring(fake, channel="bridge")
        out = self.root / 'out'
        result = run_plan(self.analysis, self.plan(), out,
                          MockSheetMetalPort(), bridge=wiring)
        self.assertEqual(result['status'], 'simulated_pass')
        self.assertFalse(result['sw_live_verified'])
        s1 = self.ckpt(result, 'S1')['evidence']['bridge']
        self.assertEqual(s1['executed_via'], 'bridge')
        self.assertEqual(s1['grade'], 'bridge')
        self.assertTrue(s1['result']['auto_bent'])
        self.assertEqual(self.ckpt(result, 'S1')['evidence']['generation'],
                         s1['result'])
        self.assertTrue(validate_bridge_evidence(s1))
        # The bridge was only ever handed the run staging path.
        part_path = Path(fake.last_build_params["part_path"])
        self.assertEqual(part_path.parent.parent, out)
        self.assertEqual(part_path.name, 'part.trace.json')
        s2 = self.ckpt(result, 'S2')['evidence']['bridge']
        self.assertEqual(s2['executed_via'], 'bridge')
        self.assertEqual(s2['readback']['k_factor'], .4)
        self.assertTrue(validate_bridge_evidence(s2))
        # #30 guards intact: checkpoint chain validates, lock released.
        stage, _ = validate_checkpoint_chain(
            self.ckpt_dir(result), plan_id=self.plan()['plan_id'],
            code_sha256=self.plan()['code_sha256'],
            base_dir=Path(result['output_dir']))
        self.assertEqual(stage, 'S5')
        self.assertEqual(list(out.glob('.*.lock')), [])

    def test_bridge_build_failure_falls_back_to_port(self):
        fake = FakeBridgeClient(fail_build="build exploded")
        wiring = BridgeWiring(fake, channel="bridge")
        out = self.root / 'out'
        result = run_plan(self.analysis, self.plan(), out,
                          MockSheetMetalPort(), bridge=wiring)
        self.assertEqual(result['status'], 'simulated_pass')
        s1 = self.ckpt(result, 'S1')['evidence']['bridge']
        self.assertEqual(s1['executed_via'], 'port')
        self.assertIn('build exploded', s1['fallback_reason'])
        # Generation came from the port (mock port: auto_bent False).
        self.assertFalse(self.ckpt(result, 'S1')['evidence']['generation']['auto_bent'])
        self.assertEqual(list(out.glob('crash-*.json')), [])

    def test_bridge_reopen_failure_falls_back_to_port(self):
        fake = FakeBridgeClient(fail_reopen="reopen exploded")
        wiring = BridgeWiring(fake, channel="bridge")
        out = self.root / 'out'
        result = run_plan(self.analysis, self.plan(), out,
                          MockSheetMetalPort(), bridge=wiring)
        self.assertEqual(result['status'], 'simulated_pass')
        s1 = self.ckpt(result, 'S1')['evidence']['bridge']
        self.assertEqual(s1['executed_via'], 'bridge')
        s2 = self.ckpt(result, 'S2')['evidence']['bridge']
        self.assertEqual(s2['executed_via'], 'port')
        self.assertIn('reopen exploded', s2['fallback_reason'])
        self.assertTrue(validate_bridge_evidence(s2))

    def test_old_client_keeps_session_proof_shape(self):
        wiring = BridgeWiring(OldFakeBridgeClient(), channel="bridge")
        result = run_plan(self.analysis, self.plan(), self.root / 'out',
                          MockSheetMetalPort(), bridge=wiring)
        self.assertEqual(result['status'], 'simulated_pass')
        s1 = self.ckpt(result, 'S1')['evidence']['bridge']
        self.assertEqual(s1['grade'], 'bridge')
        self.assertEqual(s1['session']['pid'], 424242)
        self.assertEqual(s1['executed_via'], 'port')
        self.assertIn('unknown method', s1['fallback_reason'])
        self.assertTrue(validate_bridge_evidence(s1))
        s2 = self.ckpt(result, 'S2')['evidence']['bridge']
        self.assertEqual(s2['open_titles'], [])
        self.assertEqual(s2['executed_via'], 'port')
        self.assertTrue(validate_bridge_evidence(s2))

    def test_bridge_unavailable_falls_back_without_crash_package(self):
        fake = FakeBridgeClient(fail_hello="pipe not found")
        wiring = BridgeWiring(fake, channel="bridge")
        out = self.root / 'out'
        result = run_plan(self.analysis, self.plan(), out,
                          MockSheetMetalPort(), bridge=wiring)
        self.assertEqual(result['status'], 'simulated_pass')
        for stage in ('S1', 'S2'):
            block = self.ckpt(result, stage)['evidence']['bridge']
            self.assertEqual(block['executed_via'], 'port')
            self.assertEqual(block['grade'], 'mock')
            self.assertIn('fallback_reason', block)
            self.assertTrue(validate_bridge_evidence(block))
        self.assertEqual(list(out.glob('crash-*.json')), [])

    def test_bridge_build_success_without_part_file_is_hard_failure(self):
        fake = FakeBridgeClient(write_part=False)
        wiring = BridgeWiring(fake, channel="bridge")
        result = run_plan(self.analysis, self.plan(), self.root / 'out',
                          MockSheetMetalPort(), bridge=wiring)
        self.assertEqual(result['status'], 'failed')
        self.assertIn('part file missing', result['error'])

    # --- validator / keys / no-default scan ---------------------------

    def test_idempotency_key_deterministic(self):
        key = idempotency_key("plan-1", "S1", "build")
        self.assertEqual(key, idempotency_key("plan-1", "S1", "build"))
        self.assertNotEqual(key, idempotency_key("plan-1", "S2", "reopen"))
        self.assertNotEqual(key, idempotency_key("plan-2", "S1", "build"))

    def test_evidence_validator_new_rules(self):
        base = {"grade": "bridge", "channel": "bridge", "available": True,
                "session": {"pid": 1, "owned": True}}
        ok_s1 = dict(base, stage="S1", executed_via="bridge",
                     result={"title": "t", "auto_bent": True})
        self.assertTrue(validate_bridge_evidence(ok_s1))
        with self.assertRaises(ValueError):
            validate_bridge_evidence(dict(base, stage="S1",
                                          executed_via="bridge"))
        ok_s2 = dict(base, stage="S2", executed_via="bridge",
                     readback=dict(MOCK_READBACK))
        self.assertTrue(validate_bridge_evidence(ok_s2))
        with self.assertRaises(ValueError):
            validate_bridge_evidence(dict(base, stage="S2",
                                          executed_via="bridge",
                                          readback={"reopened": True}))
        with self.assertRaises(ValueError):
            validate_bridge_evidence(dict(base, stage="S1",
                                          executed_via="port"))
        with self.assertRaises(ValueError):
            validate_bridge_evidence(dict(base, stage="S2",
                                          executed_via="bridge",
                                          readback=dict(MOCK_READBACK),
                                          thickness_mm=2.5))
        with self.assertRaises(ValueError):
            validate_bridge_evidence(dict(base, stage="S1",
                                          executed_via="sideways",
                                          fallback_reason="x"))

    def test_no_default_constants_in_new_code(self):
        root = Path(__file__).resolve().parents[1]
        for name in ("src/bridge_wiring.py",
                     "csharp-bridge/python/bridge_client.py"):
            src = (root / name).read_text(encoding="utf-8")
            self.assertNotIn("DEFAULT_K", src, name)
            self.assertNotIn("DEFAULT_T", src, name)
            self.assertNotIn("MATERIAL_K_FACTORS", src, name)


if __name__ == '__main__':
    unittest.main()
