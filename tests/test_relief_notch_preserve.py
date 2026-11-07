"""四角小矩形释放槽不得被轮廓拼环对角捷径掉。"""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "src"))


import unittest

from cad_analyzer import Primitive, SketchSegment, _line_contours
from profile_sanitize import sanitize_closed_profile


def _line(start: tuple[float, float], end: tuple[float, float]) -> Primitive:
    return Primitive(
        (start, end),
        False,
        False,
        "0",
        "LINE",
        (SketchSegment(start, end),),
    )


def _rect_with_corner_notches(
    width: float,
    height: float,
    notch: float,
) -> list[Primitive]:
    """轴对齐矩形，四角各开 notch×notch 向内台阶释放槽。"""

    r = float(notch)
    w = float(width)
    h = float(height)
    edges = [
        ((r, 0.0), (w - r, 0.0)),
        ((w - r, 0.0), (w - r, r)),
        ((w - r, r), (w, r)),
        ((w, r), (w, h - r)),
        ((w, h - r), (w - r, h - r)),
        ((w - r, h - r), (w - r, h)),
        ((w - r, h), (r, h)),
        ((r, h), (r, h - r)),
        ((r, h - r), (0.0, h - r)),
        ((0.0, h - r), (0.0, r)),
        ((0.0, r), (r, r)),
        ((r, r), (r, 0.0)),
    ]
    return [_line(a, b) for a, b in edges]


def _diagonal_segments(points: tuple[tuple[float, float], ...]) -> list:
    found = []
    for start, end in zip(points, points[1:]):
        if abs(end[0] - start[0]) > 0.2 and abs(end[1] - start[1]) > 0.2:
            found.append((start, end))
    return found


class CornerReliefNotchPreserveTests(unittest.TestCase):
    def _assert_notches_kept(self, width: float, height: float, notch: float) -> None:
        contours = _line_contours(_rect_with_corner_notches(width, height, notch))
        self.assertGreaterEqual(len(contours), 1)
        outer = max(
            contours,
            key=lambda item: (
                max(p[0] for p in item.points) - min(p[0] for p in item.points)
            )
            * (max(p[1] for p in item.points) - min(p[1] for p in item.points)),
        )
        pts = {(round(p[0], 6), round(p[1], 6)) for p in outer.points}
        expected = {
            (notch, notch),
            (width - notch, notch),
            (width - notch, height - notch),
            (notch, height - notch),
        }
        self.assertTrue(
            expected <= pts,
            f"missing inner notch corners {expected - pts} (snap ate relief)",
        )
        self.assertEqual(
            _diagonal_segments(outer.points),
            [],
            "轮廓在释放槽处出现对角捷径",
        )
        sanitized = sanitize_closed_profile(outer, min_edge_mm=0.5)
        pts2 = {(round(p[0], 6), round(p[1], 6)) for p in sanitized.points}
        self.assertTrue(expected <= pts2)
        self.assertEqual(_diagonal_segments(sanitized.points), [])

    def test_small_notch_on_large_part_not_diagonally_cut(self) -> None:
        # 旧 snap 上限 2mm 时，1–2mm 槽会被吸塌。
        self._assert_notches_kept(800.0, 600.0, 1.0)
        self._assert_notches_kept(800.0, 600.0, 2.0)
        self._assert_notches_kept(1000.0, 800.0, 1.5)

    def test_four_corner_notches_medium_part(self) -> None:
        self._assert_notches_kept(500.0, 400.0, 1.5)
        self._assert_notches_kept(100.0, 80.0, 5.0)


if __name__ == "__main__":
    unittest.main()
