
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "src"))
import math
import unittest

from cad_analyzer import Primitive
from profile_selection import (
    candidate_profile_indices,
    contained_hole_indices,
    is_sheet_frame_index,
    outermost_containing_profile_index,
)


def circle(radius: float, *, center: tuple[float, float] = (0, 0)) -> Primitive:
    points = tuple(
        (
            center[0] + radius * math.cos(math.tau * index / 48),
            center[1] + radius * math.sin(math.tau * index / 48),
        )
        for index in range(49)
    )
    return Primitive(points, True, False, "OUTLINE", "CIRCLE")


class CandidateProfileTests(unittest.TestCase):
    def test_hides_enclosed_circle_and_square_holes_by_default(self) -> None:
        outline = Primitive(
            ((0, 0), (100, 0), (100, 80), (0, 80), (0, 0)),
            True,
            False,
            "OUTLINE",
            "LINE_LOOP",
        )
        square_hole = Primitive(
            ((10, 10), (30, 10), (30, 30), (10, 30), (10, 10)),
            True,
            False,
            "HOLE",
            "LINE_LOOP",
        )

        self.assertEqual(
            candidate_profile_indices(
                (outline, circle(5, center=(50, 40)), square_hole)
            ),
            (0,),
        )

    def test_can_show_enclosed_profiles_when_explicitly_requested(self) -> None:
        self.assertEqual(
            candidate_profile_indices((circle(20), circle(5)), include_enclosed=True),
            (0, 1),
        )

    def test_keeps_a_standalone_circular_part_candidate(self) -> None:
        self.assertEqual(candidate_profile_indices((circle(20),)), (0,))

    def test_returns_all_enclosed_closed_shapes_as_cutouts(self) -> None:
        outline = Primitive(
            ((0, 0), (100, 0), (100, 80), (0, 80), (0, 0)),
            True,
            False,
            "OUTLINE",
            "LINE_LOOP",
        )
        hole = circle(5, center=(25, 30))
        square = Primitive(
            ((60, 30), (70, 30), (70, 40), (60, 40), (60, 30)),
            True,
            False,
            "HOLE",
            "LINE_LOOP",
        )
        detail = Primitive(
            ((20, 50), (30, 52), (25, 60), (20, 50)),
            True,
            False,
            "DETAIL",
            "LINE_LOOP",
        )
        large_irregular = Primitive(
            ((42, 8), (82, 12), (75, 24), (55, 27), (42, 8)),
            True,
            False,
            "LARGE_DETAIL",
            "LINE_LOOP",
        )
        nested = circle(2, center=(25, 55))

        self.assertEqual(
            contained_hole_indices(
                (outline, hole, square, detail, large_irregular, nested),
                0,
            ),
            (1, 2, 3, 4, 5),
        )

    def test_returns_enclosed_rotated_slots_as_cutouts(self) -> None:
        outline = Primitive(
            ((0, 0), (100, 0), (100, 80), (0, 80), (0, 0)),
            True,
            False,
            "OUTLINE",
            "LINE_LOOP",
        )
        angle = math.radians(37)
        axis = (math.cos(angle), math.sin(angle))
        normal = (-axis[1], axis[0])

        def oriented_rectangle(
            center: tuple[float, float],
            length: float,
            width: float,
        ) -> Primitive:
            points = tuple(
                (
                    center[0] + axis[0] * along + normal[0] * across,
                    center[1] + axis[1] * along + normal[1] * across,
                )
                for along, across in (
                    (-length / 2, -width / 2),
                    (length / 2, -width / 2),
                    (length / 2, width / 2),
                    (-length / 2, width / 2),
                )
            )
            return Primitive(
                points + (points[0],),
                True,
                False,
                "SLOT",
                "LINE_LOOP",
            )

        slot = oriented_rectangle((50, 40), 30, 4)
        detail = Primitive(
            ((20, 20), (30, 20), (25, 28), (20, 20)),
            True,
            False,
            "DETAIL",
            "LINE_LOOP",
        )

        self.assertEqual(
            contained_hole_indices((outline, slot, detail), 0),
            (1, 2),
        )


class SheetFrameTests(unittest.TestCase):
    @staticmethod
    def _rect(x0: float, y0: float, x1: float, y1: float) -> Primitive:
        points = ((x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0))
        return Primitive(points, True, False, "0", "LINE_LOOP")

    def test_parts_inside_a_drawing_frame_stay_selectable(self) -> None:
        frame = self._rect(0, 0, 400, 300)
        part_a = self._rect(20, 20, 100, 70)
        part_b = self._rect(150, 30, 280, 110)
        hole = circle(4, center=(50, 40))
        profiles = (frame, part_a, part_b, hole)

        self.assertEqual(candidate_profile_indices(profiles), (1, 2))
        self.assertTrue(is_sheet_frame_index(profiles, 0))
        self.assertEqual(outermost_containing_profile_index(profiles, 1), 1)
        self.assertEqual(outermost_containing_profile_index(profiles, 3), 1)
        self.assertEqual(contained_hole_indices(profiles, 1), (3,))

    def test_holes_in_one_part_do_not_turn_it_into_a_frame(self) -> None:
        outline = self._rect(0, 0, 100, 80)
        profiles = (
            outline,
            circle(5, center=(30, 40)),
            self._rect(60, 20, 75, 35),
        )
        self.assertEqual(candidate_profile_indices(profiles), (0,))
        self.assertFalse(is_sheet_frame_index(profiles, 0))
        self.assertEqual(outermost_containing_profile_index(profiles, 2), 0)


class DegenerateProfileTests(unittest.TestCase):
    """真实钣金图里混着退化轮廓，不能让整张列表构建失败。"""

    def test_degenerate_profile_has_no_holes_instead_of_raising(self) -> None:
        outline = Primitive(
            ((0, 0), (100, 0), (100, 80), (0, 80), (0, 0)),
            True,
            False,
            "OUTLINE",
            "LINE_LOOP",
        )
        # 零面积：所有点重合，包围盒宽高为 0，会被包围盒计算滤掉。
        degenerate = Primitive(
            ((5, 5), (5, 5), (5, 5), (5, 5)),
            True,
            False,
            "0",
            "LINE_LOOP",
        )
        profiles = (outline, degenerate)

        # 以前这里抛 StopIteration，导致右侧列表一行都不显示。
        self.assertEqual(contained_hole_indices(profiles, 1), ())
        self.assertEqual(contained_hole_indices(profiles, 0), ())

    def test_out_of_range_index_still_raises_index_error(self) -> None:
        outline = Primitive(
            ((0, 0), (100, 0), (100, 80), (0, 80), (0, 0)),
            True,
            False,
            "OUTLINE",
            "LINE_LOOP",
        )
        with self.assertRaises(IndexError):
            contained_hole_indices((outline,), 5)


if __name__ == "__main__":
    unittest.main()
