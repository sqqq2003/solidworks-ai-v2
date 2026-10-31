
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "src"))
import math
import unittest
from types import SimpleNamespace

from cad_analyzer import Primitive, SketchSegment
from solidworks_generator import (
    DEFAULT_CHAIN_PITCH_MM,
    BendRejectedError,
    RollerSpec,
    SolidWorksGenerationError,
    _arc_direction,
    _create_sketch,
    _validate_single_closed_contour,
    compute_roller_layout,
    profile_bend_indices,
    roller_revolve_profile,
    sprocket_geometry,
    sprocket_pocket_area,
    sprocket_tooth_pockets,
    suggest_relief_cutouts,
    validate_roller_spec,
)


class RollerSpecValidationTests(unittest.TestCase):
    def test_uses_drawing_total_length_and_required_shaft_projection(self) -> None:
        spec = RollerSpec(
            "动力滚筒",
            655.0,
            50.0,
            1.2,
            15.0,
            20.0,
            14,
            12.7,
        )

        self.assertAlmostEqual(validate_roller_spec(spec), 615.0)

    def test_accepts_unpowered_roller_without_sprocket_parameters(self) -> None:
        spec = RollerSpec(
            "无动力滚筒",
            280.0,
            50.0,
            1.2,
            15.0,
            15.0,
        )

        self.assertAlmostEqual(validate_roller_spec(spec), 250.0)

    def test_rejects_wall_thicker_than_half_the_diameter(self) -> None:
        spec = RollerSpec("无动力滚筒", 280, 50, 25, 15, 15)

        with self.assertRaisesRegex(ValueError, "筒壁厚"):
            validate_roller_spec(spec)

    def test_rejects_shaft_projection_that_leaves_no_barrel(self) -> None:
        spec = RollerSpec("无动力滚筒", 280, 50, 1.2, 15, 139.0)

        with self.assertRaisesRegex(ValueError, "轴头伸出量"):
            validate_roller_spec(spec)

    def test_requires_integer_sprocket_teeth_for_powered_roller(self) -> None:
        spec = RollerSpec("动力滚筒", 655, 50, 1.2, 15, 20, 14.5)

        with self.assertRaisesRegex(ValueError, "齿数"):
            validate_roller_spec(spec)

    def test_rejects_sprocket_parameters_on_unpowered_roller(self) -> None:
        spec = RollerSpec("无动力滚筒", 280, 50, 1.2, 15, 15, 14)

        with self.assertRaisesRegex(ValueError, "无动力滚筒"):
            validate_roller_spec(spec)

    def test_powered_layout_matches_14_tooth_4_fen_reference(self) -> None:
        spec = RollerSpec(
            "动力滚筒",
            280,
            50,
            1.2,
            12,
            20,
            14,
            DEFAULT_CHAIN_PITCH_MM,
        )

        layout = compute_roller_layout(spec)

        # 参考件实测齿顶圆 Ø66.5（见 README「完整外形参考」与
        # SPROCKET_TIP_RADIUS_REF_MM）。旧断言用的理论分度圆推导值已废弃。
        self.assertAlmostEqual(layout.sprocket_outer_diameter_mm, 66.5, places=3)
        self.assertEqual(len(layout.sprocket_rows_mm), 2)
        for row_start, row_end in layout.sprocket_rows_mm:
            self.assertGreater(row_start, layout.body_min_mm)
            self.assertLessEqual(row_end, layout.body_max_mm)
            self.assertGreater(row_end - row_start, 0)
        # 缩径轮毂：直径小于筒身，也小于链轮齿根圆，保证切齿不切到轮毂
        self.assertIsNotNone(layout.hub_diameter_mm)
        self.assertLess(layout.hub_diameter_mm, spec.outer_diameter_mm)
        self.assertIsNotNone(layout.sprocket_root_diameter_mm)
        self.assertLess(layout.hub_diameter_mm, layout.sprocket_root_diameter_mm)
        # 动力款无链轮端的 R5 外侧切点相对 body_min 内偏 2mm（见
        # compute_roller_layout 的注释，与回转轮廓一致）；
        # 只有无动力款才是筒身=本体。
        self.assertAlmostEqual(layout.tube_min_mm, layout.body_min_mm + 2.0, places=3)
        self.assertEqual(layout.hub_max_mm, layout.body_max_mm)
        self.assertLess(layout.tube_max_mm, layout.hub_min_mm)
        # 一次盲切覆盖两排链轮
        self.assertIsNotNone(layout.sprocket_cut_span_mm)
        cut_start, cut_end = layout.sprocket_cut_span_mm
        # 切槽两端各外扩 SPROCKET_CUT_OVERSHOOT_REF_MM（参考件 1mm）保证切净，
        # 所以断言的是「完整覆盖两排」，而不是精确相等。
        self.assertLessEqual(cut_start, layout.sprocket_rows_mm[0][0])
        self.assertGreaterEqual(cut_end, layout.sprocket_rows_mm[1][1])

    def test_unpowered_layout_has_no_sprocket_rows(self) -> None:
        spec = RollerSpec("无动力滚筒", 280, 50, 1.2, 12, 15)

        layout = compute_roller_layout(spec)

        self.assertIsNone(layout.sprocket_outer_diameter_mm)
        self.assertEqual(layout.sprocket_rows_mm, ())
        self.assertEqual(len(layout.cavity_spans_mm), 1)
        self.assertEqual(layout.tube_min_mm, layout.body_min_mm)
        self.assertEqual(layout.tube_max_mm, layout.body_max_mm)

    def test_sprocket_tooth_profile_matches_reference_part(self) -> None:
        pitch_radius, seat_radius, tip_radius = sprocket_geometry(
            14, DEFAULT_CHAIN_PITCH_MM
        )

        # 参考件实测：齿顶圆 Ø66.5、齿沟圆弧 R4.5、齿根辅助圆 Ø47.5
        # （201不锈钢滚筒-动力-壁厚1.2mm-双排链轮4分14齿-Φ50x280.SLDPRT）
        self.assertAlmostEqual(2 * tip_radius, 66.5, places=3)
        self.assertAlmostEqual(seat_radius, 4.5, places=3)
        self.assertAlmostEqual(
            2 * (pitch_radius - seat_radius),
            47.5,
            places=3,
        )

        pockets = sprocket_tooth_pockets(
            14,
            pitch_radius,
            seat_radius,
            tip_radius,
        )

        self.assertEqual(len(pockets), 14)
        self.assertTrue(all(len(pocket) == 4 for pocket in pockets))
        area = sprocket_pocket_area(pockets[0])
        self.assertGreater(area, 60.0)
        self.assertLess(area, 120.0)
        # 齿顶两角都落在齿顶圆上
        for pocket in pockets:
            for curve in pocket:
                if curve["kind"] != "arc":
                    continue
                if curve["radius"] != tip_radius:
                    continue
                for point in (curve["start"], curve["end"]):
                    self.assertAlmostEqual(
                        math.hypot(point[0], point[1]),
                        tip_radius,
                        places=6,
                    )

    def test_roller_revolve_profile_has_hub_groove_and_journal(self) -> None:
        spec = RollerSpec("动力滚筒", 280.0, 50.0, 1.2, 15.0, 13.5, 14, 12.7, 5.0)
        layout = compute_roller_layout(spec)

        profile = roller_revolve_profile(spec, layout)
        radii = [point[1] for point in profile]

        self.assertIn(25.0, radii)  # 筒身外径 Ø50
        self.assertIn(layout.hub_diameter_mm / 2.0, radii)  # 缩径轮毂
        self.assertIn(9.0, radii)  # 轴端台阶 Ø18
        # 挡圈槽槽底小于轴半径
        self.assertLess(min(radii), 7.5)
        self.assertAlmostEqual(profile[0][0], -140.0)
        self.assertAlmostEqual(profile[-1][0], 140.0)


class ProfileBendMatchingTests(unittest.TestCase):
    def test_matches_fold_lines_whose_midpoint_is_inside_profile(self) -> None:
        profile = Primitive(
            ((0, 0), (100, 0), (100, 50), (0, 50), (0, 0)),
            True,
            False,
            "OUTLINE",
            "LINE_LOOP",
        )
        bends = (
            Primitive(((10, 25), (90, 25)), False, True, "BEND", "LINE"),
            Primitive(((110, 25), (120, 25)), False, True, "BEND", "LINE"),
            Primitive(((20, 50), (80, 50)), False, True, "BEND", "LINE"),
        )

        self.assertEqual(profile_bend_indices(profile, bends), (0, 2))

    def test_does_not_match_open_profile(self) -> None:
        profile = Primitive(
            ((0, 0), (100, 0), (100, 50)),
            False,
            False,
            "OUTLINE",
            "LINE",
        )
        bend = Primitive(((10, 25), (90, 25)), False, True, "BEND", "LINE")

        self.assertEqual(profile_bend_indices(profile, (bend,)), ())


class ReliefCutoutSuggestionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.outer = Primitive(
            ((0, 0), (100, 0), (100, 100), (0, 100), (0, 0)),
            True,
            False,
            "OUTLINE",
            "LINE_LOOP",
        )
        self.bends = (
            Primitive(((10, 50), (40, 50)), False, True, "BEND", "LINE"),
            Primitive(((50, 10), (50, 40)), False, True, "BEND", "LINE"),
        )
        self.analysis = SimpleNamespace(bend_lines=self.bends)

    def test_suggests_circle_at_extended_intersection_without_existing_slot(self) -> None:
        cutouts = suggest_relief_cutouts(
            self.analysis,
            (self.outer,),
            0,
            (0, 1),
            2.0,
            1,
        )

        # 延长交点 (50,50) 优先；四条延长到外轮廓的端部也要给槽
        # （见 suggest_relief_cutouts 文档：即使有交点，端部也常需要槽）。
        centers = sorted(cutout.center for cutout in cutouts)
        self.assertEqual(len(cutouts), 5)
        self.assertEqual(
            centers,
            [(0.0, 50.0), (50.0, 0.0), (50.0, 50.0), (50.0, 100.0), (100.0, 50.0)],
        )
        # 预览圆孔：step × 0.5t。t=2、step=1 → 1.0。生成路径不使用这些圆孔。
        self.assertTrue(all(cutout.radius_mm == 1.0 for cutout in cutouts))
        self.assertTrue(
            all(cutout.replaced_profile_index is None for cutout in cutouts)
        )

    def test_expands_existing_circle_by_half_thickness_per_step(self) -> None:
        circle = Primitive(
            ((48, 50), (50, 52), (52, 50), (50, 48), (48, 50)),
            True,
            False,
            "HOLE",
            "CIRCLE",
            circle_center=(50.0, 50.0),
            circle_radius=2.0,
        )
        cutouts = suggest_relief_cutouts(
            self.analysis,
            (self.outer, circle),
            0,
            (0, 1),
            2.0,
            3,
        )

        self.assertEqual(cutouts[0].radius_mm, 5.0)
        self.assertEqual(cutouts[0].replaced_profile_index, 1)

    def test_does_not_replace_a_distant_circle(self) -> None:
        circle = Primitive(
            ((78, 80), (80, 82), (82, 80), (80, 78), (78, 80)),
            True,
            False,
            "HOLE",
            "CIRCLE",
            circle_center=(80.0, 80.0),
            circle_radius=2.0,
        )
        cutouts = suggest_relief_cutouts(
            self.analysis,
            (self.outer, circle),
            0,
            (0, 1),
            2.0,
            1,
        )

        self.assertIsNone(cutouts[0].replaced_profile_index)

    def test_falls_back_to_profile_ends_when_bends_do_not_intersect(self) -> None:
        # 平行折弯线延长后不相交，退回到折弯线与外轮廓的交点。
        parallel_analysis = SimpleNamespace(
            bend_lines=(
                Primitive(((0, 40), (60, 40)), False, True, "BEND", "LINE"),
                Primitive(((0, 60), (60, 60)), False, True, "BEND", "LINE"),
            )
        )

        cutouts = suggest_relief_cutouts(
            parallel_analysis,
            (self.outer,),
            0,
            (0, 1),
            2.0,
            1,
        )

        self.assertEqual(
            sorted(cutout.center for cutout in cutouts),
            [(0.0, 40.0), (0.0, 60.0)],
        )

    def test_single_rejected_bend_gets_relief_at_both_ends(self) -> None:
        # 单条折弯线被拒绝时，此前会因为没有第二条折弯线而直接放弃。
        single_analysis = SimpleNamespace(
            bend_lines=(
                Primitive(((0, 50), (100, 50)), False, True, "BEND", "LINE"),
            )
        )

        cutouts = suggest_relief_cutouts(
            single_analysis,
            (self.outer,),
            0,
            (0,),
            2.0,
            1,
        )

        self.assertEqual(
            sorted(cutout.center for cutout in cutouts),
            [(0.0, 50.0), (100.0, 50.0)],
        )
        # 预览圆孔：step × 0.5t。t=2、step=1 → 1.0。
        self.assertTrue(all(cutout.radius_mm == 1.0 for cutout in cutouts))

    def test_extends_bend_inside_profile_to_outline(self) -> None:
        # 图纸把折弯线画成悬在零件内部的短线段时，沿折弯方向延长到轮廓取位置。
        inside_analysis = SimpleNamespace(
            bend_lines=(
                Primitive(((20, 50), (80, 50)), False, True, "BEND", "LINE"),
            )
        )

        cutouts = suggest_relief_cutouts(
            inside_analysis,
            (self.outer,),
            0,
            (0,),
            2.0,
            1,
        )

        self.assertEqual(
            sorted(cutout.center for cutout in cutouts),
            [(0.0, 50.0), (100.0, 50.0)],
        )

    def test_rejects_bends_that_never_meet_the_profile(self) -> None:
        outside_analysis = SimpleNamespace(
            bend_lines=(
                Primitive(((220, 220), (250, 220)), False, True, "BEND", "LINE"),
            )
        )

        with self.assertRaisesRegex(ValueError, "没有落在外轮廓上"):
            suggest_relief_cutouts(
                outside_analysis,
                (self.outer,),
                0,
                (0,),
                2.0,
                1,
            )

    def test_requires_at_least_one_bend(self) -> None:
        with self.assertRaisesRegex(ValueError, "没有可用的折弯线"):
            suggest_relief_cutouts(
                self.analysis,
                (self.outer,),
                0,
                (),
                2.0,
                1,
            )

    def test_bend_rejection_records_failed_lines_and_retry_state(self) -> None:
        error = BendRejectedError((1, 3), relief_step=2)

        self.assertEqual(error.bend_indices, (1, 3))
        self.assertEqual(error.relief_step, 2)
        self.assertIn("第 2, 4 条", str(error))
        self.assertIn("扩大释放槽 2 次", str(error))


class SketchCurveTests(unittest.TestCase):
    def test_accepts_one_closed_solidworks_contour(self) -> None:
        class Module:
            def ISketch(self, instance: object) -> object:
                return instance

            def ISketchContour(self, instance: object) -> object:
                return instance

        class Contour:
            @property
            def _oleobj_(self) -> "Contour":
                return self

            def IsClosed(self) -> bool:
                return True

        class Sketch:
            @property
            def _oleobj_(self) -> "Sketch":
                return self

            def GetSketchContours(self) -> tuple[Contour, ...]:
                return (Contour(),)

        class Feature:
            def GetSpecificFeature2(self) -> Sketch:
                return Sketch()

        _validate_single_closed_contour(
            Feature(),
            Primitive(
                ((0, 0), (10, 0), (10, 10), (0, 10), (0, 0)),
                True,
                False,
                "OUTLINE",
                "LINE_LOOP",
            ),
            Module(),
        )

    def test_rejects_multiple_or_open_solidworks_contours(self) -> None:
        class Module:
            def ISketch(self, instance: object) -> object:
                return instance

            def ISketchContour(self, instance: object) -> object:
                return instance

        class Contour:
            def __init__(self, closed: bool) -> None:
                self.closed = closed

            @property
            def _oleobj_(self) -> "Contour":
                return self

            def IsClosed(self) -> bool:
                return self.closed

        class Sketch:
            @property
            def _oleobj_(self) -> "Sketch":
                return self

            def GetSketchContours(self) -> tuple[Contour, ...]:
                return (Contour(True), Contour(False))

        class Feature:
            def GetSpecificFeature2(self) -> Sketch:
                return Sketch()

        profile = Primitive(
            ((0, 0), (10, 0), (10, 10), (0, 10), (0, 0)),
            True,
            False,
            "OUTLINE",
            "LINE_LOOP",
        )
        with self.assertRaisesRegex(
            SolidWorksGenerationError,
            "断点、重叠线、自交",
        ):
            _validate_single_closed_contour(Feature(), profile, Module())

    def test_uses_native_solidworks_arc_for_exact_curve_segment(self) -> None:
        class SketchManager:
            def __init__(self) -> None:
                self.lines: list[tuple[float, ...]] = []
                self.arcs: list[tuple[float, ...]] = []
                self.AddToDB = False
                self.write_modes: list[bool] = []

            def CreateLine(self, *coordinates: float) -> None:
                self.lines.append(coordinates)
                self.write_modes.append(self.AddToDB)

            def CreateArc(self, *coordinates: float) -> None:
                self.arcs.append(coordinates)
                self.write_modes.append(self.AddToDB)

        sketch = SketchManager()
        arc = SketchSegment((10, 0), (0, 10), (0, 0), 1.5707963267948966)

        _create_sketch(
            sketch,
            ((10, 0), (0, 10), (0, 0)),
            (0, 0),
            closed=True,
            curve_segments=(
                arc,
                SketchSegment((0, 10), (0, 0)),
                SketchSegment((0, 0), (10, 0)),
            ),
        )

        self.assertEqual(len(sketch.arcs), 1)
        self.assertEqual(len(sketch.lines), 2)
        self.assertEqual(
            sketch.arcs[0],
            (0.0, 0.0, 0.0, 0.01, 0.0, 0.0, 0.0, 0.01, 0.0, 1),
        )
        self.assertEqual(sketch.write_modes, [True, True, True])
        self.assertFalse(sketch.AddToDB)

    def test_uses_clockwise_direction_for_reversed_arc(self) -> None:
        class SketchManager:
            def __init__(self) -> None:
                self.arcs: list[tuple[float, ...]] = []
                self.AddToDB = False

            def CreateArc(self, *coordinates: float) -> None:
                self.arcs.append(coordinates)

        sketch = SketchManager()

        _create_sketch(
            sketch,
            ((0, 10), (10, 0)),
            (0, 0),
            closed=False,
            curve_segments=(
                SketchSegment((0, 10), (10, 0), (0, 0), -1.5707963267948966),
            ),
        )

        self.assertEqual(sketch.arcs[0][-1], -1)
        self.assertFalse(sketch.AddToDB)
        self.assertEqual(_arc_direction(1.0, -1.0), -1)

    def test_restores_add_to_database_mode_when_sketch_creation_fails(self) -> None:
        class SketchManager:
            AddToDB = False

            def CreateLine(self, *_coordinates: float) -> None:
                raise RuntimeError("line creation failed")

        sketch = SketchManager()
        with self.assertRaisesRegex(RuntimeError, "line creation failed"):
            _create_sketch(
                sketch,
                ((0, 0), (10, 0)),
                (0, 0),
                closed=False,
                curve_segments=(SketchSegment((0, 0), (10, 0)),),
            )

        self.assertFalse(sketch.AddToDB)


if __name__ == "__main__":
    unittest.main()
