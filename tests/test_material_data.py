"""Material data lookups: confirmed rows resolve, others stay unresolved."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.material_data import (  # noqa: E402
    MaterialDataError,
    density_for,
    k_factor_for,
)


class MaterialDataTests(unittest.TestCase):
    def test_confirmed_density_resolves_with_source(self):
        row = density_for("SUS304")
        self.assertEqual(row["status"], "resolved")
        self.assertAlmostEqual(row["density_g_per_cm3"], 7.93, places=6)
        self.assertTrue(row["confirmed"])
        self.assertTrue(row["source"])

    def test_unknown_material_is_unresolved(self):
        row = density_for("unobtanium")
        self.assertEqual(row["status"], "unresolved")
        self.assertNotIn("density_g_per_cm3", row)

    def test_example_row_is_refused(self):
        row = density_for("EXAMPLE-not-for-production")
        self.assertEqual(row["status"], "unresolved")

    def test_k_factor_table_has_no_production_rows(self):
        # The shipped K-factor table must not silently provide production K.
        table = json.loads((ROOT / "data" / "k_factor_table.json").read_text(encoding="utf-8"))
        self.assertTrue(all(row.get("confirmed") is not True for row in table["k_factors"]))

    def test_k_factor_lookup_is_unresolved_without_default(self):
        row = k_factor_for("SUS304", 2.5)
        self.assertEqual(row["status"], "unresolved")
        self.assertNotIn("k_factor", row)

    def test_k_factor_rejects_nonpositive_thickness(self):
        with self.assertRaises(MaterialDataError):
            k_factor_for("SUS304", 0)

    def test_confirmed_k_row_resolves(self):
        with tempfile.TemporaryDirectory() as tmp:
            table = {
                "table_version": 1,
                "k_factors": [
                    {
                        "material": "SUS304",
                        "thickness_mm": 2.5,
                        "k_factor": 0.33,
                        "confirmed": True,
                        "source": "press-brake trial coupon; operator measurement",
                        "provenance": "runtime/k-trials/sus304-2p5.json",
                    }
                ],
            }
            path = Path(tmp) / "k.json"
            path.write_text(json.dumps(table), encoding="utf-8")
            row = k_factor_for("SUS304", 2.5, path=path)
        self.assertEqual(row["status"], "resolved")
        self.assertAlmostEqual(row["k_factor"], 0.33, places=6)
        self.assertTrue(row["provenance"])


if __name__ == "__main__":
    unittest.main()
