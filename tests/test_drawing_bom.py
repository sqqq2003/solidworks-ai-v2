"""Issue #6 module 5: drawing / DXF / BOM data and export interface tests."""

from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from src.batch_export import SheetPartJob
from src.drawing_bom import (
    bom_csv_rows,
    bom_from_parametric_plan,
    bom_from_sheet_jobs,
    bom_from_variants,
    drawing_hints_for_bom,
    export_plan,
    write_bom_csv,
)
from src.ql5050px.solver import solve_spec
from src.roller_drawing import RollerDrawingVariant


def sheet_job(**kwargs) -> SheetPartJob:
    base = {
        "profile_index": 0,
        "bend_indices": (),
        "area_mm2": 49749.33,
        "label": "件01_#1",
        "quantity": 1,
        "thickness_mm": 2.5,
        "thickness_source": "分区大字「板厚 2.5」",
        "quantity_source": "「J1 X 2件」",
        "size_hint": "420x180",
    }
    base.update(kwargs)
    return SheetPartJob(**base)


def variant(**kwargs) -> RollerDrawingVariant:
    base = {
        "roller_type": "无动力滚筒",
        "quantity": 2,
        "overall_length_mm": 1000.0,
        "outer_diameter_mm": 50.0,
        "wall_thickness_mm": 1.2,
        "shaft_diameter_mm": 12.0,
        "shaft_projection_mm": 18.0,
        "shaft_exposed_mm": None,
        "sprocket_teeth": None,
        "chain_pitch_mm": None,
        "note": "synthetic",
    }
    base.update(kwargs)
    return RollerDrawingVariant(**base)


class BomFromSheetJobsTests(unittest.TestCase):
    def test_rows_reuse_batch_export_naming(self):
        report = bom_from_sheet_jobs([sheet_job(quantity=2)])
        self.assertEqual(report.status, "planned")
        self.assertEqual(len(report.items), 1)
        item = report.items[0]
        self.assertEqual(item.name, "01×2 2.5mm.SLDPRT")
        self.assertEqual(item.quantity, 2)
        self.assertEqual(item.thickness_mm, 2.5)
        self.assertEqual(item.source, "分区大字「板厚 2.5」")
        self.assertEqual(item.size_hint, "420x180")
        payload = report.to_dict()
        self.assertFalse(payload["cad_executed"])
        self.assertEqual(payload["sw_live"], "not_applicable_on_linux")

    def test_interface_default_is_labeled(self):
        report = bom_from_sheet_jobs(
            [sheet_job(thickness_mm=None, thickness_source="")], default_thickness_mm=2.0
        )
        self.assertEqual(report.status, "planned")
        self.assertEqual(report.items[0].thickness_mm, 2.0)
        self.assertEqual(report.items[0].source, "interface default (not a drawing value)")

    def test_missing_thickness_stays_unresolved(self):
        report = bom_from_sheet_jobs([sheet_job(thickness_mm=None, thickness_source="")])
        self.assertEqual(report.status, "review_required")
        self.assertIsNone(report.items[0].thickness_mm)
        self.assertEqual(report.items[0].name, "件01_#1")
        self.assertEqual(len(report.unresolved), 1)
        self.assertIn("sheet thickness unresolved", report.unresolved[0]["reason"])

    def test_material_and_drawing_ref_are_carried(self):
        report = bom_from_sheet_jobs(
            [sheet_job()], material="软钢/冷轧", drawing_ref="QL-5050PX-01.dwg"
        )
        item = report.items[0]
        self.assertEqual(item.material, "软钢/冷轧")
        self.assertEqual(item.drawing_ref, "QL-5050PX-01.dwg")


class BomFromVariantsTests(unittest.TestCase):
    def test_roller_rows_reuse_roller_spec(self):
        report = bom_from_variants([variant()])
        self.assertEqual(report.status, "planned")
        item = report.items[0]
        self.assertEqual(item.quantity, 2)
        self.assertEqual(item.thickness_mm, 1.2)
        self.assertEqual(item.source, "roller_spec wall thickness")
        self.assertIn("无动力滚筒", item.name)

    def test_missing_dimensions_stay_unresolved(self):
        report = bom_from_variants([variant(overall_length_mm=None)])
        self.assertEqual(report.status, "review_required")
        self.assertIsNone(report.items[0].thickness_mm)
        self.assertIn("缺少总长", report.unresolved[0]["reason"])


class BomFromParametricPlanTests(unittest.TestCase):
    def test_mock_bom_for_missing_model(self):
        plan = solve_spec()
        report = bom_from_parametric_plan(plan, drawing_ref="QL-5050PX")
        self.assertEqual(report.status, "review_required")
        self.assertEqual(report.backend, "mock_plan")
        names = [item.name for item in report.items]
        self.assertIn("mount (mock, no model)", names)
        mount = next(item for item in report.items if item.name.startswith("mount"))
        self.assertIsNone(mount.thickness_mm)
        self.assertEqual(mount.size_hint, "1800x900x1500")
        self.assertTrue(any("unmapped" in row["reason"] for row in report.unresolved))
        payload = report.to_dict()
        self.assertFalse(payload["cad_executed"])


class BomCsvTests(unittest.TestCase):
    def test_csv_rows_and_file(self):
        report = bom_from_sheet_jobs([sheet_job()], material="软钢/冷轧")
        rows = bom_csv_rows(report)
        self.assertEqual(rows[0][0], "sequence")
        self.assertEqual(rows[1][1], "01×1 2.5mm.SLDPRT")
        self.assertEqual(rows[1][3], "2.5")
        with tempfile.TemporaryDirectory() as folder:
            path = write_bom_csv(report, Path(folder) / "bom.csv")
            with path.open(encoding="utf-8-sig") as stream:
                written = list(csv.reader(stream))
        self.assertEqual(written[0], rows[0])
        self.assertEqual(written[1], [str(cell) for cell in rows[1]])


class ExportPlanTests(unittest.TestCase):
    def setUp(self):
        self.report = bom_from_sheet_jobs([sheet_job()])
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)

    def test_mock_trace_is_written_for_json(self):
        destination = self.root / "trace.json"
        trace = export_plan(self.report, destination=destination)
        self.assertEqual(trace["status"], "mock_trace")
        self.assertFalse(trace["dxf_written"])
        self.assertFalse(trace["dwg_written"])
        self.assertFalse(trace["slddrw_written"])
        self.assertFalse(trace["cad_executed"])
        self.assertEqual(trace["sw_live"], "not_applicable_on_linux")
        payload = json.loads(destination.read_text(encoding="utf-8"))
        self.assertEqual(payload["requested_formats"], ["dxf"])
        self.assertIn("bom", payload)

    def test_mock_refuses_drawing_product_suffix(self):
        trace = export_plan(self.report, destination=self.root / "flat.dxf")
        self.assertEqual(trace["status"], "refused")
        self.assertTrue(any("CAD or drawing product file" in row for row in trace["refusals"]))
        self.assertFalse((self.root / "flat.dxf").exists())

    def test_live_backend_is_refused_offline(self):
        trace = export_plan(
            self.report, destination=self.root / "trace.json", backend="live"
        )
        self.assertEqual(trace["status"], "refused")
        self.assertTrue(any("not available in this offline framework" in row for row in trace["refusals"]))

    def test_existing_destination_is_not_overwritten(self):
        destination = self.root / "trace.json"
        destination.write_text("keep me", encoding="utf-8")
        trace = export_plan(self.report, destination=destination)
        self.assertEqual(trace["status"], "refused")
        self.assertEqual(destination.read_text(encoding="utf-8"), "keep me")

    def test_unknown_format_is_refused(self):
        trace = export_plan(
            self.report, destination=self.root / "trace.json", formats=("step",)
        )
        self.assertEqual(trace["status"], "refused")
        self.assertTrue(any("unsupported export formats" in row for row in trace["refusals"]))


class DrawingHintsTests(unittest.TestCase):
    def test_hints_from_synthetic_dxf(self):
        import ezdxf

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "hints.dxf"
            doc = ezdxf.new("R2010")
            doc.units = ezdxf.units.MM
            doc.modelspace().add_text("板厚 2.5", dxfattribs={"height": 5.0}).set_placement((0, 0))
            doc.saveas(path)
            hints = drawing_hints_for_bom(path)
        self.assertEqual(hints["thickness_mm"], 2.5)
        self.assertIn("drawing_notes", hints["source"])

    def test_hints_for_dwg_return_empty(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "not-a-drawing.dwg"
            path.write_bytes(b"not a real dwg")
            hints = drawing_hints_for_bom(path)
        self.assertIsNone(hints["thickness_mm"])


if __name__ == "__main__":
    unittest.main()
