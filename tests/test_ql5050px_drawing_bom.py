"""QL-5050PX BOM/drawing/DXF data contract; JSON and DXF are not native drawings."""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

import ezdxf

from ql5050px.drawing_bom import (build_bom, drawing_model, export_bom_csv,
                                  export_drawing_json, write_dxf)


class BomTests(unittest.TestCase):
    def test_instances_are_grouped_deterministically(self):
        bom = build_bom([
            {"id": "p1", "part_number": "QL-B", "material": "Q235", "quantity": 2},
            {"id": "p2", "part_number": "QL-A", "material": "Q235"},
            {"id": "p3", "part_number": "QL-B", "material": "Q235", "quantity": 3},
            {"id": "p4", "part_number": "QL-A", "material": "Q235", "configuration": "Alt"},
        ])
        self.assertEqual([row["part_number"] for row in bom], ["QL-A", "QL-A", "QL-B"])
        self.assertEqual([row["item"] for row in bom], [1, 2, 3])
        self.assertEqual(bom[0]["configuration"], "")
        self.assertEqual(bom[2]["quantity"], 5)
        self.assertEqual(bom[2]["instances"], ["p1", "p3"])
        self.assertEqual(bom[0]["status"], "declared_input")
        self.assertFalse(bom[0]["purchased"])

    def test_missing_material_stays_pending(self):
        bom = build_bom([{"id": "x", "part_number": "QL-X"}])
        self.assertEqual(bom[0]["material"], "pending_mapping")
        self.assertEqual(bom[0]["status"], "pending_mapping")

    def test_null_configuration_does_not_break_grouping(self):
        bom = build_bom([
            {"part_number": "QL-A", "configuration": None},
            {"part_number": "QL-A", "configuration": "",
             "purchased": True},
        ])
        self.assertEqual(len(bom), 2)
        self.assertFalse(bom[0]["purchased"])
        self.assertTrue(bom[1]["purchased"])

    def test_quantity_must_be_positive_integer(self):
        for bad in (0, -1, 1.5, True, "2"):
            with self.subTest(quantity=bad):
                with self.assertRaises(ValueError):
                    build_bom([{"part_number": "QL-A", "quantity": bad}])

    def test_part_number_must_be_stable_string(self):
        for bad in (None, "", "   ", 7):
            with self.subTest(part_number=bad):
                with self.assertRaises(ValueError):
                    build_bom([{"part_number": bad}])

    def test_non_string_material_or_configuration_refused(self):
        for overrides in ({"material": 5}, {"configuration": 5}):
            with self.subTest(overrides=overrides):
                with self.assertRaises(ValueError):
                    build_bom([{"part_number": "QL-A", **overrides}])


class DrawingModelTests(unittest.TestCase):
    def test_model_is_explicitly_unverified(self):
        model = drawing_model("QL-STRIP", material="Q235",
                              dimensions_mm={"length": 243.0478, "width": 80},
                              views=[{"orientation": "*Front"}],
                              notes=["simulation fixture"])
        self.assertEqual(model["schema_version"], 1)
        self.assertEqual(model["units"], "mm")
        self.assertEqual(model["dimensions_mm"]["width"], 80)
        self.assertEqual(model["native_status"], "unverified")
        self.assertEqual(model["views"], [{"orientation": "*Front"}])

    def test_bad_dimensions_refused(self):
        for bad in (True, "80", float("nan"), float("inf"), None):
            with self.subTest(value=bad):
                with self.assertRaises(ValueError):
                    drawing_model("QL-STRIP", dimensions_mm={"width": bad})


class FileOutputTests(unittest.TestCase):
    def test_bom_csv_round_trip_and_no_overwrite(self):
        bom = build_bom([{"part_number": "QL-B", "material": "Q235", "quantity": 2},
                         {"part_number": "QL-A"}])
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "bom.csv"
            self.assertEqual(export_bom_csv(bom, path), str(path))
            text = path.read_text(encoding="utf-8-sig")
            self.assertTrue(text.startswith("item,part_number,configuration,material,purchased,quantity,status"))
            self.assertIn("QL-A,,pending_mapping,False,1,pending_mapping", text)
            before = path.read_text(encoding="utf-8-sig")
            with self.assertRaises(FileExistsError):
                export_bom_csv(bom, path)
            self.assertEqual(path.read_text(encoding="utf-8-sig"), before)

    def test_drawing_json_round_trip_and_no_overwrite(self):
        model = drawing_model("QL-STRIP", dimensions_mm={"length": 100.0})
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "drawing.json"
            export_drawing_json(model, path)
            self.assertIn('"native_status": "unverified"', path.read_text(encoding="utf-8"))
            with self.assertRaises(FileExistsError):
                export_drawing_json(model, path)
            self.assertEqual(path.read_text(encoding="utf-8").count("native_status"), 1)

    def test_dxf_lines_layers_and_units(self):
        segments = [((0, 0), (100, 0), "CUT"), ((100, 0), (100, 80), "CUT"),
                    ((50, 0), (50, 80), "BEND")]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "part.dxf"
            write_dxf(segments, path)
            doc = ezdxf.readfile(path)
            self.assertEqual(doc.dxfversion, "AC1015")
            self.assertEqual(doc.header.get("$INSUNITS"), 4)
            self.assertEqual({layer.dxf.name for layer in doc.layers} >= {"CUT", "BEND"}, True)
            lines = list(doc.modelspace().query("LINE"))
            self.assertEqual(len(lines), 3)
            self.assertEqual(sorted(line.dxf.layer for line in lines), ["BEND", "CUT", "CUT"])
            self.assertEqual(len(doc.audit().errors), 0)

    def test_dxf_bad_input_refused(self):
        bad_segments = [
            [((0, 0), (1, 1, 1), "CUT")],
            [((0, 0), (True, 1), "CUT")],
            [((0, 0), (float("nan"), 1), "CUT")],
            [((0, 0), (1, 1), "")],
            [((0, 0), (1, 1), "弯曲")],
            [((0, 0), (1, 1), "A; B")],
        ]
        with tempfile.TemporaryDirectory() as folder:
            for index, segments in enumerate(bad_segments):
                path = Path(folder) / f"bad{index}.dxf"
                with self.subTest(segments=segments):
                    with self.assertRaises(ValueError):
                        write_dxf(segments, path)
                    self.assertFalse(path.exists())

    def test_dxf_no_overwrite(self):
        segments = [((0, 0), (1, 1), "CUT")]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "part.dxf"
            path.write_text("occupied", encoding="ascii")
            with self.assertRaises(FileExistsError):
                write_dxf(segments, path)
            self.assertEqual(path.read_text(encoding="ascii"), "occupied")


if __name__ == "__main__":
    unittest.main()
