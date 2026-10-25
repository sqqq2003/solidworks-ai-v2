"""Tests for bom (phase 1, F3). No masses are ever guessed."""

import json
import tempfile
import unittest
from pathlib import Path

from bom.bom import BomError, build_bom, render_csv, render_table
from bom.cli import main as cli_main


def _assembly():
    return {
        "assembly_name": "sealer_frame",
        "parts": [
            {"id": "column_left", "name": "左立柱", "material": "Q235",
             "quantity": 2, "mass_kg": 4.5},
            {"id": "beam_front", "name": "前横梁", "material": "Q235",
             "quantity": 1, "mass_kg": 6.0,
             "depends_on": ["column_left"]},
            {"id": "roller_a", "name": "滚筒A", "material": "45钢",
             "quantity": 4, "mass_kg": 1.25,
             "depends_on": ["beam_front"]},
        ],
    }


class TestBom(unittest.TestCase):
    def test_ok_order_and_totals(self):
        result = build_bom(_assembly())
        self.assertEqual(result["status"], "ok")
        self.assertEqual(
            [r["id"] for r in result["rows"]],
            ["column_left", "beam_front", "roller_a"],
        )
        self.assertEqual(result["total_quantity"], 7)
        self.assertAlmostEqual(result["total_mass_kg"], 20.0)

    def test_missing_mass_pending_total_unknown(self):
        doc = _assembly()
        del doc["parts"][0]["mass_kg"]
        result = build_bom(doc)
        self.assertEqual(result["status"], "pending")
        self.assertTrue(
            any("mass_pending" in p for p in result["pending"])
        )
        self.assertIsNone(result["total_mass_kg"])
        self.assertIsNone(result["rows"][0]["total_mass_kg"])

    def test_duplicate_id_error(self):
        doc = _assembly()
        doc["parts"].append(dict(doc["parts"][0]))
        with self.assertRaises(BomError):
            build_bom(doc)

    def test_bad_quantity_error(self):
        for bad in (0, 1.5, True, "2"):
            doc = _assembly()
            doc["parts"][0]["quantity"] = bad
            with self.assertRaises(BomError):
                build_bom(doc)

    def test_cycle_error(self):
        doc = _assembly()
        doc["parts"][0]["depends_on"] = ["roller_a"]
        with self.assertRaises(BomError):
            build_bom(doc)

    def test_unresolved_dependency_pending_row_kept(self):
        doc = _assembly()
        doc["parts"][1]["depends_on"] = ["purchased_bracket"]
        result = build_bom(doc)
        self.assertEqual(result["status"], "pending")
        self.assertTrue(
            any("unresolved_dependency:purchased_bracket" in p
                for p in result["pending"])
        )
        self.assertEqual(len(result["rows"]), 3)

    def test_dependency_report_cross_check(self):
        report = {
            "format": "dependency-engine-report/1",
            "name": "other_machine",
            "parts": [
                {"id": "column_left", "label": "左立柱",
                 "uses_parameters": [], "feature_refs": []},
            ],
        }
        result = build_bom(_assembly(), report)
        self.assertEqual(result["status"], "pending")
        self.assertEqual(
            result["dependency_check"]["unmatched_ids"],
            ["beam_front", "roller_a"],
        )
        self.assertFalse(result["dependency_check"]["name_match"])
        self.assertIn("assembly_name_mismatch", result["pending"])

    def test_csv_and_table_render(self):
        result = build_bom(_assembly())
        csv_text = render_csv(result)
        self.assertIn("零件号", csv_text)
        self.assertIn("beam_front", csv_text)
        table = render_table(result)
        self.assertIn("sealer_frame", table)
        self.assertIn("合计数量: 7", table)

    def test_cli_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            input_path = tmp / "assembly.json"
            input_path.write_text(
                json.dumps(_assembly(), ensure_ascii=False),
                encoding="utf-8",
            )
            out = tmp / "out"
            self.assertEqual(
                cli_main([str(input_path), "--out-dir", str(out)]), 0
            )
            self.assertTrue((out / "bom.json").exists())
            self.assertTrue((out / "bom.csv").exists())
            self.assertTrue((out / "bom_table.txt").exists())
            self.assertEqual(
                cli_main([str(tmp / "nope.json"),
                          "--out-dir", str(out)]),
                2,
            )


if __name__ == "__main__":
    unittest.main()
