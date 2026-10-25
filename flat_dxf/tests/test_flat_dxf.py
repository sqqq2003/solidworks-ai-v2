"""Tests for flat_dxf (phase 1, F2). Pure stdlib, no SolidWorks."""

import json
import math
import re
import tempfile
import unittest
from pathlib import Path

from flat_dxf.cli import main as cli_main
from flat_dxf.dxf import (
    FlatDxfError,
    build_flat_dxf,
)

T = 2.0
R = 1.5
ANGLE = 90
K = 0.38


def _ba():
    return math.radians(ANGLE) * (R + K * T)


def _unfold():
    ba = _ba()
    return {
        "unfold_version": "feature-tree-unfold/1",
        "tree_name": "u_channel",
        "status": "ok",
        "straight_lengths_mm": [30.0, 40.0, 30.0],
        "straight_total_mm": 100.0,
        "bends": [
            {"bend_id": "b1", "bend_allowance_mm": ba,
             "pending_reasons": []},
            {"bend_id": "b2", "bend_allowance_mm": ba,
             "pending_reasons": []},
        ],
        "total_bend_allowance_mm": 2 * ba,
        "unfold_length_mm": 100.0 + 2 * ba,
        "pending": [],
        "excluded": [],
    }


def _bends(**overrides):
    b1 = {
        "bend_id": "b1", "thickness_mm": T, "radius_mm": R,
        "angle_degrees": ANGLE, "k_factor": K,
        "v_opening_mm": 12, "process": "air_bending",
        "direction": "up", "sequence": 1,
    }
    b2 = dict(b1, bend_id="b2", direction="down", sequence=2)
    b1.update(overrides.get("b1", {}))
    b2.update(overrides.get("b2", {}))
    if "drop" in overrides:
        for key in overrides["drop"]:
            b1.pop(key, None)
            b2.pop(key, None)
    return [b1, b2]


class TestFlatDxf(unittest.TestCase):
    def test_ok_strip_and_bend_lines(self):
        result = build_flat_dxf(_unfold(), _bends(), 80.0)
        self.assertEqual(result["status"], "ok")
        ba = _ba()
        self.assertAlmostEqual(
            result["flat_length_mm"], 100.0 + 2 * ba, places=9
        )
        card = result["bend_card"]
        self.assertAlmostEqual(
            card["bends"][0]["bend_line_x_mm"], 30.0 + ba / 2, places=9
        )
        self.assertAlmostEqual(
            card["bends"][1]["bend_line_x_mm"],
            30.0 + ba + 40.0 + ba / 2, places=9,
        )
        dxf = result["dxf_text"]
        self.assertIn("SECTION", dxf)
        self.assertIn("CUT", dxf)
        self.assertIn("BEND", dxf)
        self.assertIn("NOTES", dxf)
        # Two bend LINE entities (counted in ENTITIES only; the
        # TABLES layer definition adds one more "BEND" above).
        entities = dxf.split("ENTITIES", 1)[1]
        self.assertEqual(entities.count("BEND"), 2)

    def test_flat_blank_no_bends(self):
        unfold = _unfold()
        unfold["straight_lengths_mm"] = [120.0]
        unfold["straight_total_mm"] = 120.0
        unfold["bends"] = []
        unfold["total_bend_allowance_mm"] = 0.0
        unfold["unfold_length_mm"] = 120.0
        result = build_flat_dxf(unfold, [], 50.0)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["flat_length_mm"], 120.0)

    def test_missing_k_factor_pending(self):
        result = build_flat_dxf(_unfold(), _bends(drop=["k_factor"]), 80.0)
        self.assertEqual(result["status"], "pending")
        self.assertTrue(
            any("missing_param:k_factor" in p for p in result["pending"])
        )
        self.assertIsNone(result["dxf_text"])

    def test_missing_v_opening_pending(self):
        result = build_flat_dxf(
            _unfold(), _bends(drop=["v_opening_mm"]), 80.0
        )
        self.assertEqual(result["status"], "pending")
        self.assertTrue(
            any("missing_param:v_opening_mm" in p
                for p in result["pending"])
        )

    def test_missing_process_pending(self):
        result = build_flat_dxf(_unfold(), _bends(drop=["process"]), 80.0)
        self.assertEqual(result["status"], "pending")
        self.assertTrue(
            any("missing_param:process" in p for p in result["pending"])
        )

    def test_bad_direction_pending(self):
        bends = _bends()
        bends[0]["direction"] = "sideways"
        result = build_flat_dxf(_unfold(), bends, 80.0)
        self.assertEqual(result["status"], "pending")
        self.assertTrue(
            any("direction" in p for p in result["pending"])
        )

    def test_unfold_pending_passthrough(self):
        unfold = _unfold()
        unfold["status"] = "pending"
        unfold["pending"] = ["bend_pending:b1:missing_param:k_factor"]
        result = build_flat_dxf(unfold, _bends(), 80.0)
        self.assertEqual(result["status"], "pending")
        self.assertTrue(
            any("unfold_report_not_ok" in p for p in result["pending"])
        )

    def test_bend_allowance_mismatch_pending(self):
        unfold = _unfold()
        unfold["bends"][0]["bend_allowance_mm"] += 0.01
        result = build_flat_dxf(unfold, _bends(), 80.0)
        self.assertEqual(result["status"], "pending")
        self.assertTrue(
            any("bend_allowance_mismatch:b1" in p
                for p in result["pending"])
        )

    def test_unfold_length_mismatch_pending(self):
        unfold = _unfold()
        unfold["unfold_length_mm"] += 0.5
        result = build_flat_dxf(unfold, _bends(), 80.0)
        self.assertEqual(result["status"], "pending")
        self.assertIn("unfold_length_mismatch", result["pending"])

    def test_straight_bend_count_mismatch_pending(self):
        unfold = _unfold()
        unfold["straight_lengths_mm"] = [30.0, 40.0]
        result = build_flat_dxf(unfold, _bends(), 80.0)
        self.assertEqual(result["status"], "pending")
        self.assertIn("straight_bend_count_mismatch", result["pending"])

    def test_blank_width_error(self):
        with self.assertRaises(FlatDxfError):
            build_flat_dxf(_unfold(), _bends(), 0)

    def test_no_default_number_scan(self):
        package = Path(__file__).resolve().parent.parent
        patterns = [
            re.compile(r"k_factor\s*=\s*[0-9]"),
            re.compile(r"thickness_mm\s*=\s*[0-9]"),
            re.compile(r"0\.44"),
            re.compile(r"DEFAULT"),
        ]
        for path in sorted(package.glob("*.py")):
            text = path.read_text(encoding="utf-8")
            for pattern in patterns:
                self.assertIsNone(
                    pattern.search(text),
                    "%s matches %s in %s"
                    % (pattern.pattern, path.name, path),
                )

    def test_cli_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            unfold_path = tmp / "unfold.json"
            unfold_path.write_text(
                json.dumps(_unfold()), encoding="utf-8"
            )
            job_path = tmp / "job.json"
            job_path.write_text(
                json.dumps(
                    {"blank_width_mm": 80.0, "bends": _bends()}
                ),
                encoding="utf-8",
            )
            out = tmp / "out"
            self.assertEqual(
                cli_main([str(unfold_path), str(job_path),
                          "--out-dir", str(out)]),
                0,
            )
            self.assertTrue((out / "flat.dxf").exists())
            self.assertTrue((out / "bend_card.json").exists())
            pending_job = tmp / "job_pending.json"
            pending_job.write_text(
                json.dumps(
                    {"blank_width_mm": 80.0,
                     "bends": _bends(drop=["k_factor"])}
                ),
                encoding="utf-8",
            )
            self.assertEqual(
                cli_main([str(unfold_path), str(pending_job),
                          "--out-dir", str(out)]),
                1,
            )
            self.assertEqual(
                cli_main([str(tmp / "nope.json"), str(job_path),
                          "--out-dir", str(out)]),
                2,
            )


if __name__ == "__main__":
    unittest.main()
