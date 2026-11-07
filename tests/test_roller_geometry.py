from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "src"))


import math
import unittest

from roller_drawing import (
    RollerDrawingVariant,
    _DimensionRecord,
    _TextRecord,
    _thread_from_records,
    decode_solidworks_text,
)
from solidworks_generator import (
    SW_END_CONDITION_BLIND,
    SW_END_CONDITION_MID_PLANE,
    SW_END_CONDITION_THROUGH_ALL,
    RollerSpec,
    compute_roller_layout,
    roller_revolve_profile,
    roller_revolve_segments,
    sprocket_geometry,
    sprocket_tooth_pockets,
    validate_roller_spec,
)


class RollerGeometryTests(unittest.TestCase):
    def test_solidworks_end_condition_enums(self) -> None:
        """Blind 必须是 0；若误写成 1 会变成贯通切除，整根筒身被拉槽。"""

        self.assertEqual(SW_END_CONDITION_BLIND, 0)
        self.assertEqual(SW_END_CONDITION_THROUGH_ALL, 1)
        self.assertEqual(SW_END_CONDITION_MID_PLANE, 6)
        self.assertNotEqual(SW_END_CONDITION_BLIND, SW_END_CONDITION_THROUGH_ALL)

    def test_sprocket_geometry_matches_reference_part(self) -> None:
        pitch_radius, seat_radius, tip_radius = sprocket_geometry(14, 12.7)
        self.assertAlmostEqual(pitch_radius, 28.25, places=6)
        self.assertAlmostEqual(tip_radius, 33.25, places=3)
        self.assertAlmostEqual(seat_radius, 4.5, places=3)

    def test_tooth_pockets_closed_and_count(self) -> None:
        pitch_radius, seat_radius, tip_radius = sprocket_geometry(14, 12.7)
        pockets = sprocket_tooth_pockets(14, pitch_radius, seat_radius, tip_radius)
        self.assertEqual(len(pockets), 14)
        for pocket in pockets:
            self.assertEqual(len(pocket), 4)
            start = pocket[0]["start"]
            end = pocket[-1]["end"]
            self.assertAlmostEqual(start[0], end[0], places=6)  # type: ignore[index]
            self.assertAlmostEqual(start[1], end[1], places=6)  # type: ignore[index]
            seat_center = pocket[0]["center"]
            self.assertAlmostEqual(
                math.hypot(seat_center[0], seat_center[1]),  # type: ignore[index]
                28.25,
                places=6,
            )

    def test_fillets_are_single_arc_entities(self) -> None:
        """批量标准：每个圆角必须是单段 arc，不能是多段折线。"""

        powered = RollerSpec(
            roller_type="动力滚筒",
            overall_length_mm=280.0,
            outer_diameter_mm=50.0,
            wall_thickness_mm=1.2,
            shaft_diameter_mm=12.0,
            shaft_projection_mm=13.5,
            sprocket_teeth=14,
            chain_pitch_mm=12.7,
            shaft_exposed_mm=5.0,
            shaft_thread_designation="M10",
        )
        powered_segments = roller_revolve_segments(
            powered, compute_roller_layout(powered)
        )
        powered_arcs = [
            segment for segment in powered_segments if segment["kind"] == "arc"
        ]
        self.assertEqual(len(powered_arcs), 3)
        self.assertEqual(
            sorted(float(arc["radius"]) for arc in powered_arcs),  # type: ignore[arg-type]
            [0.5, 5.0, 5.0],
        )

        unpowered = RollerSpec(
            roller_type="无动力滚筒",
            overall_length_mm=330.0,
            outer_diameter_mm=50.0,
            wall_thickness_mm=1.2,
            shaft_diameter_mm=12.0,
            shaft_projection_mm=5.0,
            shaft_exposed_mm=5.0,
            shaft_thread_designation="M8",
        )
        unpowered_layout = compute_roller_layout(unpowered)
        # 批量标准：标注伸出=光轴段时仍补一级台阶（轴径+3）。
        self.assertAlmostEqual(unpowered_layout.barrel_length_mm, 310.0)
        self.assertAlmostEqual(unpowered_layout.body_min_mm, -155.0)
        self.assertAlmostEqual(unpowered_layout.body_max_mm, 155.0)
        unpowered_segments = roller_revolve_segments(unpowered, unpowered_layout)
        unpowered_arcs = [
            segment for segment in unpowered_segments if segment["kind"] == "arc"
        ]
        self.assertEqual(len(unpowered_arcs), 2)
        for arc in unpowered_arcs:
            self.assertAlmostEqual(float(arc["radius"]), 2.0, places=3)  # type: ignore[arg-type]
        journal_horizontals = [
            segment
            for segment in unpowered_segments
            if segment["kind"] == "line"
            and abs(float(segment["start"][1]) - 6.0) < 1e-6  # type: ignore[index]
            and abs(float(segment["end"][1]) - 6.0) < 1e-6  # type: ignore[index]
        ]
        self.assertGreaterEqual(len(journal_horizontals), 2)
        step_horizontals = [
            segment
            for segment in unpowered_segments
            if segment["kind"] == "line"
            and abs(float(segment["start"][1]) - 7.5) < 1e-6  # type: ignore[index]
            and abs(float(segment["end"][1]) - 7.5) < 1e-6  # type: ignore[index]
        ]
        self.assertGreaterEqual(len(step_horizontals), 2)
        step_verticals = [
            segment
            for segment in unpowered_segments
            if segment["kind"] == "line"
            and abs(float(segment["start"][0]) - float(segment["end"][0])) < 1e-6  # type: ignore[index]
            and {
                round(float(segment["start"][1]), 3),  # type: ignore[index]
                round(float(segment["end"][1]), 3),  # type: ignore[index]
            }
            == {6.0, 7.5}
        ]
        self.assertGreaterEqual(len(step_verticals), 2)

        # 另一规格也必须走同一标准（轴径 20 → 台阶 Ø23），证明不绑死单张样例图。
        other = RollerSpec(
            roller_type="无动力滚筒",
            overall_length_mm=500.0,
            outer_diameter_mm=76.0,
            wall_thickness_mm=1.5,
            shaft_diameter_mm=20.0,
            shaft_projection_mm=8.0,
            shaft_exposed_mm=5.0,
            shaft_thread_designation="M10",
            shaft_step_diameter_mm=25.0,
        )
        other_layout = compute_roller_layout(other)
        # 伸出 8 > 光轴 5 → 台阶长 3，总伸出 8，筒身 484。
        self.assertAlmostEqual(other_layout.barrel_length_mm, 484.0)
        other_segments = roller_revolve_segments(other, other_layout)
        other_step = [
            segment
            for segment in other_segments
            if segment["kind"] == "line"
            and abs(float(segment["start"][1]) - 12.5) < 1e-6  # type: ignore[index]
            and abs(float(segment["end"][1]) - 12.5) < 1e-6  # type: ignore[index]
        ]
        self.assertGreaterEqual(len(other_step), 2)

    def test_phi50x280_matches_reference_sldprt_sketch1(self) -> None:
        """逐点对齐《201不锈钢滚筒-…-Φ50x280》草图1 / 草图6。"""

        spec = RollerSpec(
            roller_type="动力滚筒",
            overall_length_mm=280.0,
            outer_diameter_mm=50.0,
            wall_thickness_mm=1.2,
            shaft_diameter_mm=12.0,
            shaft_projection_mm=13.5,
            sprocket_teeth=14,
            chain_pitch_mm=12.7,
            shaft_exposed_mm=5.0,
            shaft_thread_designation="M10",
        )
        layout = compute_roller_layout(spec)
        self.assertAlmostEqual(layout.body_max_mm, 126.5)
        self.assertAlmostEqual(layout.tube_min_mm or 0.0, -124.5)
        self.assertAlmostEqual(layout.tube_max_mm or 0.0, 77.5)
        self.assertAlmostEqual(layout.hub_min_mm or 0.0, 82.5)
        self.assertAlmostEqual(layout.hub_diameter_mm or 0.0, 37.0)
        self.assertEqual(layout.sprocket_rows_mm, ((98.5, 103.5), (120.5, 125.5)))
        self.assertEqual(layout.sprocket_cut_span_mm, (96.5, 126.5))
        self.assertAlmostEqual(layout.sprocket_outer_diameter_mm or 0.0, 66.5)
        self.assertAlmostEqual(layout.sprocket_root_diameter_mm or 0.0, 47.5)
        self.assertAlmostEqual(layout.sprocket_pitch_radius_mm or 0.0, 28.25)

        segments = roller_revolve_segments(spec, layout)
        points: list[tuple[float, float]] = []
        for segment in segments:
            start = segment["start"]
            end = segment["end"]
            assert isinstance(start, tuple) and isinstance(end, tuple)
            points.extend((start, end))  # type: ignore[arg-type]

        def has(point: tuple[float, float], tol: float = 1e-4) -> bool:
            return any(
                abs(existing[0] - point[0]) < tol
                and abs(existing[1] - point[1]) < tol
                for existing in points
            )

        for point in (
            (-140.0, 7.5),
            (-135.0, 7.5),
            (-134.5, 9.0),
            (-129.5, 9.0),
            (-129.5, 20.0),
            (-124.5, 25.0),
            (77.5, 25.0),
            (82.5, 20.0),
            (82.5, 18.5),
            (98.5, 33.25),
            (125.5, 33.25),
            (126.5, 23.75),
            (140.0, 7.5),
        ):
            self.assertTrue(has(point), msg=f"missing reference point {point}")

        # 段与段端点闭合，避免 SolidWorks 识别不到闭合轮廓。
        for first, second in zip(segments, segments[1:]):
            self.assertEqual(first["end"], second["start"])
        self.assertEqual(segments[0]["start"], segments[-1]["end"])

        profile = roller_revolve_profile(spec, layout)
        self.assertAlmostEqual(validate_roller_spec(spec), 253.0)
        self.assertEqual(profile[0], (-140.0, 0.0))
        self.assertEqual(profile[-1], (140.0, 0.0))

    def test_powered_with_long_shaft_projection_stays_consistent(self) -> None:
        """图纸常见轴头伸出 18.5：无链轮端 R5 不得跑到端面外侧。"""

        spec = RollerSpec(
            roller_type="动力滚筒",
            overall_length_mm=280.0,
            outer_diameter_mm=50.0,
            wall_thickness_mm=1.2,
            shaft_diameter_mm=12.0,
            shaft_projection_mm=18.5,
            sprocket_teeth=14,
            chain_pitch_mm=12.7,
            shaft_exposed_mm=5.0,
            shaft_thread_designation="M8",
        )
        layout = compute_roller_layout(spec)
        segments = roller_revolve_segments(spec, layout)
        self.assertGreaterEqual(layout.tube_min_mm or 0.0, layout.body_min_mm - 1e-6)
        arcs = [segment for segment in segments if segment["kind"] == "arc"]
        self.assertEqual(len(arcs), 3)
        for first, second in zip(segments, segments[1:]):
            self.assertEqual(first["end"], second["start"])

    def test_unpowered_has_no_sprocket_rows(self) -> None:
        spec = RollerSpec(
            roller_type="无动力滚筒",
            overall_length_mm=525.0,
            outer_diameter_mm=50.0,
            wall_thickness_mm=1.2,
            shaft_diameter_mm=12.0,
            shaft_projection_mm=13.5,
            shaft_exposed_mm=5.0,
            shaft_thread_designation="M10",
        )
        layout = compute_roller_layout(spec)
        self.assertEqual(layout.sprocket_rows_mm, ())
        self.assertIsNone(layout.sprocket_outer_diameter_mm)

    def test_thread_parser_reads_m8_callout(self) -> None:
        texts = (_TextRecord("2-M8-20深", 0.0, 0.0),)
        self.assertEqual(_thread_from_records(texts, ()), "M8")
        dims = (_DimensionRecord("2-M10-25", 10.0, 0.0, 0.0),)
        self.assertEqual(_thread_from_records((), dims), "M10")

    def test_decode_solidworks_text(self) -> None:
        encoded = r"201\U+4E0D\U+9508\U+94A2\U+52A8\U+529B\U+6EDA\U+7B52"
        self.assertIn("动力滚筒", decode_solidworks_text(encoded))

    def test_variant_thread_field(self) -> None:
        variant = RollerDrawingVariant(
            "动力滚筒",
            1,
            280.0,
            50.0,
            1.2,
            12.0,
            13.5,
            5.0,
            14,
            12.7,
            "note",
            shaft_thread_designation="M10",
        )
        self.assertEqual(variant.shaft_thread_designation, "M10")
        self.assertTrue(variant.is_powered)


if __name__ == "__main__":
    unittest.main()
