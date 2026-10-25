"""Tests for drawing_gen (phase 1, F1). Template only, no CAD."""

import json
import tempfile
import unittest
from pathlib import Path

from drawing_gen.cli import main as cli_main
from drawing_gen.drawing import DrawingError, build_drawing


def _doc(**overrides):
    doc = {
        "part_name": "bracket",
        "bounding_box_mm": {
            "length": 120.0, "width": 80.0, "height": 60.0
        },
        "sheet_size": "A4",
        "scale": "1:2",
        "title_block": {
            "drawing_no": "QL-B-001",
            "part_name": "bracket",
            "material": "Q235",
            "scale": "1:2",
            "sheet_size": "A4",
            "designer": "Lou",
            "date": "2026-10-25",
            "revision": "A",
        },
        "dimensions": [
            {"name": "overall_length", "value_mm": 120.0,
             "source": "explicit"},
            {"name": "overall_width", "value_mm": 80.0,
             "source": "explicit"},
        ],
    }
    for key, value in overrides.items():
        if key == "title_block":
            doc["title_block"].update(value)
        elif key == "bounding_box_mm":
            doc["bounding_box_mm"].update(value)
        else:
            doc[key] = value
    return doc


class TestDrawingGen(unittest.TestCase):
    def test_ok_layout(self):
        result = build_drawing(_doc())
        self.assertEqual(result["status"], "ok")
        views = {v["name"]: v for v in result["views"]}
        self.assertEqual(views["front"]["size_mm"], [60.0, 30.0])
        self.assertEqual(views["front"]["position_mm"], [20.0, 20.0])
        self.assertEqual(views["top"]["position_mm"], [20.0, 60.0])
        self.assertEqual(views["side"]["position_mm"], [90.0, 20.0])
        self.assertEqual(len(result["dimensions"]), 2)

    def test_missing_title_field_pending(self):
        doc = _doc()
        del doc["title_block"]["designer"]
        result = build_drawing(doc)
        self.assertEqual(result["status"], "pending")
        self.assertIn("missing_title_field:designer", result["pending"])

    def test_dimension_missing_value_pending(self):
        doc = _doc(dimensions=[
            {"name": "overall_length", "source": "explicit"},
        ])
        result = build_drawing(doc)
        self.assertEqual(result["status"], "pending")
        self.assertIn("dimension_pending:overall_length", result["pending"])
        self.assertEqual(result["dimensions"], [])

    def test_layout_overflow_pending(self):
        doc = _doc(bounding_box_mm={
            "length": 600.0, "width": 500.0, "height": 400.0
        })
        result = build_drawing(doc)
        self.assertEqual(result["status"], "pending")
        self.assertTrue(
            any("view_layout_overflow" in p for p in result["pending"])
        )

    def test_bad_scale_error(self):
        with self.assertRaises(DrawingError):
            build_drawing(_doc(scale="wide"))

    def test_bad_sheet_error(self):
        with self.assertRaises(DrawingError):
            build_drawing(_doc(sheet_size="A0"))

    def test_title_scale_mismatch_pending(self):
        doc = _doc(title_block={"scale": "1:1"})
        result = build_drawing(doc)
        self.assertEqual(result["status"], "pending")
        self.assertIn("title_block_scale_mismatch", result["pending"])

    def test_mock_note_present(self):
        result = build_drawing(_doc())
        self.assertTrue(
            any("MOCK_RENDER" in note for note in result["notes"])
        )

    def test_cli_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            input_path = tmp / "drawing.json"
            input_path.write_text(
                json.dumps(_doc()), encoding="utf-8"
            )
            out = tmp / "out"
            self.assertEqual(
                cli_main([str(input_path), "--out-dir", str(out)]), 0
            )
            self.assertTrue((out / "drawing.json").exists())
            pending_path = tmp / "pending.json"
            doc = _doc()
            del doc["title_block"]["date"]
            pending_path.write_text(
                json.dumps(doc), encoding="utf-8"
            )
            self.assertEqual(
                cli_main([str(pending_path), "--out-dir", str(out)]), 1
            )
            self.assertEqual(
                cli_main([str(tmp / "nope.json"),
                          "--out-dir", str(out)]),
                2,
            )


if __name__ == "__main__":
    unittest.main()
