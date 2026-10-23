"""Issue #6 module 2: controlled-execution entry and refusal tests."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from src.ql5050px.solver import solve_spec
from src.sw_api.controlled import ExecutionRequest, refusals, run_controlled_execution


class ControlledExecutionTests(unittest.TestCase):
    def setUp(self):
        self.plan = solve_spec()
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)

    def request(self, **kwargs) -> ExecutionRequest:
        base = {
            "source": "simulated://QL-5050PX/unmapped-template",
            "destination": self.root / "trace.json",
            "plan": self.plan,
        }
        base.update(kwargs)
        return ExecutionRequest(**base)

    def conditions(self, request: ExecutionRequest) -> set[str]:
        return {row.condition for row in refusals(request)}

    def test_clean_mock_request_has_no_refusals(self):
        self.assertEqual(self.conditions(self.request()), set())

    def test_mock_dry_run_writes_trace_only(self):
        destination = self.root / "trace.json"
        report = run_controlled_execution(
            self.request(destination=destination),
        )
        self.assertEqual(report["status"], "mock_dry_run")
        self.assertEqual(report["backend"], "mock")
        self.assertFalse(report["cad_executed"])
        self.assertEqual(report["sw_live"], "not_applicable_on_linux")
        self.assertEqual(report["refusals"], [])
        payload = json.loads(destination.read_text(encoding="utf-8"))
        self.assertEqual(payload["backend"], "mock")
        self.assertFalse(payload["original_overwritten"])
        self.assertIn("variables_skipped_unresolved", payload["trace"])

    def test_mock_refuses_cad_product_suffix(self):
        report = run_controlled_execution(self.request(destination=self.root / "part.SLDPRT"))
        self.assertEqual(report["status"], "refused")
        self.assertIn("mock_trace_suffix", self.conditions(self.request(destination=self.root / "part.SLDPRT")))
        self.assertFalse((self.root / "part.SLDPRT").exists())

    def test_mock_requires_json_trace_suffix(self):
        request = self.request(destination=self.root / "trace.txt")
        self.assertEqual(self.conditions(request), {"mock_trace_suffix"})

    def test_refuses_existing_destination(self):
        destination = self.root / "trace.json"
        destination.write_text("keep me", encoding="utf-8")
        request = self.request(destination=destination)
        self.assertIn("destination_exists", self.conditions(request))
        report = run_controlled_execution(request)
        self.assertEqual(report["status"], "refused")
        self.assertEqual(destination.read_text(encoding="utf-8"), "keep me")

    def test_refuses_source_alias(self):
        source = self.root / "work-copy.json"
        source.write_text("{}", encoding="utf-8")
        request = self.request(source=str(source), destination=source)
        self.assertIn("distinct_copy", self.conditions(request))

    def test_live_request_refusals_are_explicit(self):
        request = self.request(live=True, destination=self.root / "copy.SLDASM")
        conditions = self.conditions(request)
        if sys.platform == "win32":
            # On Windows the platform check clears and every remaining live
            # precondition must be named explicitly. COM may or may not be
            # installed, so it is not asserted here.
            self.assertEqual(conditions, {"unconfirmed", "mapping_missing", "sw_exe_missing"})
        else:
            self.assertEqual(conditions, {"platform"})
        report = run_controlled_execution(request)
        self.assertEqual(report["status"], "refused")
        self.assertFalse(report["cad_executed"])
        self.assertFalse((self.root / "copy.SLDASM").exists())

    def test_live_request_never_touches_com_on_linux(self):
        # On non-win32 the platform refusal must short-circuit before the COM
        # backend is even imported.
        if sys.platform == "win32":
            self.skipTest("COM probe is expected on Windows")
        request = self.request(live=True, destination=self.root / "copy.SLDASM")
        run_controlled_execution(request)
        self.assertNotIn("src.sw_api.win32com_backend", sys.modules)

    def test_live_request_keeps_work_copy_rules(self):
        # A .json live destination would be refused for the suffix even on
        # Windows; on Linux the platform refusal arrives first.
        request = self.request(live=True, destination=self.root / "trace.json")
        conditions = self.conditions(request)
        if sys.platform == "win32":
            self.assertIn("work_copy_suffix", conditions)
        else:
            self.assertEqual(conditions, {"platform"})


if __name__ == "__main__":
    unittest.main()
