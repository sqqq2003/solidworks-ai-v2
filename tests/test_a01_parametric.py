"""Solver, constraints, and dependency tests for the A01 parametric plan."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import a01
from src.a01_parametric import constraints
from src.a01_parametric.config import apply_simulated_allowances, load_spec, with_envelope
from src.a01_parametric.solver import dependency_order, solve, solve_spec

FIXTURE = ROOT / "tests" / "fixtures" / "a01_sim_assembly.json"


def _index(plan: dict, name: str) -> int:
    return plan["parameter_order"].index(name)


class SolverTests(unittest.TestCase):
    def test_default_envelope_keeps_unconfirmed_measured_empty(self):
        plan = solve_spec()
        self.assertEqual(plan["target_envelope_mm"], {"length": 1800.0, "width": 900.0, "height": 1500.0})
        self.assertEqual(plan["status"], "review_required")
        self.assertFalse(plan["cad_executed"])
        self.assertEqual(plan["sw_live"], "not_applicable_on_linux")
        self.assertIsNone(plan["values_mm"]["front_allowance"])
        self.assertIsNone(plan["values_mm"]["frame_length"])
        self.assertIsNone(plan["values_mm"]["roller_pitch"])
        self.assertIsNone(plan["values_mm"]["chain_pitch"])
        present = {name: value for name, value in plan["values_mm"].items() if value is not None}
        self.assertEqual(present, {"length": 1800.0, "width": 900.0, "height": 1500.0})

    def test_plan_json_is_deterministic(self):
        first = json.dumps(solve_spec(), sort_keys=True, ensure_ascii=False)
        second = json.dumps(solve_spec(length=1800, width=900, height=1500), sort_keys=True, ensure_ascii=False)
        self.assertEqual(first, second)

    def test_dependency_order_follows_frame_conveyor_drive_mount(self):
        plan = solve_spec()
        self.assertLess(_index(plan, "frame_length"), _index(plan, "conveyor_bed_length"))
        self.assertLess(_index(plan, "conveyor_bed_length"), _index(plan, "roller_pitch"))
        self.assertLess(_index(plan, "roller_pitch"), _index(plan, "roller_count"))
        self.assertLess(_index(plan, "conveyor_bed_length"), _index(plan, "drive_center_along_length"))
        self.assertLess(_index(plan, "drive_center_along_length"), _index(plan, "chain_pitch"))
        self.assertLess(_index(plan, "chain_pitch"), _index(plan, "sprocket_teeth"))
        self.assertLess(_index(plan, "column_height"), _index(plan, "motor_mount_z"))
        self.assertLess(_index(plan, "bearing_journal"), _index(plan, "bearing_mount_span"))

    def test_cycle_is_rejected(self):
        spec = with_envelope(load_spec(), 1800, 900, 1500)
        spec["parametric_graph"]["roller_pitch"]["depends_on"] = ["sprocket_teeth"]
        spec["parametric_graph"]["sprocket_teeth"]["depends_on"] = ["roller_pitch"]
        with self.assertRaises(ValueError):
            dependency_order(spec)

    def test_non_mm_spec_and_non_positive_envelope_rejected(self):
        spec = load_spec()
        spec["units"] = "inch"
        with self.assertRaises(ValueError):
            solve(spec)
        with self.assertRaises(ValueError):
            solve_spec(length=0, width=900, height=1500)
        with self.assertRaises(ValueError):
            solve_spec(length=True, width=900, height=1500)

    def test_preserved_interface_cannot_be_overwritten(self):
        spec = with_envelope(load_spec(), 1800, 900, 1500)
        plan = solve(spec)
        values = dict(plan["values_mm"])
        values["chain_pitch"] = 12.7
        with self.assertRaises(ValueError):
            constraints.enforce(spec, values)
        self.assertNotIn(12.7, plan["values_mm"].values())

    def test_simulated_fixture_resolves_only_the_allowance_chain(self):
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.assertTrue(fixture["not_measured_from_real_a01"])
        spec = apply_simulated_allowances(with_envelope(load_spec(), 1800, 900, 1500), fixture)
        plan = solve(spec)
        self.assertEqual(plan["values_mm"]["frame_length"], 1780.0)
        self.assertEqual(plan["values_mm"]["frame_width"], 880.0)
        self.assertEqual(plan["values_mm"]["column_height"], 1480.0)
        self.assertEqual(plan["values_mm"]["conveyor_bed_length"], 1780.0)
        self.assertEqual(plan["values_mm"]["conveyor_clear_width"], 880.0)
        self.assertIsNone(plan["values_mm"]["roller_pitch"])
        self.assertIsNone(plan["values_mm"]["passline_height"])
        self.assertIsNone(plan["values_mm"]["sheet_thickness"])
        present = set(value for value in plan["values_mm"].values() if value is not None)
        for banned in fixture["ignored_numbers_mm"]:
            self.assertNotIn(banned, present)
        self.assertEqual(plan["status"], "review_required")

    def test_register_lists_pending_mapping_without_approval(self):
        plan = solve_spec()
        row = plan["parameter_register"]["roller_pitch"]
        self.assertEqual(row["unit"], "mm")
        self.assertEqual(row["source"], "unmapped_real_model")
        self.assertEqual(row["depends_on"], ["conveyor_bed_length"])
        self.assertEqual(row["confirmation_status"], "pending_mapping")
        self.assertFalse(row["production_approved"])
        self.assertEqual(row["subsystem"], "conveyor")
        ids = [item["mapping_id"] for item in plan["pending_mapping"]]
        self.assertIn("A01.conveyor.roller_pitch", ids)
        self.assertIn("A01.drive.chain_pitch", ids)
        self.assertIn("A01.mount.motor_x", ids)
        self.assertIn("A01.interfaces.sheet_thickness", ids)
        self.assertTrue(all(item["production_approved"] is False for item in plan["parameter_register"].values()))

    def test_existing_preflight_still_reviews_real_spec(self):
        report = a01.make_plan(a01.read_json(a01.ROOT / "data" / "machine_spec.json"))
        self.assertEqual(report["status"], "review_required")
        self.assertIsNone(report["values_mm"]["frame_length"])
        self.assertFalse(report["cad_executed"])


class CliTests(unittest.TestCase):
    def test_dry_run_cli_emits_plan(self):
        out = ROOT / "runtime" / "a01-parametric" / "cli-test-report.json"
        trace = ROOT / "runtime" / "a01-parametric" / "cli-test-trace.json"
        if out.exists():
            out.unlink()
        if trace.exists():
            trace.unlink()
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "src.a01_parametric.cli",
                "--length",
                "1800",
                "--width",
                "900",
                "--height",
                "1500",
                "--dry-run",
                "--out",
                str(out),
                "--save-as",
                str(trace),
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        report = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(report["plan"]["target_envelope_mm"]["length"], 1800.0)
        self.assertEqual(report["dry_run"]["sw_live"], "not_applicable_on_linux")
        self.assertFalse(report["dry_run"]["original_overwritten"])
        self.assertIn("roller_pitch", report["dry_run"]["variables_skipped_unresolved"])
        self.assertEqual(report["dry_run"]["variables_set"], ["height", "length", "width"])
        self.assertFalse(trace.with_suffix(".sldasm").exists())

    def test_live_flag_is_refused_without_com(self):
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                "import src.sw_api.win32com_backend as backend; "
                "backend.com_available = lambda: False; "
                "from src.a01_parametric.cli import main; raise SystemExit(main())",
                "--live",
                "--assembly",
                str(ROOT / "runtime" / "original.SLDASM"),
                "--save-as",
                str(ROOT / "runtime" / "copy.SLDASM"),
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 2, completed.stdout)
        self.assertIn("not_applicable_on_linux", completed.stdout)
        self.assertFalse((ROOT / "runtime" / "copy.SLDASM").exists())


if __name__ == "__main__":
    unittest.main()

