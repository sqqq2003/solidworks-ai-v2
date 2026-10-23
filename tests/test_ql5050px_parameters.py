"""QL-5050PX plan contract; targets and design rules are not OEM evidence."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from ql5050px.parameters import MODULES, build_plan
from sw_api.mapping import load_mappings, mapping_template


def measurement(value, source="simulation_fixture_only", confirmed=True):
    return {"value": value, "source": source, "confirmed": confirmed}


class PlanDefaultsTests(unittest.TestCase):
    def test_default_envelope_is_target_only(self):
        plan = build_plan()
        self.assertEqual(plan["schema_version"], 1)
        self.assertEqual(plan["machine"], "QL-5050PX")
        self.assertEqual(plan["units"], "mm")
        self.assertEqual(plan["values_mm"]["target_length"], 1800.0)
        self.assertEqual(plan["values_mm"]["target_width"], 900.0)
        self.assertEqual(plan["values_mm"]["target_height"], 1500.0)
        for name in ("target_length", "target_width", "target_height"):
            self.assertEqual(plan["parameter_register"][name]["status"], "target_only")
            self.assertEqual(plan["parameter_register"][name]["source"], "user_target")
        self.assertEqual(plan["mechanical_acceptance"], "unverified")

    def test_module_values_start_pending(self):
        plan = build_plan()
        for names in MODULES.values():
            for name in names:
                self.assertIsNone(plan["values_mm"][name], name)
                self.assertEqual(plan["parameter_register"][name]["status"], "pending_mapping", name)
        for name in MODULES:
            for parameter in MODULES[name]:
                self.assertIn(parameter, plan["pending_mapping"])
        self.assertIn("end_allowance", plan["pending_mapping"])

    def test_register_units_and_module_index(self):
        plan = build_plan()
        self.assertEqual(plan["parameter_register"]["drive_speed"]["unit"], "mm/s")
        self.assertEqual(plan["parameter_register"]["motor_power"]["unit"], "W")
        self.assertEqual(plan["parameter_register"]["right_drive_x"]["unit"], "mm")
        self.assertEqual(plan["modules"], MODULES)
        indexed = {name for names in MODULES.values() for name in names}
        self.assertLessEqual(indexed, set(plan["values_mm"]))

    def test_bad_envelope_refused(self):
        for bad in (0, -1, True, "1800", None, float("nan"), float("inf")):
            with self.subTest(value=bad):
                with self.assertRaises(ValueError):
                    build_plan(envelope={"length": bad, "width": 900, "height": 1500})
        with self.assertRaises(KeyError):
            build_plan(envelope={"length": 1800, "width": 900})


class MeasurementTests(unittest.TestCase):
    def test_confirmed_measurement_is_recorded(self):
        plan = build_plan(measurements={
            "frame_length": measurement(1650),
            "drive_speed": measurement(120),
            "motor_power": measurement(750),
            "left_drive_x": measurement(-320),
        })
        self.assertEqual(plan["values_mm"]["frame_length"], 1650.0)
        self.assertEqual(plan["values_mm"]["left_drive_x"], -320.0)
        for name in ("frame_length", "drive_speed", "motor_power", "left_drive_x"):
            row = plan["parameter_register"][name]
            self.assertEqual(row["status"], "confirmed_input")
            self.assertEqual(row["source"], "simulation_fixture_only")
        self.assertNotIn("frame_length", plan["pending_mapping"])

    def test_unconfirmed_or_unsourced_measurement_is_ignored(self):
        plan = build_plan(measurements={
            "frame_length": measurement(1650, confirmed=False),
            "frame_width": measurement(850, source=None),
            "frame_height": measurement(1400, confirmed="yes"),
        })
        for name in ("frame_length", "frame_width", "frame_height"):
            self.assertIsNone(plan["values_mm"][name])
            self.assertEqual(plan["parameter_register"][name]["status"], "pending_mapping")

    def test_unknown_or_invalid_measurement_refused(self):
        with self.assertRaisesRegex(ValueError, "unknown QL parameter"):
            build_plan(measurements={"gt_zx_length": measurement(1300)})
        for bad in (0, -5, True, "1600", float("nan")):
            with self.subTest(value=bad):
                with self.assertRaises(ValueError):
                    build_plan(measurements={"frame_length": measurement(bad)})
        with self.assertRaises(ValueError):
            build_plan(measurements={"right_drive_x": measurement(-10)})


class DerivedRuleTests(unittest.TestCase):
    def test_design_relationships_derive_frame_and_drives(self):
        plan = build_plan(measurements={
            "end_allowance": measurement(50),
            "side_allowance": measurement(25),
            "top_allowance": measurement(100),
            "conveyor_width": measurement(600),
            "belt_offset": measurement(20),
        })
        self.assertEqual(plan["values_mm"]["frame_length"], 1700.0)
        self.assertEqual(plan["values_mm"]["frame_width"], 850.0)
        self.assertEqual(plan["values_mm"]["frame_height"], 1400.0)
        self.assertEqual(plan["values_mm"]["left_drive_x"], -320.0)
        self.assertEqual(plan["values_mm"]["right_drive_x"], 320.0)
        row = plan["parameter_register"]["frame_length"]
        self.assertEqual(row["status"], "derived_design")
        self.assertEqual(row["depends_on"], ["target_length", "end_allowance"])
        self.assertIn("OEM validation pending", row["source"])
        for name in ("frame_length", "frame_width", "frame_height", "left_drive_x", "right_drive_x"):
            self.assertNotIn(name, plan["pending_mapping"])

    def test_confirmed_value_overrides_rule(self):
        plan = build_plan(measurements={
            "end_allowance": measurement(50),
            "frame_length": measurement(1650),
        })
        self.assertEqual(plan["values_mm"]["frame_length"], 1650.0)
        self.assertEqual(plan["parameter_register"]["frame_length"]["status"], "confirmed_input")

    def test_nonpositive_derived_length_refused(self):
        with self.assertRaises(ValueError):
            build_plan(measurements={"end_allowance": measurement(900)})

    def test_incomplete_dependencies_keep_rule_pending(self):
        plan = build_plan(measurements={"conveyor_width": measurement(600)})
        for name in ("left_drive_x", "right_drive_x"):
            self.assertIsNone(plan["values_mm"][name])
            self.assertEqual(plan["parameter_register"][name]["status"], "pending_mapping")


class MappingContractTests(unittest.TestCase):
    def test_template_loads_and_stays_pending(self):
        plan = build_plan()
        rows = load_mappings(mapping_template(plan))
        self.assertTrue(rows)
        self.assertTrue(all(row.status == "pending_mapping" for row in rows))

    def test_template_excludes_units_the_schema_cannot_express(self):
        plan = build_plan()
        template = mapping_template(plan)
        names = {row["parameter"] for row in template["parameters"]}
        self.assertNotIn("drive_speed", names)
        self.assertNotIn("motor_power", names)
        self.assertIn("frame_length", names)
        self.assertIn("left_drive_x", names)
        self.assertEqual(len(names), len(template["parameters"]))

    def test_template_rows_are_unique(self):
        plan = build_plan(measurements={"frame_length": measurement(1650)})
        rows = load_mappings(mapping_template(plan))
        names = [row.parameter for row in rows]
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue(all(row.unit in {"mm", "m", "deg", "count"} for row in rows))


if __name__ == "__main__":
    unittest.main()
