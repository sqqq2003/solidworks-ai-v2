"""一键全部导出：拆件与红线折弯绑定。"""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "src"))


import unittest
from pathlib import Path

from cad_analyzer import DrawingAnalysis, Primitive, SketchSegment
from batch_export import discover_sheet_parts


def _rect(x0, y0, x1, y1, layer="0") -> Primitive:
    pts = ((x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0))
    segs = tuple(SketchSegment(a, b) for a, b in zip(pts, pts[1:]))
    return Primitive(pts, True, False, layer, "LINE_LOOP", segs)


def _line(a, b, *, bend=False, layer="0") -> Primitive:
    return Primitive((a, b), False, bend, layer, "LINE", (SketchSegment(a, b),))


class DiscoverSheetPartsTests(unittest.TestCase):
    def test_two_outers_with_own_bends(self) -> None:
        outer_a = _rect(0, 0, 100, 80)
        hole_a = _rect(40, 30, 60, 50)
        outer_b = _rect(200, 0, 260, 40)
        bend_a = _line((10, 40), (90, 40), bend=True)
        bend_b = _line((210, 20), (250, 20), bend=True)
        stray = _line((-50, -50), (-40, -40), bend=True)
        analysis = DrawingAnalysis(
            Path("demo.dxf"),
            "mm",
            (outer_a, hole_a, outer_b, bend_a, bend_b, stray),
            (bend_a, bend_b, stray),
            (outer_a, hole_a, outer_b),
            (0, 0, 260, 80),
            "Model",
        )
        jobs = discover_sheet_parts(analysis)
        self.assertEqual(len(jobs), 2)
        self.assertEqual(jobs[0].profile_index, 0)  # 更高的一块在前
        self.assertEqual(jobs[0].bend_indices, (0,))
        self.assertEqual(jobs[1].profile_index, 2)
        self.assertEqual(jobs[1].bend_indices, (1,))


if __name__ == "__main__":
    unittest.main()
