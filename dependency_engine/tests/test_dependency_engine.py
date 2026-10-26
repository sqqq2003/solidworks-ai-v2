"""Mock tests for the dependency precheck engine (Linux, stdlib only).

Run from the repository root:
    python3 -m unittest discover -s dependency_engine/tests -t .
"""

import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dependency_engine.engine import (
    CycleError,
    DuplicateNameError,
    InputError,
    precheck,
)

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def machine(params, parts=None, mates=None):
    return {
        "format": "dependency-engine/1",
        "name": "test-machine",
        "units": "mm",
        "parameters": params,
        "parts": parts or [],
        "mates": mates or [],
    }


def leaf(name, value, **extra):
    row = {"name": name, "unit": "mm", "value": value}
    row.update(extra)
    return row


class TestResolution(unittest.TestCase):
    def test_topological_order_and_values(self):
        report = precheck(
            machine(
                [
                    leaf("machine_width", 1000),
                    leaf("side_allowance", 30),
                    {
                        "name": "frame_width",
                        "unit": "mm",
                        "formula": {
                            "op": "subtract",
                            "args": ["machine_width", "side_allowance", "side_allowance"],
                        },
                    },
                    {"name": "beam", "unit": "mm", "formula": {"op": "copy", "args": ["frame_width"]}},
                ]
            )
        )
        self.assertEqual(report["status"], "ok")
        values = {p["name"]: p["value"] for p in report["parameters"]}
        self.assertEqual(values["frame_width"], 940.0)
        self.assertEqual(values["beam"], 940.0)
        order = report["resolution_order"]
        self.assertLess(order.index("machine_width"), order.index("frame_width"))
        self.assertLess(order.index("frame_width"), order.index("beam"))

    def test_cycle_rejected(self):
        with self.assertRaises(CycleError):
            precheck(
                machine(
                    [
                        {"name": "a", "unit": "mm", "formula": {"op": "copy", "args": ["b"]}},
                        {"name": "b", "unit": "mm", "formula": {"op": "copy", "args": ["a"]}},
                    ]
                )
            )

    def test_duplicate_name_rejected(self):
        with self.assertRaises(DuplicateNameError):
            precheck(machine([leaf("a", 1), leaf("a", 2)]))

    def test_missing_leaf_pending_and_propagates(self):
        report = precheck(
            machine(
                [
                    leaf("machine_width", 1000),
                    {"name": "side_allowance", "unit": "mm"},
                    {
                        "name": "frame_width",
                        "unit": "mm",
                        "formula": {
                            "op": "subtract",
                            "args": ["machine_width", "side_allowance", "side_allowance"],
                        },
                    },
                ]
            )
        )
        self.assertEqual(report["status"], "pending")
        by_name = {p["name"]: p for p in report["parameters"]}
        self.assertEqual(by_name["side_allowance"]["pending_reasons"], ["pending_mapping"])
        self.assertEqual(by_name["frame_width"]["status"], "pending_confirmation")
        self.assertIn("side_allowance", by_name["frame_width"]["pending_reasons"][0])
        self.assertIsNone(by_name["frame_width"]["value"])

    def test_unknown_reference_pending_not_crash(self):
        report = precheck(
            machine(
                [
                    {
                        "name": "x",
                        "unit": "mm",
                        "formula": {"op": "copy", "args": ["no_such_param"]},
                    }
                ]
            )
        )
        self.assertEqual(report["status"], "pending")
        self.assertIn("unknown_reference:no_such_param", report["parameters"][0]["pending_reasons"][0])

    def test_out_of_range_pending_never_clamped(self):
        report = precheck(
            machine(
                [
                    {"name": "k_factor", "unit": "unitless", "value": 1.4, "min": 0, "max": 1},
                ]
            )
        )
        param = report["parameters"][0]
        self.assertEqual(param["status"], "pending_confirmation")
        self.assertIn("out_of_range", param["pending_reasons"][0])
        # The offending value is reported, not silently clamped to 1.
        self.assertEqual(param["value"], 1.4)


class TestMates(unittest.TestCase):
    def _parts(self):
        return [
            {"id": "a", "uses_parameters": []},
            {"id": "b", "uses_parameters": []},
        ]

    def test_contradiction_error(self):
        report = precheck(
            machine(
                [leaf("width", 800)],
                parts=self._parts(),
                mates=[
                    {"id": "m1", "kind": "distance", "part_a": "a", "part_b": "b", "axis": "x", "value_param": "width"},
                    {"id": "m2", "kind": "distance", "part_a": "a", "part_b": "b", "axis": "x", "value_mm": 850},
                ],
            )
        )
        self.assertEqual(report["status"], "conflict")
        kinds = [c["kind"] for c in report["conflicts"] if c["severity"] == "error"]
        self.assertIn("contradiction", kinds)

    def test_redundant_same_value_warning_not_error(self):
        report = precheck(
            machine(
                [leaf("w", 100)],
                parts=self._parts(),
                mates=[
                    {"id": "m1", "kind": "distance", "part_a": "a", "part_b": "b", "axis": "x", "value_mm": 100},
                    {"id": "m2", "kind": "distance", "part_a": "a", "part_b": "b", "axis": "x", "value_mm": 100},
                ],
            )
        )
        self.assertEqual(report["status"], "ok")
        self.assertTrue(any(c["kind"] == "redundant_constraint" for c in report["conflicts"]))

    def test_coincident_compared_against_distance(self):
        # Coincident fixes all axes at 0, so a nonzero distance on the
        # same pair and axis must contradict it.
        report = precheck(
            machine(
                [leaf("w", 100)],
                parts=self._parts(),
                mates=[
                    {"id": "m1", "kind": "coincident", "part_a": "a", "part_b": "b"},
                    {"id": "m2", "kind": "distance", "part_a": "a", "part_b": "b", "axis": "x", "value_mm": 50},
                ],
            )
        )
        self.assertEqual(report["status"], "conflict")

    def test_under_constrained_part_warning(self):
        report = precheck(
            machine(
                [leaf("w", 100)],
                parts=self._parts() + [{"id": "free", "uses_parameters": []}],
                mates=[
                    {"id": "m1", "kind": "distance", "part_a": "a", "part_b": "b", "axis": "x", "value_mm": 100},
                ],
            )
        )
        self.assertTrue(
            any(
                c["kind"] == "under_constrained" and c["parts"] == ["free"]
                for c in report["conflicts"]
            )
        )


class TestImpactAndChains(unittest.TestCase):
    def test_impact_scope_transitive(self):
        data = json.loads((EXAMPLES / "frame_linkage_ok.json").read_text())
        report = precheck(data)
        impact = report["impact"]["machine_width"]
        for expected in ("frame_width", "beam_length", "roller_length", "guide_spacing", "cover_width"):
            self.assertIn(expected, impact["parameters"])
        for part in ("beam_front", "roller_1", "guide_left", "cover_top"):
            self.assertIn(part, impact["parts"])
        self.assertIn("m5", impact["mates"])

    def test_confirm_chain_lists_pending_upstream_first(self):
        data = json.loads((EXAMPLES / "frame_linkage_pending.json").read_text())
        report = precheck(data)
        chains = {c["change"]: c for c in report["confirm_chains"]}
        self.assertIn("side_allowance", chains["frame_width"]["confirm_first"])
        self.assertIn("beam_length", chains["machine_width"]["affected"]["parameters"])


class TestCli(unittest.TestCase):
    def _run(self, example, extra=None):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            cmd = [
                sys.executable, "-m", "dependency_engine.cli",
                str(EXAMPLES / example), "--out-dir", str(out),
            ] + (extra or [])
            proc = subprocess.run(cmd, capture_output=True, text=True, cwd=Path(__file__).resolve().parents[2])
            report = None
            if (out / "precheck.json").exists():
                report = json.loads((out / "precheck.json").read_text())
            return proc.returncode, report, proc.stdout + proc.stderr

    def test_cli_ok_example_exit_0(self):
        code, report, _ = self._run("frame_linkage_ok.json")
        self.assertEqual(code, 0)
        self.assertEqual(report["status"], "ok")
        values = {p["name"]: p["value"] for p in report["parameters"]}
        self.assertEqual(values["frame_width"], 940.0)
        self.assertEqual(values["roller_length"], 920.0)
        self.assertEqual(values["guide_spacing"], 880.0)
        self.assertEqual(values["cover_width"], 970.0)

    def test_cli_conflict_example_exit_1(self):
        code, report, _ = self._run("frame_linkage_conflict.json")
        self.assertEqual(code, 1)
        self.assertEqual(report["status"], "conflict")

    def test_cli_pending_example_exit_1(self):
        code, report, _ = self._run("frame_linkage_pending.json")
        self.assertEqual(code, 1)
        self.assertEqual(report["status"], "pending")

    def test_cli_input_never_modified(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "machine.json"
            src.write_text((EXAMPLES / "frame_linkage_ok.json").read_text())
            before = src.read_text()
            proc = subprocess.run(
                [sys.executable, "-m", "dependency_engine.cli", str(src), "--out-dir", str(Path(tmp) / "out")],
                capture_output=True, text=True, cwd=Path(__file__).resolve().parents[2],
            )
            self.assertEqual(proc.returncode, 0)
            self.assertEqual(src.read_text(), before)


class TestNoDefaults(unittest.TestCase):
    def test_no_default_constants_or_generator_constant_reference(self):
        root = Path(__file__).resolve().parents[1]
        pattern = re.compile(r"\bDEFAULT_[A-Z_]+")
        for path in (root / "engine.py", root / "cli.py"):
            text = path.read_text()
            self.assertIsNone(
                pattern.search(text),
                "%s must not define a DEFAULT_* constant" % path.name,
            )
            self.assertNotIn("MATERIAL_K", text)
            self.assertNotIn("DEFAULT_BEND_K_FACTOR", text)


if __name__ == "__main__":
    unittest.main()
