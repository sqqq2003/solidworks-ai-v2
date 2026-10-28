"""一键全部导出：拆件与红线折弯绑定。"""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "src"))


import unittest
from tempfile import TemporaryDirectory
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
    def test_batch_refuses_unresolved_red_bend_before_writes(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from batch_export import export_all_sheet_parts
        analysis=SimpleNamespace(texts=('红色线为折弯线，折弯90度',),bend_lines=())
        with patch('batch_export.ensure_dirs') as mkdir:
            with self.assertRaisesRegex(ValueError,'没有识别到折弯线'):
                export_all_sheet_parts(analysis,thickness_mm=4,radius_mm=1)
            mkdir.assert_not_called()

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

    def test_text_frame_jobs_are_marked_and_excluded_from_export(self) -> None:
        # 内含图纸文字的轮廓是文字框，不进入批量生成清单。
        from types import SimpleNamespace
        from unittest.mock import patch
        from cad_analyzer import DrawingText
        outer_a = _rect(0, 0, 100, 80)
        frame = _rect(0, 200, 150, 240)
        # 用不触发「折弯线矛盾」拦截的文字（焊接打码说明）。
        analysis = SimpleNamespace(
            path=Path("demo.dxf"),
            name="demo",
            texts=("焊接打码说明",),
            text_entities=(DrawingText("焊接打码说明", 50, 220, 4.0),),
            bend_lines=(),
            profiles=(outer_a, frame),
            primitives=(outer_a, frame),
        )
        jobs = discover_sheet_parts(analysis)
        marked = [job for job in jobs if job.text_frame]
        self.assertEqual(len(marked), 1)
        self.assertEqual(marked[0].profile_index, 1)

        # 批量导出应默认排除文字框：只导出 1 件真实零件。
        with patch("batch_export.discover_sheet_parts", return_value=jobs), TemporaryDirectory() as folder:
            source = Path(folder) / 'synthetic.dxf'
            source.write_bytes(b'synthetic metadata fixture; parser is not invoked')
            analysis.path = source
            with patch("batch_export._export_jobs") as export_jobs:
                from batch_export import export_all_sheet_parts
                export_all_sheet_parts(
                    analysis, thickness_mm=4, radius_mm=1, output_dir=Path(folder) / 'out'
                )
                # _export_jobs 收到的编号清单只含非文字框的件。
                exported = export_jobs.call_args[0][1]
                self.assertEqual(len(exported), 1)


    def test_stamping_note_target_has_no_bends(self) -> None:
        # 「打码焊接线，不用折弯」文字写在一个说明框里，紧邻它标注的零件。
        # 该零件的红线应判为打码线（折弯清零），其余零件的折弯线保留。
        from cad_analyzer import DrawingText
        outer_a = _rect(0, 0, 100, 80)          # 有折弯的普通零件
        bend_a = _line((10, 40), (90, 40), bend=True)
        part_c = _rect(0, 200, 130, 240)        # 打码目标零件（130×40）
        bend_c = _line((20, 210), (20, 230), bend=True)   # 打码竖线
        frame = _rect(200, 200, 350, 240)       # 说明框，紧邻 part_c 右侧
        analysis = DrawingAnalysis(
            Path("demo.dxf"),
            "mm",
            (outer_a, bend_a, part_c, bend_c, frame),
            (bend_a, bend_c),
            (outer_a, part_c, frame),
            (0, 0, 350, 240),
            "Model",
            text_entities=(DrawingText("打码焊接线，不用折弯", 250, 220, 4.0),),
        )
        jobs = discover_sheet_parts(analysis)
        by_index = {job.profile_index: job for job in jobs}
        # part_c（profile#2）折弯应清零。
        self.assertEqual(by_index[2].bend_indices, ())
        # outer_a（profile#0）折弯保留。
        self.assertEqual(by_index[0].bend_indices, (0,))

    def test_no_stamping_note_leaves_bends_untouched(self) -> None:
        # 没有打码文字时，折弯线正常保留。
        outer = _rect(0, 0, 100, 80)
        bend = _line((10, 40), (90, 40), bend=True)
        analysis = DrawingAnalysis(
            Path("demo.dxf"),
            "mm",
            (outer, bend),
            (bend,),
            (outer,),
            (0, 0, 100, 80),
            "Model",
        )
        jobs = discover_sheet_parts(analysis)
        self.assertEqual(jobs[0].bend_indices, (0,))


if __name__ == "__main__":
    unittest.main()
