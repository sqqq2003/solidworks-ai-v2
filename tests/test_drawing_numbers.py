"""Drawing-number allocation: monotonic, journaled, never silently reused."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.drawing_numbers import (  # noqa: E402
    DrawingNumberError,
    allocate_drawing_numbers,
    attach_drawing_refs,
    load_journal,
)


class DrawingNumberTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.journal = Path(self.tmp.name) / "journal.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_first_allocation_starts_at_one(self):
        result = allocate_drawing_numbers(["part-a"], journal_path=self.journal)
        self.assertEqual(result["allocations"][0]["drawing_number"], "QL-5050PX-001")
        self.assertEqual(result["allocations"][0]["status"], "allocated")

    def test_allocation_is_monotonic_and_persisted(self):
        allocate_drawing_numbers(["part-a"], journal_path=self.journal)
        result = allocate_drawing_numbers(["part-b"], journal_path=self.journal)
        self.assertEqual(result["allocations"][0]["drawing_number"], "QL-5050PX-002")
        self.assertTrue(self.journal.exists())
        journal = load_journal(self.journal)
        self.assertEqual(journal["max_seq"], 2)

    def test_same_part_is_idempotent(self):
        allocate_drawing_numbers(["part-a"], journal_path=self.journal)
        result = allocate_drawing_numbers(["part-a"], journal_path=self.journal)
        row = result["allocations"][0]
        self.assertEqual(row["status"], "existing")
        self.assertEqual(row["drawing_number"], "QL-5050PX-001")
        self.assertEqual(load_journal(self.journal)["max_seq"], 1)

    def test_issued_number_is_never_reused_for_another_part(self):
        allocate_drawing_numbers(["part-a"], journal_path=self.journal)
        # Tamper with the journal so the next computed number collides.
        journal = load_journal(self.journal)
        journal["max_seq"] = 0  # force QL-5050PX-001 to be recomputed
        journal["issued"]["QL-5050PX-001"] = {"part": "part-x", "sequence": 1, "assigned": "now"}
        self.journal.write_text(json.dumps(journal), encoding="utf-8")
        with self.assertRaises(DrawingNumberError):
            allocate_drawing_numbers(["part-y"], journal_path=self.journal)

    def test_attach_drawing_refs_fills_bom_items(self):
        from src.drawing_bom import BomItem, BomReport

        report = BomReport(status="mock", items=(BomItem(1, "part-a", 1, 2.5, "", None, "mock", None),))
        allocations = [{"part": "part-a", "drawing_number": "QL-5050PX-001", "status": "allocated"}]
        attached = attach_drawing_refs(report, allocations)
        self.assertEqual(attached.items[0].drawing_ref, "QL-5050PX-001")

    def test_custom_scheme(self):
        result = allocate_drawing_numbers(
            ["part-a"], scheme="DWG-{seq:04d}", journal_path=self.journal
        )
        self.assertEqual(result["allocations"][0]["drawing_number"], "DWG-0001")


if __name__ == "__main__":
    unittest.main()
