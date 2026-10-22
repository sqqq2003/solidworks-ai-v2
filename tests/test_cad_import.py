"""cad_import：只抽所选件图元、原样拷贝、扩槽移动端点、完整性校验。"""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "src"))


import tempfile
import unittest
from pathlib import Path

import ezdxf

from cad_import import build_part_dxf

# 外轮廓 100×80，左下角 L 形释放槽（与 QL-5050 #247 同型）
OUTER = [
    (10.0, 0.0), (100.0, 0.0), (100.0, 80.0), (0.0, 80.0), (0.0, 18.5),
    (9.0, 18.5), (9.0, 21.5), (11.0, 21.5), (11.0, 20.0), (10.0, 20.0),
]
HOLE_CENTER = (50.0, 40.0)
HOLE_R = 5.0


def _ring_circle(cx: float, cy: float, r: float, n: int = 72) -> list:
    import math

    return [
        (cx + r * math.cos(2 * math.pi * i / n), cy + r * math.sin(2 * math.pi * i / n))
        for i in range(n)
    ]


def _write_source(path: Path) -> None:
    doc = ezdxf.new("R2010")
    doc.units = 4
    msp = doc.modelspace()
    # 外轮廓：一条边拆成两段（模拟原图分段），其余单段
    for i in range(len(OUTER)):
        a = OUTER[i]
        b = OUTER[(i + 1) % len(OUTER)]
        if a == (10.0, 0.0):
            msp.add_line(a, (60.0, 0.0))
            msp.add_line((60.0, 0.0), b)
        else:
            msp.add_line(a, b)
    msp.add_circle(HOLE_CENTER, HOLE_R)
    # 折弯线（内部，不应导入）、文字、另一块件
    msp.add_line((0.0, 30.0), (100.0, 30.0), dxfattribs={"layer": "BEND"})
    msp.add_text("T=2", dxfattribs={"insert": (20, 60)})
    msp.add_lwpolyline([(200, 0), (260, 0), (260, 40), (200, 40)], close=True)
    doc.saveas(path)


class BuildPartDxfTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.src = self.tmp / "src.dxf"
        _write_source(self.src)
        self.rings = [OUTER, _ring_circle(*HOLE_CENTER, HOLE_R)]

    def _read(self, path: Path):
        doc = ezdxf.readfile(path)
        return list(doc.modelspace())

    def test_only_part_entities_copied_verbatim(self) -> None:
        out = self.tmp / "part.dxf"
        info = build_part_dxf(self.src, self.rings, (50.0, 40.0), out,
                              coverage_rings=self.rings)
        ents = self._read(out)
        kinds = sorted(e.dxftype() for e in ents)
        self.assertEqual(kinds.count("CIRCLE"), 1)
        self.assertEqual(kinds.count("LINE"), len(OUTER) + 1)  # 分段保留
        self.assertNotIn("TEXT", kinds)
        self.assertEqual(info.moved_endpoints, 0)
        # 平移到件中心，坐标原样（无 snap）
        pts = {(round(e.dxf.start.x, 6), round(e.dxf.start.y, 6))
               for e in ents if e.dxftype() == "LINE"}
        self.assertIn((-41.0, -18.5), pts)  # (9,21.5)-(50,40)
        circle = next(e for e in ents if e.dxftype() == "CIRCLE")
        self.assertAlmostEqual(circle.dxf.center.x, 0.0)
        self.assertAlmostEqual(circle.dxf.radius, HOLE_R)
        # 无斜线
        for e in ents:
            if e.dxftype() == "LINE":
                dx = abs(e.dxf.end.x - e.dxf.start.x)
                dy = abs(e.dxf.end.y - e.dxf.start.y)
                self.assertTrue(dx < 1e-9 or dy < 1e-9)

    def test_relief_move_pairs_shift_endpoints(self) -> None:
        after = list(OUTER)
        # 只朝板面单边 +1：内角 (11,21.5)->(12,22.5)，(9,21.5)->(9,22.5)，(11,20)->(12,20)
        after[6] = (9.0, 22.5)
        after[7] = (12.0, 22.5)
        after[8] = (12.0, 20.0)
        out = self.tmp / "part_r.dxf"
        info = build_part_dxf(self.src, self.rings, (0.0, 0.0), out,
                              move_pairs=[(OUTER, after)],
                              coverage_rings=[after, self.rings[1]])
        self.assertGreater(info.moved_endpoints, 0)
        pts = set()
        for e in self._read(out):
            if e.dxftype() == "LINE":
                pts.add((round(e.dxf.start.x, 6), round(e.dxf.start.y, 6)))
                pts.add((round(e.dxf.end.x, 6), round(e.dxf.end.y, 6)))
        self.assertIn((12.0, 22.5), pts)
        self.assertIn((9.0, 22.5), pts)
        self.assertIn((12.0, 20.0), pts)
        self.assertNotIn((11.0, 21.5), pts)
        self.assertIn((10.0, 20.0), pts)

    def test_missing_geometry_raises(self) -> None:
        out = self.tmp / "bad.dxf"
        bogus = [(0.0, 0.0), (500.0, 0.0), (500.0, 500.0)]
        with self.assertRaises(ValueError):
            build_part_dxf(self.src, self.rings, (0.0, 0.0), out,
                           coverage_rings=[bogus])


if __name__ == "__main__":
    unittest.main()


class TopologyCleanupTests(unittest.TestCase):
    def test_red_edge_kept_gap_closed_overlap_removed(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        src = tmp / "src.dxf"
        doc = ezdxf.new("R2010")
        doc.units = 4
        msp = doc.modelspace()
        msp.add_line((0, 0), (100, 0))
        msp.add_line((100, 0), (100, 50))
        msp.add_line((100, 50), (0.05, 50))  # 0.05 mm 微缝
        # 左边是纯红实线（会被识别为「折弯线」，但它就是轮廓边）
        msp.add_line((0, 50), (0, 0), dxfattribs={"color": 1})
        msp.add_line((20, 0), (40, 0))  # 与底边共线重叠
        doc.saveas(src)
        ring = [(0, 0), (100, 0), (100, 50), (0, 50)]
        info = build_part_dxf(src, [ring], (0, 0), tmp / "out.dxf", coverage_rings=[ring])
        self.assertEqual(info.lines, 4)
        self.assertEqual(info.removed_overlaps, 1)
        self.assertEqual(info.closed_gaps, 1)
        self.assertEqual(info.peeled_dangling, 0)


class CircleDedupTests(unittest.TestCase):
    def test_stacked_same_center_radius_removed(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        src = tmp / "src.dxf"
        doc = ezdxf.new("R2010")
        doc.units = 4
        msp = doc.modelspace()
        # 外框
        msp.add_lwpolyline([(0, 0), (100, 0), (100, 60), (0, 60)], close=True)
        # 同一孔画了两遍圆 + 一段同径圆弧
        msp.add_circle((40, 30), 5.0)
        msp.add_circle((40.02, 30.01), 5.01)  # 容差内叠圆
        msp.add_arc((40, 30), 5.0, 0, 90)
        doc.saveas(src)
        ring = [(0, 0), (100, 0), (100, 60), (0, 60)]
        hole = _ring_circle(40, 30, 5.0)
        info = build_part_dxf(
            src, [ring, hole], (0, 0), tmp / "out.dxf", coverage_rings=[ring, hole]
        )
        self.assertEqual(info.circles, 1)
        self.assertGreaterEqual(info.removed_dup_circles, 1)
        # 同径四分弧叠在整圆上应被去掉
        out = ezdxf.readfile(tmp / "out.dxf")
        arcs = [e for e in out.modelspace() if e.dxftype() == "ARC"]
        circs = [e for e in out.modelspace() if e.dxftype() == "CIRCLE"]
        self.assertEqual(len(circs), 1)
        self.assertEqual(len(arcs), 0)
