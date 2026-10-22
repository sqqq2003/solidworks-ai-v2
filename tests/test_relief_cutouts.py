from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "src"))


import unittest
from pathlib import Path

from cad_analyzer import DrawingAnalysis, Primitive
from solidworks_generator import suggest_relief_cutouts


class ReliefCutoutTests(unittest.TestCase):
    def _analysis(self) -> tuple[DrawingAnalysis, int]:
        # 矩形外轮廓 + 两条相交折弯（十字）。
        outer = Primitive(
            ((0.0, 0.0), (100.0, 0.0), (100.0, 60.0), (0.0, 60.0), (0.0, 0.0)),
            True,
            False,
            "0",
            "LINE_LOOP",
        )
        bend_v = Primitive(
            ((40.0, 5.0), (40.0, 55.0)),
            False,
            True,
            "折弯线",
            "LINE",
        )
        bend_h = Primitive(
            ((10.0, 30.0), (90.0, 30.0)),
            False,
            True,
            "折弯线",
            "LINE",
        )
        analysis = DrawingAnalysis(
            path=Path("relief.dxf"),
            units_name="mm",
            primitives=(outer, bend_v, bend_h),
            bend_lines=(bend_v, bend_h),
            profiles=(outer,),
            bounds=(0.0, 0.0, 100.0, 60.0),
            layout_name="Model",
        )
        return analysis, 0

    def test_step_zero_no_circle_preopen(self) -> None:
        analysis, outer_index = self._analysis()
        cutouts = suggest_relief_cutouts(
            analysis,
            analysis.profiles,
            outer_index,
            (0, 1),
            thickness_mm=2.0,
            relief_step=0,
        )
        self.assertEqual(cutouts, ())

    def test_radius_grows_with_step(self) -> None:
        analysis, outer_index = self._analysis()
        step1 = suggest_relief_cutouts(
            analysis, analysis.profiles, outer_index, (0, 1), 2.0, 1
        )
        step2 = suggest_relief_cutouts(
            analysis, analysis.profiles, outer_index, (0, 1), 2.0, 2
        )
        self.assertGreaterEqual(len(step1), 1)
        self.assertAlmostEqual(
            max(item.radius_mm for item in step2),
            max(item.radius_mm for item in step1) + 1.0,
            places=6,
        )


if __name__ == "__main__":
    unittest.main()
