"""QL-5050PX strip development and DXF contract; no native generation evidence."""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

import ezdxf

from bend_allowance import compute_bend_allowance
from ql5050px.sheet_metal import export_blank_dxf, generate_native, unfold_strip


def expected_flat(legs, angles, thickness, radius, k_factor):
    bends = [compute_bend_allowance(thickness, radius, angle, k_factor) for angle in angles]
    tangents = []
    for index, leg in enumerate(legs):
        setbacks = (bends[index - 1].outside_setback_mm if index else 0)
        setbacks += bends[index].outside_setback_mm if index < len(bends) else 0
        tangents.append(leg - setbacks)
    return sum(tangents) + sum(bend.bend_allowance_mm for bend in bends)


class DevelopmentTests(unittest.TestCase):
    def test_two_leg_strip_geometry(self):
        blank = unfold_strip([100, 50], [90], thickness_mm=2, radius_mm=2,
                             k_factor=0.44, width_mm=80)
        bend = compute_bend_allowance(2, 2, 90, 0.44)
        self.assertAlmostEqual(blank["flat_length_mm"], expected_flat([100, 50], [90], 2, 2, 0.44))
        self.assertEqual(blank["width_mm"], 80.0)
        self.assertEqual(blank["profile_kind"], "serial_constant_width_strip")
        self.assertEqual(blank["native_status"], "unverified")
        self.assertAlmostEqual(blank["bend_lines"][0]["x_mm"],
                               (100 - bend.outside_setback_mm) + bend.bend_allowance_mm / 2)
        self.assertEqual(len(blank["relief_slots"]), 2)
        self.assertEqual([slot["y_mm"] for slot in blank["relief_slots"]], [0.0, 80 - (2 + 2)])
        self.assertAlmostEqual(blank["relief_slots"][0]["depth_mm"], 4.0)
        self.assertAlmostEqual(blank["relief_slots"][0]["width_mm"], 2.0)

    def test_three_leg_strip_line_and_slot_order(self):
        blank = unfold_strip([100, 50, 100], [90, 45], thickness_mm=1.5, radius_mm=1,
                             k_factor=0.4, width_mm=60)
        self.assertAlmostEqual(blank["flat_length_mm"],
                               expected_flat([100, 50, 100], [90, 45], 1.5, 1, 0.4))
        self.assertEqual([round(line["angle_deg"], 6) for line in blank["bend_lines"]], [90.0, 45.0])
        positions = [line["x_mm"] for line in blank["bend_lines"]]
        self.assertEqual(positions, sorted(positions))
        self.assertEqual(len(blank["relief_slots"]), 4)
        self.assertEqual(len(blank["bends"]), 2)

    def test_custom_relief_respected(self):
        blank = unfold_strip([100, 50], [90], thickness_mm=2, radius_mm=2, k_factor=0.44,
                             width_mm=80, relief_width_mm=6, relief_depth_mm=8)
        self.assertEqual(blank["relief_slots"][0]["width_mm"], 6.0)
        self.assertEqual(blank["relief_slots"][0]["depth_mm"], 8.0)

    def test_invalid_strip_refused(self):
        cases = [
            dict(legs_mm=[100], angles_deg=[], width_mm=80),
            dict(legs_mm=[100, 50, 20], angles_deg=[90], width_mm=80),
            dict(legs_mm=[2, 50], angles_deg=[90], width_mm=80),
            dict(legs_mm=[100, 50], angles_deg=[90], width_mm=0),
            dict(legs_mm=[100, "50"], angles_deg=[90], width_mm=80),
            dict(legs_mm=[100, 50], angles_deg=["90"], width_mm=80),
            dict(legs_mm=[100, 50], angles_deg=[0], width_mm=80),
            dict(legs_mm=[100, 50], angles_deg=[90], width_mm=80, thickness_mm=0),
            dict(legs_mm=[100, 50], angles_deg=[90], width_mm=80, radius_mm=-1),
            dict(legs_mm=[100, 50], angles_deg=[90], width_mm=80, k_factor=1.5),
            dict(legs_mm=[100, 50], angles_deg=[90], width_mm=8, radius_mm=3,
                 relief_depth_mm=5),
            dict(legs_mm=[100, 50], angles_deg=[90], width_mm=80, relief_depth_mm=2),
            dict(legs_mm=[100, 50], angles_deg=[90], width_mm=80, relief_width_mm=1),
        ]
        for overrides in cases:
            params = dict(legs_mm=[100, 50], angles_deg=[90], thickness_mm=2,
                          radius_mm=2, k_factor=0.44, width_mm=80)
            params.update(overrides)
            with self.subTest(params=overrides):
                with self.assertRaises(ValueError):
                    unfold_strip(**params)


class BlankDxfTests(unittest.TestCase):
    def test_dxf_contains_contour_and_bend_layers_in_mm(self):
        blank = unfold_strip([100, 50], [90], thickness_mm=2, radius_mm=2,
                             k_factor=0.44, width_mm=80)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "blank.dxf"
            result = export_blank_dxf(blank, path)
            self.assertEqual(result, str(path))
            doc = ezdxf.readfile(path)
            self.assertEqual(doc.dxfversion, "AC1015")
            self.assertEqual(doc.header.get("$INSUNITS"), 4)
            lines = list(doc.modelspace().query("LINE"))
            cut = [line for line in lines if line.dxf.layer == "CUT"]
            bend = [line for line in lines if line.dxf.layer == "BEND"]
            self.assertEqual(len(bend), 1)
            self.assertEqual(len(cut), 12)
            self.assertAlmostEqual(bend[0].dxf.start.x, blank["bend_lines"][0]["x_mm"])
            self.assertAlmostEqual(bend[0].dxf.end.x, blank["bend_lines"][0]["x_mm"])
            self.assertEqual({bend[0].dxf.start.y, bend[0].dxf.end.y}, {0.0, 80.0})
            self.assertEqual(len(doc.audit().errors), 0)

    def test_existing_blank_file_is_not_overwritten(self):
        blank = unfold_strip([100, 50], [90], thickness_mm=2, radius_mm=2,
                             k_factor=0.44, width_mm=80)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "blank.dxf"
            path.write_text("occupied", encoding="ascii")
            with self.assertRaises(FileExistsError):
                export_blank_dxf(blank, path)
            self.assertEqual(path.read_text(encoding="ascii"), "occupied")


class NativeGenerationTests(unittest.TestCase):
    def test_refuses_off_windows(self):
        if sys.platform == "win32":
            self.skipTest("Windows has the native generator; refusal covered off-Windows")
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(RuntimeError, "requires Windows"):
                generate_native(object(), Path(folder) / "part.sldprt", generator_options={})

    def test_refuses_existing_or_wrong_output(self):
        with tempfile.TemporaryDirectory() as folder:
            existing = Path(folder) / "part.sldprt"
            existing.write_text("occupied", encoding="ascii")
            with self.assertRaisesRegex(ValueError, "new SLDPRT"):
                generate_native(object(), existing, generator_options={})
            with self.assertRaisesRegex(ValueError, "new SLDPRT"):
                generate_native(object(), Path(folder) / "part.step", generator_options={})
            self.assertEqual(existing.read_text(encoding="ascii"), "occupied")

    def test_output_path_cannot_be_passed_twice(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, "output_path"):
                generate_native(object(), Path(folder) / "part.sldprt",
                                generator_options={"output_path": "duplicate"})


if __name__ == "__main__":
    unittest.main()
