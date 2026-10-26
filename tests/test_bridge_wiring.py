"""Bridge wiring into run_plan S1/S2/S5 (Issue #25, next batch).

Mock only, Linux-safe: no SolidWorks, no named pipes, no C# compile.
The fake client below mirrors the bridge_client.BridgeClient interface
(call / teardown) from PR #26; it is NOT the real client, because this
branch stacks on PR #23 and the csharp-bridge/ tree lives on PR #26.
Mock success here is never native acceptance.
"""
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'src')]
import ezdxf
from bridge_wiring import BridgeWiring, TEARDOWN_STEPS, validate_bridge_evidence
from cad_analyzer import analyze_dxf
from sheet_metal_pipeline import build_plan, run_plan, MockSheetMetalPort


class FakeBridgeClient:
    """Scripted stand-in for bridge_client.BridgeClient.

    ``fail_hello`` / ``fail_spawn`` / ``fail_teardown`` hold an error
    message, or None for success. ``exit_code`` is the recorded process
    exit code (possibly nonzero: it is recorded, never assumed 0).
    """

    def __init__(self, *, exit_code=0, fail_hello=None, fail_spawn=None,
                 fail_teardown=None, fail_list_titles=None):
        self.exit_code = exit_code
        self.fail_hello = fail_hello
        self.fail_spawn = fail_spawn
        self.fail_teardown = fail_teardown
        self.fail_list_titles = fail_list_titles
        self.owned_titles = set()
        self.pid = 424242

    def call(self, method, params=None):
        if method == "hello":
            if self.fail_hello:
                raise RuntimeError(self.fail_hello)
            return {"bridge": "fake", "protocol": "sw-bridge/1"}
        if method == "spawn":
            if self.fail_spawn:
                raise RuntimeError(self.fail_spawn)
            return {"pid": self.pid, "owned": True}
        if method == "list_titles":
            if self.fail_list_titles:
                raise RuntimeError(self.fail_list_titles)
            return {"titles": sorted(self.owned_titles)}
        if method == "exit_app":
            if self.owned_titles:
                raise RuntimeError("refusing ExitApp while documents remain")
            return {"exit_requested": True}
        if method == "teardown_report":
            return {"exit_code": self.exit_code}
        raise ValueError("unknown method %r" % (method,))

    def teardown(self, owned_titles=()):
        if self.fail_teardown:
            raise RuntimeError(self.fail_teardown)
        steps = []
        remaining = list(owned_titles)
        for title in list(remaining):
            remaining.remove(title)
        steps.append({"stage": "S5", "event": "close_documents",
                      "owned_docs": remaining, "pid": self.pid, "elapsed_ms": 1})
        steps.append({"stage": "S5", "event": "enumerate_titles",
                      "owned_docs": [], "pid": self.pid, "elapsed_ms": 1})
        steps.append({"stage": "S5", "event": "exit_app",
                      "owned_docs": [], "pid": self.pid, "elapsed_ms": 1})
        steps.append({"stage": "S5", "event": "release_wrappers",
                      "owned_docs": [], "pid": self.pid, "elapsed_ms": 1})
        steps.append({"stage": "S5", "event": "process_exit",
                      "owned_docs": [], "pid": self.pid, "elapsed_ms": 1,
                      "exit_code": self.exit_code})
        order = [s["event"] for s in steps]
        assert order == list(TEARDOWN_STEPS), order
        return {"steps": steps, "exit_code": self.exit_code}


class WiringTests(unittest.TestCase):
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
        return build_plan(self.analysis, profile_index=self.outer,
                          thickness_mm=2.5, radius_mm=1, angle_degrees=90,
                          k_factor=.4, flip_direction=False, bends_confirmed=True)

    def ckpt_dir(self, result):
        # After a successful run, checkpoints live in the hidden sibling
        # dir next to the published destination.
        out = Path(result['output_dir'])
        return out.parent / ('.' + out.name + '.ckpt')

    def ckpt(self, result, stage):
        return json.loads((self.ckpt_dir(result) / ('ckpt-' + stage + '.json')).read_text())

    def test_bridge_available_records_s1_s2_s5_evidence(self):
        wiring = BridgeWiring(FakeBridgeClient(), channel="bridge")
        result = run_plan(self.analysis, self.plan(), self.root / 'out',
                          MockSheetMetalPort(), bridge=wiring)
        self.assertEqual(result['status'], 'simulated_pass')
        # Bridge evidence must NOT upgrade a simulated run.
        self.assertFalse(result['sw_live_verified'])
        s1 = self.ckpt(result, 'S1')['evidence']['bridge']
        self.assertEqual(s1['grade'], 'bridge')
        self.assertEqual(s1['channel'], 'bridge')
        self.assertEqual(s1['session']['pid'], 424242)
        self.assertTrue(validate_bridge_evidence(s1))
        s2 = self.ckpt(result, 'S2')['evidence']['bridge']
        self.assertEqual(s2['grade'], 'bridge')
        self.assertEqual(s2['open_titles'], [])
        self.assertTrue(validate_bridge_evidence(s2))
        s5 = self.ckpt(result, 'S5')['evidence']['bridge']
        self.assertEqual(s5['grade'], 'bridge')
        self.assertEqual(s5['exit_code'], 0)
        self.assertTrue(s5['ok'])
        self.assertEqual([s['event'] for s in s5['teardown_steps']],
                         list(TEARDOWN_STEPS))
        self.assertTrue(validate_bridge_evidence(s5))

    def test_bridge_nonzero_exit_code_is_recorded_not_assumed(self):
        wiring = BridgeWiring(FakeBridgeClient(exit_code=0xC0000005), channel="bridge")
        result = run_plan(self.analysis, self.plan(), self.root / 'out',
                          MockSheetMetalPort(), bridge=wiring)
        s5 = self.ckpt(result, 'S5')['evidence']['bridge']
        self.assertEqual(s5['exit_code'], 0xC0000005)
        self.assertFalse(s5['ok'])
        # The artifact still landed (teardown evidence is not unpublishing),
        # but acceptance readers must see the nonzero exit code.
        self.assertEqual(result['status'], 'simulated_pass')

    def test_bridge_unavailable_falls_back_without_crash_package(self):
        wiring = BridgeWiring(FakeBridgeClient(fail_hello="pipe not found"),
                              channel="bridge")
        out = self.root / 'out'
        result = run_plan(self.analysis, self.plan(), out,
                          MockSheetMetalPort(), bridge=wiring)
        self.assertEqual(result['status'], 'simulated_pass')
        for stage in ('S1', 'S2', 'S5'):
            block = self.ckpt(result, stage)['evidence']['bridge']
            self.assertEqual(block['grade'], 'mock')
            self.assertIn('fallback_reason', block)
            self.assertTrue(validate_bridge_evidence(block))
        # Plain unavailability is fallback, not failure: no crash package.
        self.assertEqual(list(out.glob('crash-*.json')), [])

    def test_bridge_timeout_falls_back(self):
        wiring = BridgeWiring(
            FakeBridgeClient(fail_spawn="bridge request spawn timed out after 30s"),
            channel="bridge")
        out = self.root / 'out'
        result = run_plan(self.analysis, self.plan(), out,
                          MockSheetMetalPort(), bridge=wiring)
        self.assertEqual(result['status'], 'simulated_pass')
        s1 = self.ckpt(result, 'S1')['evidence']['bridge']
        self.assertEqual(s1['grade'], 'mock')
        self.assertIn('timed out', s1['fallback_reason'])
        # No session was ever established, so S5 teardown is skipped
        # fallback too -- and still no crash package.
        s5 = self.ckpt(result, 'S5')['evidence']['bridge']
        self.assertEqual(s5['grade'], 'mock')
        self.assertEqual(list(out.glob('crash-*.json')), [])

    def test_bridge_teardown_failure_keeps_artifact_and_writes_crash_package(self):
        wiring = BridgeWiring(FakeBridgeClient(fail_teardown="teardown blew up"),
                              channel="bridge")
        out = self.root / 'out'
        result = run_plan(self.analysis, self.plan(), out,
                          MockSheetMetalPort(), bridge=wiring)
        # The artifact already landed: teardown failure does NOT unpublish.
        self.assertEqual(result['status'], 'simulated_pass')
        self.assertTrue(Path(result['output_dir'], 'part.trace.json').is_file())
        s5 = self.ckpt(result, 'S5')['evidence']
        self.assertEqual(s5['bridge']['grade'], 'mock')
        self.assertIn('teardown blew up', s5['bridge']['fallback_reason'])
        self.assertIn('bridge_teardown_crash_package', s5)
        crash = json.loads(Path(s5['bridge_teardown_crash_package']).read_text())
        self.assertEqual(crash['plan_id'], self.plan()['plan_id'])
        self.assertIn('teardown blew up', crash['error'])

    def test_bridge_evidence_shape_and_no_invented_parameters(self):
        wiring = BridgeWiring(FakeBridgeClient(), channel="bridge")
        result = run_plan(self.analysis, self.plan(), self.root / 'out',
                          MockSheetMetalPort(), bridge=wiring)
        for stage in ('S1', 'S2', 'S5'):
            block = self.ckpt(result, stage)['evidence']['bridge']
            self.assertTrue(validate_bridge_evidence(block))
            # The wiring records no per-job parameters of its own.
            for forbidden in ('thickness_mm', 'radius_mm', 'angle_degrees', 'k_factor'):
                self.assertNotIn(forbidden, block)
        # The validator itself rejects bad shapes.
        with self.assertRaises(ValueError):
            validate_bridge_evidence({'grade': 'native', 'stage': 'S1', 'channel': 'bridge'})
        with self.assertRaises(ValueError):
            validate_bridge_evidence({'grade': 'bridge', 'stage': 'S1', 'channel': 'mock'})
        with self.assertRaises(ValueError):
            validate_bridge_evidence({'grade': 'bridge', 'stage': 'S5', 'channel': 'bridge'})
        with self.assertRaises(ValueError):
            validate_bridge_evidence({'grade': 'mock', 'stage': 'S1', 'channel': 'mock',
                                      'thickness_mm': 2.5})

    def test_resume_keeps_bridge_evidence(self):
        wiring = BridgeWiring(FakeBridgeClient(), channel="bridge")
        first = run_plan(self.analysis, self.plan(), self.root / 'out',
                         MockSheetMetalPort(), bridge=wiring)
        self.assertEqual(first['status'], 'simulated_pass')
        second = run_plan(self.analysis, self.plan(), self.root / 'out',
                          MockSheetMetalPort(), bridge=wiring)
        self.assertTrue(second['resumed'])
        # The resumed run returns early; the first run's bridge evidence
        # in the checkpoint dir is untouched.
        s5 = self.ckpt(first, 'S5')['evidence']['bridge']
        self.assertEqual(s5['grade'], 'bridge')
        self.assertEqual(s5['exit_code'], 0)

    def test_no_bridge_is_exact_old_behavior(self):
        result = run_plan(self.analysis, self.plan(), self.root / 'out',
                          MockSheetMetalPort())
        self.assertEqual(result['status'], 'simulated_pass')
        self.assertNotIn('bridge', self.ckpt(result, 'S1')['evidence'])
        self.assertNotIn('bridge', self.ckpt(result, 'S2')['evidence'])
        self.assertNotIn('bridge', self.ckpt(result, 'S5')['evidence'])


if __name__ == '__main__':
    unittest.main()
