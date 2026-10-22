# -*- coding: utf-8 -*-
"""图纸残留与零宽尖刺：两条都会让 SolidWorks 认不出单一闭合轮廓。"""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "src"))


import math
import unittest

from cad_analyzer import Primitive, SketchSegment
from profile_sanitize import sanitize_closed_profile
from solidworks_generator import _is_drawing_artifact_loop


def _spur_profile() -> Primitive:
    """100×100 矩形顶边带 0.083 mm 宽、2 mm 深的来回尖刺（真实图纸里的缝）。"""

    ring = [
        (0.0, 0.0),
        (100.0, 0.0),
        (100.0, 100.0),
        (60.083, 100.0),
        (60.0, 98.0),
        (60.083, 100.0),
        (0.0, 100.0),
    ]
    segments = tuple(
        SketchSegment(start, end)
        for start, end in zip(ring, ring[1:] + ring[:1])
    )
    return Primitive(tuple(ring), True, False, "0", "LINE_LOOP", segments)


class SpurSegmentTests(unittest.TestCase):
    def test_out_and_back_pair_is_removed(self) -> None:
        sanitized = sanitize_closed_profile(_spur_profile(), min_edge_mm=0.1)
        segments = sanitized.curve_segments
        # 尖刺那两段（60.083,100 → 60,98 与回程）被去掉。
        self.assertFalse(
            any(
                math.dist(segment.start, (60.0, 98.0)) < 1e-6
                or math.dist(segment.end, (60.0, 98.0)) < 1e-6
                for segment in segments
            )
        )
        self.assertEqual(len(segments), 5)

    def test_remaining_segments_stay_connected(self) -> None:
        sanitized = sanitize_closed_profile(_spur_profile(), min_edge_mm=0.1)
        segments = sanitized.curve_segments
        for index, segment in enumerate(segments):
            nxt = segments[(index + 1) % len(segments)]
            self.assertLess(
                math.dist(segment.end, nxt.start),
                1e-6,
                f"第 {index} 段与下一段之间留了缝",
            )
        # 外形面积不变（尖刺本身是零宽，不该被当成两个环）。
        self.assertAlmostEqual(
            abs(_area(sanitized.points)), 100.0 * 100.0, delta=1.0
        )


class ArtifactLoopTests(unittest.TestCase):
    def _triangle(self) -> Primitive:
        return Primitive(
            ((38.571, 5269.037), (38.071, 5269.037), (38.571, 5270.037)),
            True,
            False,
            "0",
            "LINE_LOOP",
        )

    def test_arrow_head_triangle_is_artifact(self) -> None:
        # 0.5×1 mm、面积 0.25 mm²：图纸尺寸箭头，不是孔。
        self.assertTrue(_is_drawing_artifact_loop(self._triangle()))

    def test_small_but_real_hole_is_kept(self) -> None:
        # Φ2 孔面积 3.14 mm²，必须照常切。
        points = tuple(
            (
                10 + math.cos(math.radians(step * 15)) * 1.0,
                10 + math.sin(math.radians(step * 15)) * 1.0,
            )
            for step in range(24)
        )
        hole = Primitive(points, True, False, "0", "CIRCLE")
        self.assertFalse(_is_drawing_artifact_loop(hole))

    def test_three_mm_square_is_kept(self) -> None:
        hole = Primitive(
            ((0.0, 0.0), (3.0, 0.0), (3.0, 3.0), (0.0, 3.0)),
            True,
            False,
            "0",
            "LINE_LOOP",
        )
        self.assertFalse(_is_drawing_artifact_loop(hole))


def _area(points) -> float:
    total = 0.0
    for index, point in enumerate(points):
        nxt = points[(index + 1) % len(points)]
        total += point[0] * nxt[1] - nxt[0] * point[1]
    return total / 2.0


if __name__ == "__main__":
    unittest.main()
