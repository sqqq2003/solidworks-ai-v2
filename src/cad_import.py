# -*- coding: utf-8 -*-
"""把用户 CAD 原图里「选中那块件」的图元原样抽到临时 DXF，供 SolidWorks 直接导入草图。

- 不重画、不 snap、不斜切：直线/圆弧/圆按原始几何拷贝（仅平移到件中心、换算 mm）。
- 只保留落在该件外轮廓/内孔轮廓上的图元；折弯线、文字、标注、其它件都不导。
- 释放槽扩大：按「扩槽前/后」顶点环对 LINE 端点做位移（同一条边上的中间点按参数插值）。
"""

from __future__ import annotations

import hashlib
import logging
import math
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

import ezdxf
from ezdxf import units

Point = tuple[float, float]
Ring = Sequence[Point]

logger = logging.getLogger(__name__)

GEOMETRY_TYPES = ("LINE", "ARC", "CIRCLE", "LWPOLYLINE", "POLYLINE", "ELLIPSE", "SPLINE")
ON_RING_TOL_MM = 0.05
ARC_CHORD_SWEEP_RAD = math.pi / 24  # 与 cad_analyzer._arc_points 的 max_sweep 一致
VERTEX_MATCH_TOL_MM = 0.02


@dataclass
class PartDxfInfo:
    path: Path
    lines: int = 0
    arcs: int = 0
    circles: int = 0
    approximated: int = 0
    skipped_duplicates: int = 0
    moved_endpoints: int = 0
    removed_overlaps: int = 0
    closed_gaps: int = 0
    peeled_dangling: int = 0
    removed_dup_circles: int = 0
    kept_layers: set[str] = field(default_factory=set)

    @property
    def entity_count(self) -> int:
        return self.lines + self.arcs + self.circles


def _cache_dir() -> Path:
    try:
        from paths_local import TEMP
        path = TEMP / "dxf_cache"
    except Exception:  # noqa: BLE001
        base = Path(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir())
        path = base / "cad2sw" / "dxf_cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def source_dxf_for(path: str | Path) -> Path:
    """DXF 原样返回；DWG 转成 DXF 并按 (路径, mtime, size) 缓存。"""

    source = Path(path)
    if source.suffix.lower() == ".dxf":
        return source
    if source.suffix.lower() != ".dwg":
        raise ValueError(f"不支持的 CAD 文件：{source}")
    stat = source.stat()
    key = hashlib.sha1(
        f"{source.resolve()}|{stat.st_mtime_ns}|{stat.st_size}".encode("utf-8")
    ).hexdigest()[:16]
    from dwg_converter import DwgConversionError, iter_dwg_converters

    errors: list[str] = []
    for name, converter in iter_dwg_converters(source):
        target = _cache_dir() / f"{key}_{name}.dxf"
        if target.is_file() and target.stat().st_size > 0:
            return target
        try:
            converter(source, target)
            if target.is_file() and target.stat().st_size > 0:
                return target
        except (DwgConversionError, OSError, ValueError) as error:
            errors.append(f"{name}: {error}")
    raise ValueError("DWG 转 DXF 失败：" + "；".join(errors))


def _select_layout(doc: ezdxf.document.Drawing):
    from cad_analyzer import _is_bend_line

    def score(layout) -> tuple[int, int, int, int]:
        bend = sum(_is_bend_line(doc, e) for e in layout)
        geometry = sum(
            e.dxftype() in ("LINE", "LWPOLYLINE", "POLYLINE", "CIRCLE", "ARC")
            for e in layout
        )
        annotation = sum(
            e.dxftype() in ("DIMENSION", "TEXT", "MTEXT", "INSERT") for e in layout
        )
        sw_model = (geometry > 0 or annotation > 0) and layout.name.casefold().startswith(
            "sw_model_"
        )
        return (int(sw_model), annotation, bend, geometry)

    return max(doc.layouts, key=score)


def _seg_dist(p: Point, a: Point, b: Point) -> tuple[float, float]:
    """点到线段距离与参数 t∈[0,1]。"""

    ax, ay = a
    dx, dy = b[0] - ax, b[1] - ay
    length2 = dx * dx + dy * dy
    if length2 <= 1e-18:
        return math.dist(p, a), 0.0
    t = ((p[0] - ax) * dx + (p[1] - ay) * dy) / length2
    t = min(1.0, max(0.0, t))
    return math.dist(p, (ax + t * dx, ay + t * dy)), t


class _RingIndex:
    """一组闭合环的线段，带 bbox 预筛。"""

    def __init__(self, rings: Iterable[Ring], *, closed: bool = True) -> None:
        self.segments: list[tuple[Point, Point]] = []
        for ring in rings:
            pts = list(ring)
            if not closed:
                if len(pts) == 1:
                    self.segments.append((pts[0], pts[0]))
                self.segments.extend(zip(pts, pts[1:]))
                continue
            if len(pts) >= 2 and math.dist(pts[0], pts[-1]) <= 1e-9:
                pts = pts[:-1]
            for i in range(len(pts)):
                self.segments.append((pts[i], pts[(i + 1) % len(pts)]))
        xs = [c for s in self.segments for c in (s[0][0], s[1][0])]
        ys = [c for s in self.segments for c in (s[0][1], s[1][1])]
        self.bbox = (min(xs), min(ys), max(xs), max(ys)) if xs else (0, 0, 0, 0)

    def near(self, p: Point, tol: float) -> bool:
        x0, y0, x1, y1 = self.bbox
        if p[0] < x0 - tol or p[0] > x1 + tol or p[1] < y0 - tol or p[1] > y1 + tol:
            return False
        for a, b in self.segments:
            if min(a[0], b[0]) - tol > p[0] or max(a[0], b[0]) + tol < p[0]:
                continue
            if min(a[1], b[1]) - tol > p[1] or max(a[1], b[1]) + tol < p[1]:
                continue
            if _seg_dist(p, a, b)[0] <= tol:
                return True
        return False


class _VertexMover:
    """扩槽前/后环：顶点按位移移动，边内点按参数插值。"""

    def __init__(self, pairs: Iterable[tuple[Ring, Ring]]) -> None:
        self.edges: list[tuple[Point, Point, Point, Point]] = []
        for before, after in pairs:
            b = list(before)
            a = list(after)
            if len(b) != len(a) or len(b) < 3:
                logger.warning("扩槽前后顶点数不一致（%d/%d），跳过该环", len(b), len(a))
                continue
            n = len(b)
            if not any(math.dist(b[i], a[i]) > 1e-9 for i in range(n)):
                continue
            for i in range(n):
                j = (i + 1) % n
                self.edges.append((b[i], b[j], a[i], a[j]))

    def __bool__(self) -> bool:
        return bool(self.edges)

    def move(self, p: Point) -> Point:
        best: tuple[float, Point] | None = None
        for b0, b1, a0, a1 in self.edges:
            if math.dist(p, b0) <= VERTEX_MATCH_TOL_MM:
                return a0
            if math.dist(p, b1) <= VERTEX_MATCH_TOL_MM:
                return a1
            d, t = _seg_dist(p, b0, b1)
            if d <= VERTEX_MATCH_TOL_MM and (best is None or d < best[0]):
                best = (d, (a0[0] + t * (a1[0] - a0[0]), a0[1] + t * (a1[1] - a0[1])))
        return best[1] if best is not None else p


def _flatten_points(entity) -> list[Point]:
    from ezdxf import path as ezpath

    try:
        p = ezpath.make_path(entity)
        return [(v.x, v.y) for v in p.flattening(0.01, segments=8)]
    except Exception:  # noqa: BLE001
        return []


GAP_CLOSE_MM = 0.6  # 原图释放槽处常见 0.5 mm 缝；只挪直线端点，不改弧
_NODE_TOL = 1e-3
CIRCLE_DEDUP_TOL_MM = 0.05  # 共圆心共半径（容差内）只留一个圆
LINE_ON_RING_TOL_MM = 0.55  # 直线落环容差（槽口相对分析折线有 0.2~0.5 mm 偏移）


def _arc_ends(r: dict) -> tuple[Point, Point]:
    cx, cy = r["c"]
    a0, a1 = math.radians(r["a0"]), math.radians(r["a1"])
    return (
        (cx + r["r"] * math.cos(a0), cy + r["r"] * math.sin(a0)),
        (cx + r["r"] * math.cos(a1), cy + r["r"] * math.sin(a1)),
    )


def _record_ends(r: dict) -> tuple[Point, Point] | None:
    if r["kind"] == "L":
        return r["a"], r["b"]
    if r["kind"] == "A":
        return _arc_ends(r)
    return None


def _record_points(r: dict) -> list[Point]:
    if r["kind"] == "L":
        a, b = r["a"], r["b"]
        return [a, ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2), b]
    return list(r.get("pts") or [])


def _covered_by(inner: dict, outer: dict, tol: float = 1e-3) -> bool:
    """inner 直线是否被 outer 直线完全覆盖（共线重叠线）。"""
    a, b = outer["a"], outer["b"]
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy)
    if length <= 1e-9:
        return False
    for p in (inner["a"], inner["b"]):
        t = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (length * length)
        if t < -tol / length or t > 1 + tol / length:
            return False
        if abs((p[0] - a[0]) * dy - (p[1] - a[1]) * dx) / length > tol:
            return False
    return True


def _circle_key(r: dict, tol: float = CIRCLE_DEDUP_TOL_MM) -> tuple[int, int, int]:
    """把圆心/半径量化到容差网格，用于共圆心共半径去重。"""
    cx, cy = r["c"]
    return (
        round(cx / tol),
        round(cy / tol),
        round(r["r"] / tol),
    )


def _arc_is_full_circle(r: dict) -> bool:
    """起止角几乎闭合（整圆）的 ARC，按圆处理。"""
    if r["kind"] != "A":
        return False
    span = abs((r["a1"] - r["a0"]) % 360.0)
    return span < 1e-3 or abs(span - 360.0) < 1e-3


def _dedupe_circles(records: list[dict], info: PartDxfInfo) -> list[dict]:
    """共圆心共半径只留一条：优先保留 CIRCLE，其次整圆 ARC，再丢掉叠在其上的同径 ARC。"""
    # 第一轮：CIRCLE / 整圆 ARC 互相去重
    keep_idx: dict[tuple[int, int, int], int] = {}
    drop: set[int] = set()
    for i, r in enumerate(records):
        if r["kind"] == "C" or _arc_is_full_circle(r):
            key = _circle_key(r if r["kind"] == "C" else {**r, "c": r["c"], "r": r["r"]})
            if key in keep_idx:
                # 已有一条：若新来的是 CIRCLE 而旧的是 ARC，替换
                prev = keep_idx[key]
                if records[prev]["kind"] != "C" and r["kind"] == "C":
                    drop.add(prev)
                    keep_idx[key] = i
                else:
                    drop.add(i)
            else:
                keep_idx[key] = i
    # 第二轮：普通 ARC 若与已保留圆同圆心同半径 → 丢掉（叠圆）
    for i, r in enumerate(records):
        if i in drop or r["kind"] != "A" or _arc_is_full_circle(r):
            continue
        key = _circle_key(r)
        if key in keep_idx and keep_idx[key] != i:
            drop.add(i)
    info.removed_dup_circles += len(drop)
    return [r for i, r in enumerate(records) if i not in drop]


def _clean_topology(
    records: list[dict],
    info: PartDxfInfo,
    *,
    coverage_rings: Sequence[Ring] = (),
) -> list[dict]:
    """按环拓扑清理：圆去重 → 去共线重叠线 → 补端点微缝 → 剔悬挂图元。

    只删除/微调多余或未闭合处的端点，不改动轮廓上任何一条原始边的形状。
    悬挂剔除不会拆掉仍覆盖 coverage_rings 的边（避免 0.5 mm 缝把整圈外环剥光）。
    """

    records = _dedupe_circles(records, info)
    lines = [i for i, r in enumerate(records) if r["kind"] == "L"]
    drop: set[int] = set()
    for i in lines:
        if i in drop:
            continue
        for j in lines:
            if i == j or j in drop:
                continue
            if _covered_by(records[i], records[j]):
                li = math.dist(records[i]["a"], records[i]["b"])
                lj = math.dist(records[j]["a"], records[j]["b"])
                if li < lj or (li == lj and i > j):
                    drop.add(i)
                    break
    info.removed_overlaps += len(drop)
    records = [r for k, r in enumerate(records) if k not in drop]

    def degree_map() -> tuple[list[Point], list[int], list[list[tuple[int, int]]]]:
        nodes: list[Point] = []
        deg: list[int] = []
        refs: list[list[tuple[int, int]]] = []
        for ri, r in enumerate(records):
            ends = _record_ends(r)
            if ends is None:
                continue
            for e, p in enumerate(ends):
                for ni, q in enumerate(nodes):
                    if abs(p[0] - q[0]) <= _NODE_TOL and abs(p[1] - q[1]) <= _NODE_TOL:
                        deg[ni] += 1
                        refs[ni].append((ri, e))
                        break
                else:
                    nodes.append(p)
                    deg.append(1)
                    refs.append([(ri, e)])
        return nodes, deg, refs

    # 补缝：度为 1 的端点两两配对（互为最近、距离 ≤ GAP_CLOSE_MM），移动直线端点。
    nodes, deg, refs = degree_map()
    loose = [i for i, d in enumerate(deg) if d == 1]
    used: set[int] = set()
    for i in loose:
        if i in used:
            continue
        best, best_d = None, GAP_CLOSE_MM
        for j in loose:
            if j == i or j in used or refs[j][0][0] == refs[i][0][0]:
                continue
            d = math.dist(nodes[i], nodes[j])
            if d <= best_d:
                best, best_d = j, d
        if best is None:
            continue
        (ri, ei), (rj, ej) = refs[i][0], refs[best][0]
        if records[ri]["kind"] == "L":
            mover, me, target = ri, ei, nodes[best]
        elif records[rj]["kind"] == "L":
            mover, me, target = rj, ej, nodes[i]
        else:
            continue  # 两段都是圆弧：不改弧，保留原样
        records[mover]["ab"[me]] = target
        used.update((i, best))
        info.closed_gaps += 1

    # 剔悬挂：只删「不覆盖目标环」的度-1 图元（标注引线等）。
    # 落在 coverage 上的边即使暂时 deg=1（微缝未补上）也保留，避免整圈被剥光。
    cov = _RingIndex(coverage_rings) if coverage_rings else None
    while True:
        nodes, deg, refs = degree_map()
        bad: set[int] = set()
        for ni, d in enumerate(deg):
            if d != 1:
                continue
            for ri, _ in refs[ni]:
                if cov is not None:
                    pts = _record_points(records[ri])
                    if any(cov.near(p, max(LINE_ON_RING_TOL_MM, 0.15)) for p in pts):
                        continue
                bad.add(ri)
        if not bad:
            break
        info.peeled_dangling += len(bad)
        records = [r for k, r in enumerate(records) if k not in bad]
    return records


def build_part_dxf(
    source_dxf: str | Path,
    outline_rings: Sequence[Ring],
    origin_mm: Point,
    target: str | Path,
    *,
    move_pairs: Sequence[tuple[Ring, Ring]] = (),
    coverage_rings: Sequence[Ring] = (),
    tol_mm: float = ON_RING_TOL_MM,
) -> PartDxfInfo:
    """抽取落在 outline_rings（外轮廓 + 内孔，mm 坐标）上的图元写成临时 DXF。

    输出 DXF 以 mm 为单位，坐标平移 -origin_mm，使件中心落在原点（与旧草图坐标一致）。
    """

    doc = ezdxf.readfile(str(source_dxf))
    layout = _select_layout(doc)
    scale = (
        units.conversion_factor(doc.units, units.MM) if doc.units else 1.0
    )
    index = _RingIndex(outline_rings)
    mover = _VertexMover(move_pairs)

    out = ezdxf.new("R2010", setup=False)
    out.units = units.MM
    out.header["$INSUNITS"] = 4
    out.header["$MEASUREMENT"] = 1
    msp = out.modelspace()
    info = PartDxfInfo(Path(target))
    ox, oy = origin_mm
    seen: set[tuple] = set()
    records: list[dict] = []  # 输出几何（mm，未平移）；先收集，拓扑清理后再写

    def keep(points_mm: list[Point], tol: float | None = None) -> bool:
        t = tol_mm if tol is None else tol
        return bool(points_mm) and all(index.near(p, t) for p in points_mm)

    def key_of(kind: str, *vals: float) -> tuple:
        return (kind,) + tuple(round(v, 4) for v in vals)

    def emit_line(a: Point, b: Point) -> None:
        if mover:
            a2, b2 = mover.move(a), mover.move(b)
            if a2 != a or b2 != b:
                info.moved_endpoints += int(a2 != a) + int(b2 != b)
            a, b = a2, b2
        if math.dist(a, b) <= 1e-9:
            return
        k = key_of("L", *sorted([a, b])[0], *sorted([a, b])[1])
        if k in seen:
            info.skipped_duplicates += 1
            return
        seen.add(k)
        records.append({"kind": "L", "a": a, "b": b})

    def handle(entity, layer: str) -> None:
        kind = entity.dxftype()
        if kind in ("LWPOLYLINE", "POLYLINE"):
            try:
                parts = list(entity.virtual_entities())
            except Exception:  # noqa: BLE001
                parts = []
            for part in parts:
                handle(part, layer)
            return
        pts = [(x * scale, y * scale) for x, y in _flatten_points(entity)]
        if kind == "LINE":
            s = entity.dxf.start
            e = entity.dxf.end
            pts = [(s.x * scale, s.y * scale), (e.x * scale, e.y * scale)]
            mid = ((pts[0][0] + pts[1][0]) / 2, (pts[0][1] + pts[1][1]) / 2)
            # 槽口相对分析折线常有 0.2~0.5 mm 偏移，直线用稍宽容差。
            if not keep(pts + [mid], LINE_ON_RING_TOL_MM):
                return
            info.kept_layers.add(layer)
            emit_line(pts[0], pts[1])
            return
        tol = None
        if kind in ("ARC", "CIRCLE"):
            # 分析器把圆弧离散成每段 ≤7.5° 的折线；大半径弧上的点离弦线有弓高，
            # 按弓高放宽，否则大圆弧会被漏抽导致外环断开。
            radius = float(entity.dxf.radius) * scale
            tol = tol_mm + radius * (1.0 - math.cos(ARC_CHORD_SWEEP_RAD / 2.0)) * 1.1
        if not keep(pts, tol):
            return
        info.kept_layers.add(layer)
        if kind in ("ARC", "CIRCLE"):
            ocs = entity.ocs()
            center = ocs.to_wcs(entity.dxf.center)
            cx, cy = center.x * scale, center.y * scale
            r = float(entity.dxf.radius) * scale
            if kind == "CIRCLE":
                k = key_of("C", cx, cy, r)
                if k in seen:
                    info.skipped_duplicates += 1
                    return
                seen.add(k)
                records.append({"kind": "C", "c": (cx, cy), "r": r, "pts": pts})
                return
            sp = entity.start_point
            ep = entity.end_point
            a0 = math.degrees(math.atan2(sp.y * scale - cy, sp.x * scale - cx))
            a1 = math.degrees(math.atan2(ep.y * scale - cy, ep.x * scale - cx))
            if entity.dxf.extrusion.z < 0:
                a0, a1 = a1, a0
            k = key_of("A", cx, cy, r, a0 % 360.0, a1 % 360.0)
            if k in seen:
                info.skipped_duplicates += 1
                return
            seen.add(k)
            records.append(
                {"kind": "A", "c": (cx, cy), "r": r, "a0": a0, "a1": a1, "pts": pts}
            )
            return
        # ELLIPSE / SPLINE：少见，退化为细分折线并记录。
        info.approximated += 1
        for a, b in zip(pts, pts[1:]):
            if math.dist(a, b) > 1e-9:
                records.append({"kind": "L", "a": a, "b": b})

    # 不再按「折弯线」规则跳过：内部折弯线中点不在环上会被 keep() 自然滤掉；
    # 恰好落在外环上的红线/中心线就是轮廓边本身，必须保留（否则外环缺边）。
    for entity in layout:
        kind = entity.dxftype()
        if kind not in GEOMETRY_TYPES:
            continue
        handle(entity, str(entity.dxf.layer))

    records = _clean_topology(records, info, coverage_rings=coverage_rings or outline_rings)
    if not records:
        raise ValueError("原图中没有找到属于所选件的图元。")
    kept_chains = [_record_points(r) for r in records]
    if coverage_rings:
        kept_index = _RingIndex(kept_chains, closed=False)
        # 覆盖环可能含分析器 A→B→A 尖刺，尖端相对原图有 0.2~0.5 mm 偏差；
        # 探针与直线落环容差对齐，并忽略尖刺 tip。
        probe = max(tol_mm, LINE_ON_RING_TOL_MM, 0.1)

        def _strip_spikes(ring: Ring) -> list[Point]:
            pts = list(ring)
            if len(pts) >= 2 and math.dist(pts[0], pts[-1]) <= probe:
                pts = pts[:-1]
            out: list[Point] = []
            n = len(pts)
            i = 0
            while i < n:
                a, b, c = pts[i], pts[(i + 1) % n], pts[(i + 2) % n]
                if math.dist(a, c) <= probe and math.dist(a, b) > probe:
                    out.append(a)
                    i += 3  # 跳过 tip 与重复的 A
                    continue
                out.append(a)
                i += 1
            return out

        missing = [
            p
            for ring in coverage_rings
            for p in _strip_spikes(ring)
            if not kept_index.near(p, probe)
        ]
        if missing:
            raise ValueError(
                f"抽取的图元未覆盖轮廓（{len(missing)} 个顶点缺失，例如 {missing[0]}）。"
            )

    for r in records:
        if r["kind"] == "L":
            a, b = r["a"], r["b"]
            msp.add_line((a[0] - ox, a[1] - oy), (b[0] - ox, b[1] - oy))
            info.lines += 1
        elif r["kind"] == "A":
            msp.add_arc((r["c"][0] - ox, r["c"][1] - oy), r["r"], r["a0"], r["a1"])
            info.arcs += 1
        else:
            msp.add_circle((r["c"][0] - ox, r["c"][1] - oy), r["r"])
            info.circles += 1

    target_path = Path(target)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    out.saveas(str(target_path))
    logger.info(
        "件图元抽取：直线=%d 圆弧=%d 圆=%d 近似=%d 去重=%d 叠圆=%d 重叠线=%d 补缝=%d 剔悬挂=%d 扩槽移动端点=%d 图层=%s → %s",
        info.lines,
        info.arcs,
        info.circles,
        info.approximated,
        info.skipped_duplicates,
        info.removed_dup_circles,
        info.removed_overlaps,
        info.closed_gaps,
        info.peeled_dangling,
        info.moved_endpoints,
        sorted(info.kept_layers),
        target_path,
    )
    return info
