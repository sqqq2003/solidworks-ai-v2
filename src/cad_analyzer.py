from __future__ import annotations

import math
import logging
import time
from dataclasses import dataclass, replace
from pathlib import Path
from tempfile import TemporaryDirectory, gettempdir
from typing import Iterable

import ezdxf
from ezdxf import units
from ezdxf.colors import aci2rgb

from dwg_converter import DwgConversionError, iter_dwg_converters
from roller_drawing import (
    RollerDrawingVariant,
    decode_solidworks_text,
    extract_roller_variants,
    extract_roller_variants_from_filename,
    looks_like_roller_drawing,
)

Point = tuple[float, float]
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SketchSegment:
    start: Point
    end: Point
    center: Point | None = None
    sweep_angle: float = 0.0


@dataclass(frozen=True)
class Primitive:
    points: tuple[Point, ...]
    closed: bool
    is_bend: bool
    layer: str
    kind: str
    curve_segments: tuple[SketchSegment, ...] = ()
    circle_center: Point | None = None
    circle_radius: float | None = None


@dataclass(frozen=True)
class DrawingText:
    """带插入点的图纸文字。坐标与字高已换算成毫米。"""

    text: str
    x: float
    y: float
    height: float


@dataclass(frozen=True)
class DrawingAnalysis:
    path: Path
    units_name: str
    primitives: tuple[Primitive, ...]
    bend_lines: tuple[Primitive, ...]
    profiles: tuple[Primitive, ...]
    bounds: tuple[float, float, float, float]
    layout_name: str
    roller_variants: tuple[RollerDrawingVariant, ...] = ()
    # 图纸里的文字（含块内注记）：用于读板厚 / 材质，DWG 转换后同样有效。
    texts: tuple[str, ...] = ()
    # 带位置的文字：按行/区把顶部大字厚度挂到零件上。
    text_entities: tuple[DrawingText, ...] = ()
    # DWG 转换出的 DXF 路径：尺寸标注（DIMENSION）要用 ezdxf 读，DWG 本身读不了。
    dxf_path: Path | None = None


def _is_effectively_straight(primitive: Primitive) -> bool:
    """开放多段线是否近似为一条直线（可作手动折弯线）。"""

    if primitive.closed or len(primitive.points) < 2:
        return False
    if any(segment.center is not None for segment in primitive.curve_segments):
        return False
    start, end = primitive.points[0], primitive.points[-1]
    length = math.dist(start, end)
    if length <= 1e-9:
        return False
    unit_x = (end[0] - start[0]) / length
    unit_y = (end[1] - start[1]) / length
    tolerance = max(length * 1e-3, 1e-4)
    for point in primitive.points[1:-1]:
        lateral = abs(
            (point[0] - start[0]) * unit_y - (point[1] - start[1]) * unit_x
        )
        if lateral > tolerance:
            return False
    return True


def is_manual_bend_candidate(primitive: Primitive) -> bool:
    if primitive.closed or primitive.kind not in ("LINE", "LWPOLYLINE", "POLYLINE"):
        return False
    if (
        len(primitive.curve_segments) == 1
        and primitive.curve_segments[0].center is None
    ):
        return True
    return _is_effectively_straight(primitive)


def with_manual_bend_lines(
    analysis: DrawingAnalysis,
    primitive_indices: Iterable[int],
) -> DrawingAnalysis:
    selected = set(primitive_indices)
    if any(index < 0 or index >= len(analysis.primitives) for index in selected):
        raise ValueError("手动标记的线条编号无效。")
    if any(
        not is_manual_bend_candidate(analysis.primitives[index])
        for index in selected
    ):
        raise ValueError("只能将未闭合的直线标记为手动折弯线。")
    primitives = tuple(
        replace(primitive, is_bend=True) if index in selected else primitive
        for index, primitive in enumerate(analysis.primitives)
    )
    merged_primitives, bends = merge_collinear_bend_lines(
        primitives,
        analysis.profiles,
    )
    return replace(
        analysis,
        primitives=merged_primitives,
        bend_lines=bends,
    )


def without_bend_lines(
    analysis: DrawingAnalysis,
    primitive_indices: Iterable[int],
) -> DrawingAnalysis:
    selected = set(primitive_indices)
    if any(index < 0 or index >= len(analysis.primitives) for index in selected):
        raise ValueError("忽略线条编号无效。")
    if any(
        not is_manual_bend_candidate(analysis.primitives[index])
        for index in selected
    ):
        raise ValueError("只能忽略未闭合的直线。")
    primitives = tuple(
        replace(primitive, is_bend=False) if index in selected else primitive
        for index, primitive in enumerate(analysis.primitives)
    )
    merged_primitives, bends = merge_collinear_bend_lines(
        primitives,
        analysis.profiles,
    )
    return replace(
        analysis,
        primitives=merged_primitives,
        bend_lines=bends,
    )


def primitive_bounds(primitive: Primitive) -> tuple[float, float, float, float]:
    if primitive.circle_center is not None and primitive.circle_radius is not None:
        center_x, center_y = primitive.circle_center
        radius = primitive.circle_radius
        return (
            center_x - radius,
            center_y - radius,
            center_x + radius,
            center_y + radius,
        )
    points = list(primitive.points)
    cardinal_angles = (0.0, math.pi / 2, math.pi, 3 * math.pi / 2)
    for segment in primitive.curve_segments:
        if segment.center is None or abs(segment.sweep_angle) <= 1e-10:
            continue
        radius = math.dist(segment.start, segment.center)
        start_angle = math.atan2(
            segment.start[1] - segment.center[1],
            segment.start[0] - segment.center[0],
        )
        if abs(segment.sweep_angle) >= math.tau - 1e-10:
            points.extend(
                (
                    segment.center[0] + radius * math.cos(angle),
                    segment.center[1] + radius * math.sin(angle),
                )
                for angle in cardinal_angles
            )
            continue
        for angle in cardinal_angles:
            offset = (
                (angle - start_angle) % math.tau
                if segment.sweep_angle > 0
                else (start_angle - angle) % math.tau
            )
            if offset <= abs(segment.sweep_angle) + 1e-10:
                points.append(
                    (
                        segment.center[0] + radius * math.cos(angle),
                        segment.center[1] + radius * math.sin(angle),
                    )
                )
    if not points:
        raise ValueError("无法计算空图形的范围。")
    return (
        min(point[0] for point in points),
        min(point[1] for point in points),
        max(point[0] for point in points),
        max(point[1] for point in points),
    )


def _layer_color(doc: ezdxf.document.Drawing, layer_name: str) -> tuple[int, int, int] | None:
    if layer_name not in doc.layers:
        # 有些导出器会写出未定义图层的实体，此时无法判断颜色。
        return None
    layer = doc.layers.get(layer_name)
    if layer.dxf.hasattr("true_color"):
        return tuple(layer.rgb)

    color = aci2rgb(abs(layer.dxf.color))
    return (color.r, color.g, color.b)


def _looks_red(red: int, green: int, blue: int) -> bool:
    if red >= 180 and red >= green * 1.7 and red >= blue * 1.7:
        return True
    # 深红（例如 ACI 12 = 165,0,0、ACI 14 = 127,0,0）亮度达不到上面的阈值，
    # 但红通道明显高于绿蓝，同样是折弯线常见的红色。
    return red >= 110 and red - green >= 80 and red - blue >= 80


def _is_red(doc: ezdxf.document.Drawing, entity: ezdxf.entities.DXFEntity) -> bool:
    if entity.dxf.hasattr("true_color"):
        red, green, blue = entity.rgb
    else:
        color_index = entity.dxf.get("color", 256)
        if color_index in (0, 256):
            color = _layer_color(doc, entity.dxf.get("layer", "0"))
            if color is None:
                return False
            red, green, blue = color
        else:
            color = aci2rgb(abs(color_index))
            red, green, blue = color.r, color.g, color.b
    return _looks_red(red, green, blue)


# 图层名里出现这些词时不作为折弯线：中心线、轴线、尺寸标注等。
_NON_BEND_LAYER_HINTS = (
    "center",
    "dimension",
    "annot",
    "标注",
    "尺寸",
    "中心",
    "轴线",
    "点划",
)
# 展开图里用「中心线」层画折弯线（与红线取并集）。
_CENTERLINE_BEND_LAYER_HINTS = ("中心线",)
# 图层名暗示折弯线（即使线型未正确导出为虚线）。
_BEND_LAYER_HINTS = (
    "bend",
    "折弯",
    "折线",
    "bendline",
    "bending",
)
# 虚线线型：AutoCAD 的 DASHED/HIDDEN 系列，以及中文样板里的"虚线"。
_DASHED_LINETYPE_HINTS = ("DASH", "HIDDEN", "虚线", "HIDDEN2", "DASHED2", "DASHEDX2")
# 点划线/双点划线属于中心线，不是折弯线。必须在虚线判断之前排除，
# 否则 "DASHDOT" 会因为含有 "DASH" 被误判成折弯线。
_CENTER_LINETYPE_HINTS = (
    "DASHDOT",
    "DASHEDDOT",
    "DIVIDE",
    "PHANTOM",
    "CENTER",
    "中心",
    "点划",
)


def _polyline_closed(entity: ezdxf.entities.DXFEntity) -> bool:
    kind = entity.dxftype()
    if kind == "LWPOLYLINE":
        return bool(entity.closed)
    if kind == "POLYLINE":
        return bool(entity.is_closed)
    return False


def _entity_linetype(doc: ezdxf.document.Drawing, entity: ezdxf.entities.DXFEntity) -> str:
    linetype = entity.dxf.get("linetype") or "BYLAYER"
    if linetype.upper() not in ("BYLAYER", "BYBLOCK"):
        return linetype

    layer_name = entity.dxf.get("layer", "0")
    if layer_name not in doc.layers:
        return "Continuous"
    return doc.layers.get(layer_name).dxf.get("linetype") or "Continuous"


def _is_dashed_linetype(linetype: str) -> bool:
    name = linetype.upper()
    if any(hint in name for hint in _CENTER_LINETYPE_HINTS):
        return False
    return any(hint in name for hint in _DASHED_LINETYPE_HINTS)


def _is_bend_line(doc: ezdxf.document.Drawing, entity: ezdxf.entities.DXFEntity) -> bool:
    if entity.dxftype() not in ("LINE", "LWPOLYLINE", "POLYLINE"):
        return False
    if _polyline_closed(entity):
        # 闭合多段线是轮廓；即使画成红色虚线也不能当折弯线，
        # 否则它会从零件候选里消失。
        return False

    layer_name = entity.dxf.get("layer", "0").casefold()
    # 并集规则：「中心线」层上的开放直线也作为折弯线（孔中心十字由
    # profile_bend_indices 按孔内中点剔除）。
    if any(word in layer_name for word in _CENTERLINE_BEND_LAYER_HINTS):
        return True
    if any(word in layer_name for word in _NON_BEND_LAYER_HINTS):
        return False

    red = _is_red(doc, entity)
    linetype = _entity_linetype(doc, entity)
    dashed = _is_dashed_linetype(linetype)
    lt = (linetype or "").casefold()
    solid = not dashed and not any(
        word in lt for word in ("dot", "center", "dash", "hidden", "phantom", "中心", "点")
    )
    bend_layer = any(word in layer_name for word in _BEND_LAYER_HINTS)
    # 常见导出情况：
    # 1) 红虚线（经典）
    # 2) 折弯图层上的红实线（线型丢失）
    # 3) 折弯图层上的虚线（颜色按图层变成非标准红）
    # 4) 纯红实线（展开图常见，闭合轮廓已在上面排除）
    if red and dashed:
        return True
    if red and bend_layer:
        return True
    if dashed and bend_layer:
        return True
    if red and solid:
        return True
    return False


def _bulge_segment(start: Point, end: Point, bulge: float) -> SketchSegment:
    if abs(bulge) < 1e-10:
        return SketchSegment(start, end)
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    chord = math.hypot(dx, dy)
    if chord < 1e-12:
        return SketchSegment(start, end)

    sweep = 4.0 * math.atan(bulge)
    offset = chord * (1.0 - bulge * bulge) / (4.0 * bulge)
    midpoint = ((start[0] + end[0]) / 2.0, (start[1] + end[1]) / 2.0)
    center = (
        midpoint[0] - dy / chord * offset,
        midpoint[1] + dx / chord * offset,
    )
    return SketchSegment(start, end, center, sweep)


def _arc_points(
    segment: SketchSegment,
    *,
    max_sweep: float = math.pi / 24,
) -> list[Point]:
    if segment.center is None or abs(segment.sweep_angle) < 1e-10:
        return [segment.start, segment.end]
    center = segment.center
    radius = math.dist(segment.start, center)
    start_angle = math.atan2(
        segment.start[1] - center[1],
        segment.start[0] - center[0],
    )
    count = max(2, math.ceil(abs(segment.sweep_angle) / max_sweep))
    return [
        (
            center[0] + radius * math.cos(start_angle + segment.sweep_angle * index / count),
            center[1] + radius * math.sin(start_angle + segment.sweep_angle * index / count),
        )
        for index in range(count + 1)
    ]


def _bulge_points(start: Point, end: Point, bulge: float) -> list[Point]:
    return _arc_points(_bulge_segment(start, end, bulge))


def _polyline_path(
    entity: ezdxf.entities.DXFEntity,
) -> tuple[list[Point], bool, tuple[SketchSegment, ...]]:
    if entity.dxftype() == "LWPOLYLINE":
        vertices = list(entity.get_points("xyb"))
        closed = entity.closed
    else:
        vertices = [
            (
                vertex.dxf.location.x,
                vertex.dxf.location.y,
                vertex.dxf.get("bulge", 0.0),
            )
            for vertex in entity.vertices
        ]
        closed = entity.is_closed

    if len(vertices) < 2:
        return [], closed, ()

    points: list[Point] = []
    segments: list[SketchSegment] = []
    edge_count = len(vertices) if closed else len(vertices) - 1
    for index in range(edge_count):
        first = vertices[index]
        second = vertices[(index + 1) % len(vertices)]
        start = (float(first[0]), float(first[1]))
        end = (float(second[0]), float(second[1]))
        segment = _bulge_segment(start, end, float(first[2]))
        segments.append(segment)
        edge = _arc_points(segment)
        points.extend(edge if not points else edge[1:])

    if closed and points and points[-1] != points[0]:
        points.append(points[0])
    return points, closed, tuple(segments)


def _entity_primitive(
    doc: ezdxf.document.Drawing,
    entity: ezdxf.entities.DXFEntity,
) -> Primitive | None:
    kind = entity.dxftype()
    layer = entity.dxf.get("layer", "0")
    is_bend = _is_bend_line(doc, entity)
    curve_segments: tuple[SketchSegment, ...] = ()
    circle_center: Point | None = None
    circle_radius: float | None = None

    if kind == "LINE":
        start = entity.dxf.start
        end = entity.dxf.end
        points = [(float(start.x), float(start.y)), (float(end.x), float(end.y))]
        closed = False
        curve_segments = (SketchSegment(points[0], points[-1]),)
    elif kind in ("LWPOLYLINE", "POLYLINE"):
        points, closed, curve_segments = _polyline_path(entity)
        # 导出时常把本应闭合的轮廓拆成“首尾留缝”的开放多段线。
        if (
            not closed
            and len(points) >= 3
            and math.dist(points[0], points[-1])
            <= max(
                0.05,
                1e-3
                * max(
                    max(point[0] for point in points)
                    - min(point[0] for point in points),
                    max(point[1] for point in points)
                    - min(point[1] for point in points),
                    1.0,
                ),
            )
        ):
            closed = True
            if points[-1] != points[0]:
                points.append(points[0])
    elif kind == "CIRCLE":
        center = entity.dxf.center
        radius = float(entity.dxf.radius)
        circle_center = (float(center.x), float(center.y))
        circle_radius = radius
        points = [
            (
                circle_center[0] + radius * math.cos(math.tau * index / 96),
                circle_center[1] + radius * math.sin(math.tau * index / 96),
            )
            for index in range(97)
        ]
        closed = True
    elif kind == "ARC":
        center = entity.dxf.center
        radius = float(entity.dxf.radius)
        start_angle = math.radians(float(entity.dxf.start_angle))
        end_angle = math.radians(float(entity.dxf.end_angle))
        while end_angle <= start_angle:
            end_angle += math.tau
        circle_center = (float(center.x), float(center.y))
        arc_segment = SketchSegment(
            (
                circle_center[0] + radius * math.cos(start_angle),
                circle_center[1] + radius * math.sin(start_angle),
            ),
            (
                circle_center[0] + radius * math.cos(end_angle),
                circle_center[1] + radius * math.sin(end_angle),
            ),
            circle_center,
            end_angle - start_angle,
        )
        points = _arc_points(arc_segment)
        closed = False
        curve_segments = (arc_segment,)
    else:
        return None

    if len(points) < 2:
        return None
    return Primitive(
        tuple(points),
        closed,
        is_bend,
        layer,
        kind,
        curve_segments,
        circle_center,
        circle_radius,
    )


SegmentMetrics = tuple[Point, Point, float, tuple[float, float, float, float]]


def _line_segment_metrics(primitive: Primitive) -> SegmentMetrics:
    start = primitive.points[0]
    end = primitive.points[-1]
    return (
        start,
        end,
        math.dist(start, end),
        (
            min(start[0], end[0]),
            min(start[1], end[1]),
            max(start[0], end[0]),
            max(start[1], end[1]),
        ),
    )


def _segment_covers(
    outer: SegmentMetrics,
    inner: SegmentMetrics,
    tolerance: float,
) -> bool:
    """判定 outer 是否完全覆盖 inner，与 _line_segment_covers 结果一致。"""
    outer_start, outer_end, length, _ = outer
    inner_start, inner_end, inner_length, _ = inner
    if length <= tolerance or inner_length > length + tolerance:
        return False

    dx, dy = outer_end[0] - outer_start[0], outer_end[1] - outer_start[1]
    for point in (inner_start, inner_end):
        px, py = point[0] - outer_start[0], point[1] - outer_start[1]
        if abs(dx * py - dy * px) > tolerance * length:
            return False
        projection = (px * dx + py * dy) / length
        if projection < -tolerance or projection > length + tolerance:
            return False
    return True


def _line_segment_covers(
    outer: Primitive,
    inner: Primitive,
    tolerance: float,
) -> bool:
    if outer.kind != "LINE" or inner.kind != "LINE":
        return False
    return _segment_covers(
        _line_segment_metrics(outer),
        _line_segment_metrics(inner),
        tolerance,
    )


def _line_arc_junction(
    line: Primitive,
    arc: Primitive,
    tolerance: float,
) -> tuple[int, int, Point, float, float] | None:
    if (
        line.kind != "LINE"
        or arc.kind != "ARC"
        or len(arc.curve_segments) != 1
        or arc.curve_segments[0].center is None
    ):
        return None

    line_start, line_end = line.points[0], line.points[-1]
    dx, dy = line_end[0] - line_start[0], line_end[1] - line_start[1]
    length_squared = dx * dx + dy * dy
    if length_squared <= 1e-18:
        return None

    segment = arc.curve_segments[0]
    center = segment.center
    radius = math.dist(segment.start, center)
    best: tuple[int, int, Point, float, float] | None = None
    for arc_side, arc_endpoint in enumerate((segment.start, segment.end)):
        parameter = (
            (arc_endpoint[0] - line_start[0]) * dx
            + (arc_endpoint[1] - line_start[1]) * dy
        ) / length_squared
        parameter = min(1.0, max(0.0, parameter))
        closest = (
            line_start[0] + parameter * dx,
            line_start[1] + parameter * dy,
        )
        endpoint_gap = math.dist(closest, arc_endpoint)
        line_side = 0 if parameter <= 0.5 else 1
        line_endpoint = line_start if line_side == 0 else line_end
        overrun = math.dist(closest, line_endpoint)
        if endpoint_gap > tolerance or overrun > max(tolerance, radius * 0.15):
            continue
        candidate = (arc_side, line_side, arc_endpoint, endpoint_gap, overrun)
        if best is None or candidate[3:5] < best[3:5]:
            best = candidate
    return best


def _snap_line_arc_junctions(
    segments: list[Primitive],
    tolerance: float,
) -> list[Primitive]:
    line_indices = [
        index for index, primitive in enumerate(segments) if primitive.kind == "LINE"
    ]
    arc_indices = [
        index for index, primitive in enumerate(segments) if primitive.kind == "ARC"
    ]
    if not line_indices or not arc_indices:
        return segments

    endpoints = [
        point
        for index in line_indices + arc_indices
        for point in (segments[index].points[0], segments[index].points[-1])
    ]
    min_x = min(point[0] for point in endpoints)
    min_y = min(point[1] for point in endpoints)
    extent = max(
        max(point[0] for point in endpoints) - min_x,
        max(point[1] for point in endpoints) - min_y,
        1.0,
    )
    cell_size = max(extent / 128.0, tolerance * 4.0)

    def line_cell_span(
        index: int,
    ) -> tuple[int, int, int, int] | None:
        start, end = segments[index].points[0], segments[index].points[-1]
        x0, x1 = min(start[0], end[0]) - tolerance, max(start[0], end[0]) + tolerance
        y0, y1 = min(start[1], end[1]) - tolerance, max(start[1], end[1]) + tolerance
        cx0, cy0 = int((x0 - min_x) // cell_size), int((y0 - min_y) // cell_size)
        cx1, cy1 = int((x1 - min_x) // cell_size), int((y1 - min_y) // cell_size)
        if (cx1 - cx0 + 1) * (cy1 - cy0 + 1) > 256:
            return None
        return cx0, cy0, cx1, cy1

    line_grid: dict[tuple[int, int], list[int]] = {}
    oversized_lines: list[int] = []
    for line_index in line_indices:
        span = line_cell_span(line_index)
        if span is None:
            oversized_lines.append(line_index)
            continue
        cx0, cy0, cx1, cy1 = span
        for cx in range(cx0, cx1 + 1):
            for cy in range(cy0, cy1 + 1):
                line_grid.setdefault((cx, cy), []).append(line_index)

    candidates = []
    for arc_index in arc_indices:
        arc = segments[arc_index]
        nearby_lines = set(oversized_lines)
        for point in (arc.points[0], arc.points[-1]):
            cell = (
                int((point[0] - min_x) // cell_size),
                int((point[1] - min_y) // cell_size),
            )
            nearby_lines.update(line_grid.get(cell, ()))
        for line_index in nearby_lines:
            junction = _line_arc_junction(
                segments[line_index],
                arc,
                tolerance,
            )
            if junction is not None:
                arc_side, line_side, point, endpoint_gap, overrun = junction
                candidates.append(
                    (
                        endpoint_gap,
                        overrun,
                        line_index,
                        arc_index,
                        line_side,
                        arc_side,
                        point,
                    )
                )
    candidates.sort()
    line_updates: dict[int, list[Point]] = {}
    used_line_endpoints: set[tuple[int, int]] = set()
    used_arc_endpoints: set[tuple[int, int]] = set()
    for (
        _,
        _,
        line_index,
        arc_index,
        line_side,
        arc_side,
        point,
    ) in candidates:
        line_key = (line_index, line_side)
        arc_key = (arc_index, arc_side)
        if line_key in used_line_endpoints or arc_key in used_arc_endpoints:
            continue
        used_line_endpoints.add(line_key)
        used_arc_endpoints.add(arc_key)
        line_updates.setdefault(
            line_index,
            list((segments[line_index].points[0], segments[line_index].points[-1])),
        )[line_side] = point

    corrected = list(segments)
    for index, endpoints in line_updates.items():
        primitive = corrected[index]
        curve = primitive.curve_segments[0]
        corrected[index] = replace(
            primitive,
            points=(endpoints[0], endpoints[1]),
            curve_segments=(
                replace(curve, start=endpoints[0], end=endpoints[1]),
            ),
        )
    return corrected


def _overlapping_line_indices(
    segments: list[Primitive],
    tolerance: float,
) -> set[int]:
    """返回被其他更长直线覆盖的直线下标。

    覆盖者必须完整包住被覆盖者，因此先按包围盒把候选配对限制在相邻网格内，
    再套用与 _line_segment_covers 相同的判定。候选集是真实覆盖者的超集，
    结果与原双重循环一致，但不再是 O(n^2) 的全量比较。
    """
    line_indices = [
        index for index, primitive in enumerate(segments) if primitive.kind == "LINE"
    ]
    if len(line_indices) < 2:
        return set()
    metrics = {index: _line_segment_metrics(segments[index]) for index in line_indices}

    min_x = min(metrics[index][3][0] for index in line_indices)
    min_y = min(metrics[index][3][1] for index in line_indices)
    max_x = max(metrics[index][3][2] for index in line_indices)
    max_y = max(metrics[index][3][3] for index in line_indices)
    extent = max(max_x - min_x, max_y - min_y, 1.0)
    cell = max(extent / 128.0, tolerance * 4.0)
    max_cells = 256

    def cell_span(index: int, slack: float) -> tuple[int, int, int, int] | None:
        _, _, _, (x0, y0, x1, y1) = metrics[index]
        cx0 = int((x0 - slack - min_x) // cell)
        cy0 = int((y0 - slack - min_y) // cell)
        cx1 = int((x1 + slack - min_x) // cell)
        cy1 = int((y1 + slack - min_y) // cell)
        if (cx1 - cx0 + 1) * (cy1 - cy0 + 1) > max_cells:
            return None
        return cx0, cy0, cx1, cy1

    # 登记时放大 3 倍容差、查询时放大 1 倍容差，保证被覆盖者的查询范围
    # 一定落在覆盖者的登记范围内（覆盖者包围盒比被覆盖者大出至少一个容差）。
    index_slack = tolerance * 3.0
    grid: dict[tuple[int, int], list[int]] = {}
    oversized: list[int] = []
    for index in line_indices:
        span = cell_span(index, index_slack)
        if span is None:
            oversized.append(index)
            continue
        cx0, cy0, cx1, cy1 = span
        for cx in range(cx0, cx1 + 1):
            for cy in range(cy0, cy1 + 1):
                grid.setdefault((cx, cy), []).append(index)

    overlapping: set[int] = set()
    for index in line_indices:
        inner_length = metrics[index][2]
        span = cell_span(index, tolerance)
        if span is None:
            candidates: set[int] = set(line_indices)
        else:
            candidates = set(oversized)
            cx0, cy0, cx1, cy1 = span
            for cx in range(cx0, cx1 + 1):
                for cy in range(cy0, cy1 + 1):
                    candidates.update(grid.get((cx, cy), ()))

        for other_index in candidates:
            if other_index == index:
                continue
            other_length = metrics[other_index][2]
            if other_length < inner_length - tolerance:
                continue
            if not _segment_covers(metrics[other_index], metrics[index], tolerance):
                continue
            if inner_length < other_length - tolerance or (
                abs(inner_length - other_length) <= tolerance and other_index < index
            ):
                overlapping.add(index)
                break
    return overlapping


def _point_in_polygon(point: Point, vertices: tuple[Point, ...]) -> bool:
    """射线法判断点是否落在多边形内（轴对齐的矩形轮廓也适用）。"""
    if len(vertices) < 4:
        return False
    x, y = point
    inside = False
    for start, end in zip(vertices, vertices[1:]):
        if (start[1] > y) != (end[1] > y):
            crossing_x = start[0] + (y - start[1]) * (end[0] - start[0]) / (
                end[1] - start[1]
            )
            if x < crossing_x:
                inside = not inside
    return inside


def _same_bend_endpoints(
    first: Primitive,
    second: Primitive,
    tolerance: float,
) -> bool:
    """两端点重合（允许反向）才算同一条线。长度必须一起对上，禁止接长。"""

    a0, a1 = first.points[0], first.points[-1]
    b0, b1 = second.points[0], second.points[-1]
    if abs(math.dist(a0, a1) - math.dist(b0, b1)) > tolerance:
        return False
    forward = math.dist(a0, b0) <= tolerance and math.dist(a1, b1) <= tolerance
    reverse = math.dist(a0, b1) <= tolerance and math.dist(a1, b0) <= tolerance
    return forward or reverse


def merge_collinear_bend_lines(
    primitives: tuple[Primitive, ...],
    profiles: tuple[Primitive, ...],
    *,
    tolerance: float = 0.05,
) -> tuple[tuple[Primitive, ...], tuple[Primitive, ...]]:
    """去掉端点重合的重复折弯线，保留每条线原来的端点和长度。

    红线 /「中心线」层折弯线识别到什么就用什么。共线的短段不再接成
    贯穿零件的长线，也不为了对齐把端点延伸到轮廓边界。``profiles``
    保留是为了兼容旧调用，去重不按零件把线接长。
    """

    del profiles  # 去重不看所属零件，避免为了“对齐”而把短段接长。
    bends = [primitive for primitive in primitives if primitive.is_bend]
    kept: list[Primitive] = []
    for bend in bends:
        if len(bend.points) < 2:
            continue
        if any(_same_bend_endpoints(bend, other, tolerance) for other in kept):
            continue
        kept.append(bend)
    others = tuple(primitive for primitive in primitives if not primitive.is_bend)
    return others + tuple(kept), tuple(kept)


def _explode_open_polyline(primitive: Primitive) -> list[Primitive]:
    """把开放多段线拆成可参与轮廓拼接的边。"""

    edges: list[Primitive] = []
    segments = primitive.curve_segments
    if not segments and len(primitive.points) >= 2:
        segments = tuple(
            SketchSegment(start, end)
            for start, end in zip(primitive.points, primitive.points[1:])
        )
    for segment in segments:
        if segment.center is None:
            edges.append(
                Primitive(
                    (segment.start, segment.end),
                    False,
                    False,
                    primitive.layer,
                    "LINE",
                    (segment,),
                )
            )
        else:
            edges.append(
                Primitive(
                    tuple(_arc_points(segment)),
                    False,
                    False,
                    primitive.layer,
                    "ARC",
                    (segment,),
                    segment.center,
                    math.dist(segment.start, segment.center),
                )
            )
    return edges


def _contour_edge_segments(primitives: Iterable[Primitive]) -> list[Primitive]:
    edges: list[Primitive] = []
    for primitive in primitives:
        if primitive.is_bend or primitive.closed:
            continue
        if primitive.kind in ("LINE", "ARC"):
            edges.append(primitive)
        elif primitive.kind in ("LWPOLYLINE", "POLYLINE"):
            edges.extend(_explode_open_polyline(primitive))
    return edges


def _cluster_endpoint_snap(
    segments: list[Primitive],
    snap_tolerance: float,
) -> list[Primitive]:
    """把距离小于容差的端点吸附到同一位置，减少缝隙导致的断环。

    绝不能把同一条边的两个端点吸成一点：大图上 snap 可达毫米级，
    用户开的小矩形释放槽边长常 ≤ snap，一旦两端合并，槽口会被轮廓
    对角捷径掉（预览蓝线斜切白线台阶）。

    仅禁止「同一条边两端」不够：短槽两侧端点分属两条相邻边时，仍可能
    被吸到同一簇，平均后变成斜线。合并前还要用「局部最短边长」限制
    吸附距离，避免跨过释放槽短边。
    """

    if not segments or snap_tolerance <= 0:
        return segments
    endpoints: list[Point] = []
    owners: list[tuple[int, int]] = []
    for index, primitive in enumerate(segments):
        endpoints.append(primitive.points[0])
        owners.append((index, 0))
        endpoints.append(primitive.points[-1])
        owners.append((index, 1))

    # 每条边两个端点在 endpoints 中的下标，合并时禁止把它们吸到同一簇。
    segment_end_pairs = tuple(
        (index * 2, index * 2 + 1) for index in range(len(segments))
    )
    edge_lengths = tuple(
        math.dist(endpoints[end_a], endpoints[end_b])
        for end_a, end_b in segment_end_pairs
    )

    parent = list(range(len(endpoints)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        root_left, root_right = find(left), find(right)
        if root_left == root_right:
            return
        # 若合并后某条边的两端落入同一簇，会把短释放槽边塌成零长，拒绝。
        for end_a, end_b in segment_end_pairs:
            root_a, root_b = find(end_a), find(end_b)
            new_a = root_left if root_a in (root_left, root_right) else root_a
            new_b = root_left if root_b in (root_left, root_right) else root_b
            if new_a == new_b:
                return
        parent[root_right] = root_left

    cell = max(snap_tolerance, 1e-9)
    grid: dict[tuple[int, int], list[int]] = {}
    for index, point in enumerate(endpoints):
        cell_key = (math.floor(point[0] / cell), math.floor(point[1] / cell))
        own_len = edge_lengths[owners[index][0]]
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for other in grid.get((cell_key[0] + dx, cell_key[1] + dy), ()):
                    distance = math.dist(point, endpoints[other])
                    if distance > snap_tolerance:
                        continue
                    # 跨过局部短边（释放槽宽/深）的吸附会把台阶拉成对角。
                    local_limit = min(
                        snap_tolerance,
                        0.49 * min(own_len, edge_lengths[owners[other][0]]),
                    )
                    if distance > local_limit + 1e-15:
                        continue
                    union(index, other)
        grid.setdefault(cell_key, []).append(index)

    clusters: dict[int, list[int]] = {}
    for index in range(len(endpoints)):
        clusters.setdefault(find(index), []).append(index)
    snapped = list(endpoints)
    for members in clusters.values():
        if len(members) < 2:
            continue
        average = (
            sum(endpoints[index][0] for index in members) / len(members),
            sum(endpoints[index][1] for index in members) / len(members),
        )
        for index in members:
            snapped[index] = average

    corrected: list[Primitive] = list(segments)
    for endpoint_index, (segment_index, side) in enumerate(owners):
        point = snapped[endpoint_index]
        primitive = corrected[segment_index]
        points = list(primitive.points)
        if side == 0:
            points[0] = point
        else:
            points[-1] = point
        curves = list(primitive.curve_segments)
        if curves:
            if side == 0:
                curves[0] = replace(curves[0], start=point)
            else:
                curves[-1] = replace(curves[-1], end=point)
        corrected[segment_index] = replace(
            primitive,
            points=tuple(points),
            curve_segments=tuple(curves),
        )
    return corrected


def _peel_dangling_edges(
    component: set[int],
    adjacency: dict[tuple[int, int], list[int]],
    segments: list[Primitive],
    key,
) -> set[int]:
    """去掉悬空尺寸线 / 引出线，留下可成环的边。"""

    remaining = set(component)
    while True:
        degree: dict[tuple[int, int], list[int]] = {}
        for index in remaining:
            start, end = segments[index].points[0], segments[index].points[-1]
            degree.setdefault(key(start), []).append(index)
            degree.setdefault(key(end), []).append(index)
        leaves = [
            edges[0]
            for edges in degree.values()
            if len(edges) == 1 and edges[0] in remaining
        ]
        if not leaves:
            break
        remaining.difference_update(leaves)
    return remaining


def _append_oriented_edge(
    ordered: list[Point],
    ordered_curves: list[SketchSegment],
    primitive: Primitive,
    current_key,
    key,
) -> tuple[int, int]:
    """按当前端点方向追加一条边，返回新的端点键。"""

    next_curves = primitive.curve_segments or (
        SketchSegment(primitive.points[0], primitive.points[-1]),
    )
    if key(primitive.points[0]) == current_key:
        ordered.extend(primitive.points[1:])
        ordered_curves.extend(next_curves)
        return key(primitive.points[-1])
    ordered.extend(reversed(primitive.points[:-1]))
    ordered_curves.extend(
        SketchSegment(
            curve.end,
            curve.start,
            curve.center,
            -curve.sweep_angle,
        )
        for curve in reversed(next_curves)
    )
    return key(primitive.points[0])


def _walk_closed_loop(
    start_index: int,
    active: set[int],
    adjacency: dict[tuple[int, int], list[int]],
    segments: list[Primitive],
    key,
) -> tuple[list[Point], list[SketchSegment], set[int]] | None:
    """从一条边出发寻找闭合环；遇分支时回溯尝试。"""

    initial = segments[start_index]
    start, end = initial.points[0], initial.points[-1]
    start_key = key(start)
    seed_ordered = [start, end]
    seed_curves = list(initial.curve_segments) or [SketchSegment(start, end)]
    seed_used = {start_index}

    def search(
        current_key,
        ordered: list[Point],
        ordered_curves: list[SketchSegment],
        used: set[int],
    ) -> tuple[list[Point], list[SketchSegment], set[int]] | None:
        if current_key == start_key and len(used) >= 2:
            closed = list(ordered)
            closed[-1] = closed[0]
            return closed, list(ordered_curves), set(used)
        if len(used) >= len(active):
            return None
        candidates = [
            candidate
            for candidate in adjacency[current_key]
            if candidate in active and candidate not in used
        ]
        # 优先：先拐进台阶，不顺着长边把口子跨过去；再轴对齐、少分支、短边。
        incoming_x = ordered[-1][0] - ordered[-2][0]
        incoming_y = ordered[-1][1] - ordered[-2][1]

        def _candidate_rank(edge: int) -> tuple[int, int, int, float]:
            prim = segments[edge]
            start_pt, end_pt = prim.points[0], prim.points[-1]
            edge_x = end_pt[0] - start_pt[0]
            edge_y = end_pt[1] - start_pt[1]
            if key(start_pt) != current_key:
                edge_x, edge_y = -edge_x, -edge_y
            incoming_len = math.hypot(incoming_x, incoming_y)
            edge_len = math.hypot(edge_x, edge_y)
            cross = abs(incoming_x * edge_y - incoming_y * edge_x)
            dot = incoming_x * edge_x + incoming_y * edge_y
            straight_on = (
                1
                if incoming_len > 1e-9
                and edge_len > 1e-9
                and cross <= 1e-6 * incoming_len * edge_len
                and dot > 0
                else 0
            )
            axis_aligned = (
                0
                if abs(start_pt[0] - end_pt[0]) <= 1e-9
                or abs(start_pt[1] - end_pt[1]) <= 1e-9
                else 1
            )
            branchiness = sum(
                other in active and other not in used and other != edge
                for vertex in (key(start_pt), key(end_pt))
                for other in adjacency[vertex]
            )
            return (straight_on, axis_aligned, branchiness, math.dist(start_pt, end_pt))

        candidates.sort(key=_candidate_rank)
        for next_index in candidates:
            next_ordered = list(ordered)
            next_curves = list(ordered_curves)
            next_used = set(used)
            next_used.add(next_index)
            next_key = _append_oriented_edge(
                next_ordered,
                next_curves,
                segments[next_index],
                current_key,
                key,
            )
            found = search(next_key, next_ordered, next_curves, next_used)
            if found is not None:
                return found
        return None

    return search(key(end), seed_ordered, seed_curves, seed_used)


def _split_lines_at_tjunctions(
    segments: list[Primitive],
    tolerance: float,
) -> list[Primitive]:
    """端点落在另一条直线中部时，把那条直线拆开。

    外轮廓的直角台阶常常口子开在一条长边上，端点并不在长边端点上。
    不拆开的话，拼环会顺着长边走，台阶就不在外轮廓里。
    """

    if tolerance <= 0 or len(segments) < 2:
        return segments
    ends: list[list[Point]] = [
        [segment.points[0], segment.points[-1]] for segment in segments
    ]
    cuts: list[list[float]] = [[] for _ in segments]
    for index, segment in enumerate(segments):
        if any(curve.center is not None for curve in segment.curve_segments):
            continue
        start, end = ends[index]
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        length_sq = dx * dx + dy * dy
        if length_sq <= tolerance * tolerance:
            continue
        length = math.sqrt(length_sq)
        for other_index, other_ends in enumerate(ends):
            if other_index == index:
                continue
            for end_index, point in enumerate(other_ends):
                factor = ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length_sq
                if factor <= tolerance / length or factor >= 1.0 - tolerance / length:
                    continue
                projected = (start[0] + factor * dx, start[1] + factor * dy)
                if math.dist(projected, point) > tolerance:
                    continue
                cuts[index].append(factor)
                ends[other_index][end_index] = projected
    rebuilt: list[Primitive] = []
    for index, segment in enumerate(segments):
        start, end = ends[index]
        if any(curve.center is not None for curve in segment.curve_segments):
            rebuilt.append(segment)
            continue
        if len(cuts[index]) == 0:
            if math.dist(start, end) <= 1e-8:
                continue
            if start == segment.points[0] and end == segment.points[-1]:
                rebuilt.append(segment)
            else:
                rebuilt.append(
                    Primitive(
                        (start, end),
                        False,
                        False,
                        segment.layer,
                        "LINE",
                        (SketchSegment(start, end),),
                    )
                )
            continue
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        ordered = [0.0]
        for factor in sorted(cuts[index]):
            if factor - ordered[-1] > 1e-4 and 1.0 - factor > 1e-4:
                ordered.append(factor)
        ordered.append(1.0)
        for left, right in zip(ordered, ordered[1:]):
            first = (start[0] + left * dx, start[1] + left * dy)
            second = (start[0] + right * dx, start[1] + right * dy)
            if math.dist(first, second) <= 1e-8:
                continue
            rebuilt.append(
                Primitive(
                    (first, second),
                    False,
                    False,
                    segment.layer,
                    "LINE",
                    (SketchSegment(first, second),),
                )
            )
    return rebuilt


def _line_contours(primitives: Iterable[Primitive]) -> list[Primitive]:
    segments = _contour_edge_segments(primitives)
    if not segments:
        return []

    all_points = [
        point
        for primitive in segments
        for point in (primitive.points[0], primitive.points[-1])
    ]
    extent = max(
        max(point[0] for point in all_points) - min(point[0] for point in all_points),
        max(point[1] for point in all_points) - min(point[1] for point in all_points),
        1.0,
    )
    # 精确比较用较小容差；端点吸附只补 DWG 转出后的缝隙（常见 0.2mm 级）。
    # 旧式上限 2mm 会在大零件上把 1–2mm 释放槽顶点吸成一团，拼环后槽口
    # 变成对角捷径。上限压到 0.55mm（仍够线-弧 0.5mm 错位），并靠
    # _cluster_endpoint_snap 禁止把同一条边两端吸塌。
    tolerance = max(extent * 1e-7, 1e-7)
    snap_tolerance = max(min(extent * 3e-3, 0.55), 0.15, tolerance)

    overlapping_segments = _overlapping_line_indices(segments, tolerance)
    segments = [
        primitive
        for index, primitive in enumerate(segments)
        if index not in overlapping_segments
    ]
    segments = _snap_line_arc_junctions(segments, snap_tolerance)
    segments = _cluster_endpoint_snap(segments, snap_tolerance)
    segments = _split_lines_at_tjunctions(segments, snap_tolerance)

    def key(point: Point) -> tuple[int, int]:
        # 吸附后用 snap 网格建邻接，避免 1e-7 量级键把已对齐端点拆开。
        quantum = max(snap_tolerance * 0.5, tolerance)
        return round(point[0] / quantum), round(point[1] / quantum)

    adjacency: dict[tuple[int, int], list[int]] = {}
    for index, primitive in enumerate(segments):
        start, end = primitive.points[0], primitive.points[-1]
        adjacency.setdefault(key(start), []).append(index)
        adjacency.setdefault(key(end), []).append(index)

    visited: set[int] = set()
    contours: list[Primitive] = []
    for initial in range(len(segments)):
        if initial in visited:
            continue
        component: set[int] = set()
        pending = [initial]
        while pending:
            segment_index = pending.pop()
            if segment_index in component:
                continue
            component.add(segment_index)
            primitive = segments[segment_index]
            start, end = primitive.points[0], primitive.points[-1]
            for endpoint in (key(start), key(end)):
                pending.extend(adjacency[endpoint])

        visited.update(component)
        # 先剥掉悬空边（尺寸线、引出线），再在剩余图上抽闭合环。
        active = _peel_dangling_edges(component, adjacency, segments, key)
        while len(active) >= 2:
            walked = None
            for candidate in sorted(active):
                walked = _walk_closed_loop(
                    candidate, active, adjacency, segments, key
                )
                if walked is not None:
                    break
            if walked is None:
                break

            ordered, ordered_curves, used = walked
            active -= used
            layer = segments[min(used)].layer
            contours.append(
                Primitive(
                    tuple(ordered),
                    True,
                    False,
                    layer,
                    "LINE_LOOP",
                    tuple(ordered_curves),
                )
            )
    return contours


def _entity_text_and_placement(
    entity: ezdxf.entities.DXFEntity,
) -> tuple[str, float, float, float] | None:
    kind = entity.dxftype()
    if kind == "TEXT":
        raw = str(entity.dxf.text)
        height = float(entity.dxf.get("height", 0) or 0)
    elif kind == "MTEXT":
        raw = str(entity.text)
        height = float(entity.dxf.get("char_height", 0) or 0)
    else:
        return None
    insert = entity.dxf.insert
    return decode_solidworks_text(raw), float(insert.x), float(insert.y), height


def collect_text_entities(
    doc: ezdxf.document.Drawing,
    layout: ezdxf.layouts.Layout,
    *,
    scale: float = 1.0,
) -> tuple[DrawingText, ...]:
    """布局文字和块参照里的文字，位置已乘图纸单位到毫米。"""

    found: list[DrawingText] = []

    def add(entity: ezdxf.entities.DXFEntity) -> None:
        placed = _entity_text_and_placement(entity)
        if placed is None:
            return
        text, x, y, height = placed
        found.append(DrawingText(text, x * scale, y * scale, height * scale))

    for entity in layout:
        kind = entity.dxftype()
        if kind in ("TEXT", "MTEXT"):
            add(entity)
        elif kind == "INSERT":
            try:
                virtuals = entity.virtual_entities()
            except Exception:  # noqa: BLE001 - 块缺失或变换失败时跳过
                continue
            for virtual in virtuals:
                if virtual.dxftype() in ("TEXT", "MTEXT"):
                    add(virtual)
    del doc
    return tuple(found)


def analyze_dxf(
    path: str | Path,
    *,
    display_path: str | Path | None = None,
) -> DrawingAnalysis:
    """分析 DXF。``display_path`` 用于界面显示与图名回退（DWG 转临时 DXF 时保留原名）。"""

    source = Path(path)
    report_path = Path(display_path) if display_path is not None else source
    doc = ezdxf.readfile(source)
    filename_rollers = extract_roller_variants_from_filename(report_path.name)

    def collect_texts(layout: ezdxf.layouts.Layout) -> tuple[str, ...]:
        """收集布局与块定义里的文字（板厚 / 材质常写在块内注记里）。"""

        found: list[str] = []
        visited: set[str] = set()

        def walk(container: Any) -> None:
            for entity in container:
                kind = entity.dxftype()
                if kind == "TEXT":
                    found.append(decode_solidworks_text(str(entity.dxf.text)))
                elif kind == "MTEXT":
                    found.append(decode_solidworks_text(str(entity.text)))
                elif kind == "INSERT":
                    name = str(entity.dxf.name)
                    if name in visited:
                        continue
                    visited.add(name)
                    try:
                        walk(doc.blocks.get(name))
                    except Exception:  # noqa: BLE001 - 块缺失时跳过
                        continue

        walk(layout)
        return tuple(found)

    def layout_score(layout: ezdxf.layouts.Layout) -> tuple[int, int, int, int]:
        bend_count = sum(_is_bend_line(doc, entity) for entity in layout)
        geometry_count = sum(
            entity.dxftype() in ("LINE", "LWPOLYLINE", "POLYLINE", "CIRCLE", "ARC")
            for entity in layout
        )
        annotation_count = sum(
            entity.dxftype() in ("DIMENSION", "TEXT", "MTEXT", "INSERT")
            for entity in layout
        )
        is_solidworks_model_layout = (
            (geometry_count > 0 or annotation_count > 0)
            and layout.name.casefold().startswith("sw_model_")
        )
        return (
            int(is_solidworks_model_layout),
            annotation_count,
            bend_count,
            geometry_count,
        )

    drawing_layout = max(doc.layouts, key=layout_score)
    if layout_score(drawing_layout) == (0, 0, 0, 0):
        if filename_rollers:
            logger.warning(
                "图纸几乎无几何，但文件名像滚筒图，改用图名规格：%s",
                report_path.name,
            )
            return DrawingAnalysis(
                report_path,
                "未指定（按毫米显示）",
                (),
                (),
                (),
                (0.0, 0.0, 1.0, 1.0),
                drawing_layout.name,
                filename_rollers,
            )
        raise ValueError("CAD 文件中没有可识别的二维线条、圆弧或闭合轮廓。")
    raw_primitives = [
        primitive
        for entity in drawing_layout
        if (primitive := _entity_primitive(doc, entity)) is not None
    ]

    drawing_units = doc.units
    unit_name = units.unit_name(drawing_units) if drawing_units else "未指定（按毫米显示）"
    scale = units.conversion_factor(drawing_units, units.MM) if drawing_units else 1.0
    primitives = tuple(
        Primitive(
            tuple((x * scale, y * scale) for x, y in primitive.points),
            primitive.closed,
            primitive.is_bend,
            primitive.layer,
            primitive.kind,
            tuple(
                SketchSegment(
                    (segment.start[0] * scale, segment.start[1] * scale),
                    (segment.end[0] * scale, segment.end[1] * scale),
                    (
                        (segment.center[0] * scale, segment.center[1] * scale)
                        if segment.center is not None
                        else None
                    ),
                    segment.sweep_angle,
                )
                for segment in primitive.curve_segments
            ),
            (
                (
                    primitive.circle_center[0] * scale,
                    primitive.circle_center[1] * scale,
                )
                if primitive.circle_center is not None
                else None
            ),
            (
                primitive.circle_radius * scale
                if primitive.circle_radius is not None
                else None
            ),
        )
        for primitive in raw_primitives
    )

    explicit_profiles = [
        primitive for primitive in primitives if primitive.closed and not primitive.is_bend
    ]
    connected_profiles = _line_contours(primitives)
    profiles = tuple(explicit_profiles + connected_profiles)
    primitives, bends = merge_collinear_bend_lines(primitives, profiles)
    visible_primitives = primitives + tuple(connected_profiles)
    geometry_bounds = [primitive_bounds(primitive) for primitive in visible_primitives]
    if not geometry_bounds:
        bounds = (0.0, 0.0, 1.0, 1.0)
    else:
        bounds = (
            min(item[0] for item in geometry_bounds),
            min(item[1] for item in geometry_bounds),
            max(item[2] for item in geometry_bounds),
            max(item[3] for item in geometry_bounds),
        )

    try:
        # 几何布局与注记布局可能不一致：遍历全部布局，取规格最多的一组。
        roller_variants: tuple[RollerDrawingVariant, ...] = ()
        for layout in doc.layouts:
            try:
                variants = extract_roller_variants(doc, layout, scale=scale)
            except Exception:
                logger.exception(
                    "布局 %s 滚筒规格识别失败，继续检查其他布局",
                    layout.name,
                )
                continue
            if len(variants) > len(roller_variants):
                roller_variants = variants
        if not roller_variants and filename_rollers:
            logger.info(
                "图内未解析出滚筒规格，回退使用文件名：%s", report_path.name
            )
            roller_variants = filename_rollers
        elif roller_variants and filename_rollers:
            # 图内有规格但总长缺失时，用图名里的 1.3米 等补上。
            filled: list[RollerDrawingVariant] = []
            for variant in roller_variants:
                if variant.overall_length_mm is not None:
                    filled.append(variant)
                    continue
                name_length = filename_rollers[0].overall_length_mm
                if name_length is None:
                    filled.append(variant)
                    continue
                filled.append(
                    replace(
                        variant,
                        overall_length_mm=name_length,
                        inferred_fields=frozenset(
                            set(variant.inferred_fields) | {"overall_length_mm"}
                        ),
                    )
                )
            roller_variants = tuple(filled)
    except Exception:
        logger.exception("从图纸自动识别滚筒规格失败，继续使用普通 CAD 流程")
        roller_variants = filename_rollers

    if looks_like_roller_drawing(
        roller_variants,
        bend_count=len(bends),
        path_name=report_path.name,
    ):
        logger.info(
            "图纸判定为滚筒尺寸图：%s（规格 %d 种，折弯线 %d 条）",
            report_path.name,
            len(roller_variants),
            len(bends),
        )

    return DrawingAnalysis(
        report_path,
        unit_name,
        visible_primitives,
        bends,
        profiles,
        bounds,
        drawing_layout.name,
        roller_variants,
        collect_texts(drawing_layout),
        collect_text_entities(doc, drawing_layout, scale=scale),
        source,
    )


def _analysis_richness(analysis: DrawingAnalysis) -> tuple[int, int, int]:
    """比较两份 DWG 转换结果时，优先滚筒规格，其次轮廓与图元。"""

    return (
        len(analysis.roller_variants),
        len(analysis.profiles),
        len(analysis.primitives),
    )


def _persistent_dwg_workdir() -> Path:
    """DWG→DXF 的持久工作目录。

    转换出的 DXF 要在分析结束后继续供 DIMENSION 读取（车件功能靠它拿孔径和
    螺纹标注），所以不能放在随用随删的 TemporaryDirectory 里。目录定期清理
    三天前的旧文件。
    """

    work = Path(gettempdir()) / "cad2sw_dwg_dxf"
    work.mkdir(parents=True, exist_ok=True)
    cutoff = time.time() - 3 * 24 * 3600
    try:
        for stale in work.glob("*.dxf"):
            try:
                if stale.stat().st_mtime < cutoff:
                    stale.unlink()
            except OSError:
                continue
    except OSError:
        pass
    return work


def analyze_cad_file(path: str | Path) -> DrawingAnalysis:
    source = Path(path)
    extension = source.suffix.lower()
    if extension == ".dxf":
        return analyze_dxf(source)
    if extension != ".dwg":
        raise ValueError(f"不支持的 CAD 文件格式：{source.suffix or '无扩展名'}")

    filename_rollers = extract_roller_variants_from_filename(source.name)
    errors: list[str] = []
    try:
        work = _persistent_dwg_workdir()
        stamp = f"{time.time_ns():x}"
        candidates: list[tuple[str, DrawingAnalysis]] = []
        # 逐个转换器试：Drawing1.dwg 经 SolidWorks 常“成功”但无滚筒注记，
        # LibreDWG 反而能保留块内规格——取滚筒规格更多的那份。
        for converter_name, converter in iter_dwg_converters(source):
            converted_path = work / f"{source.stem}_{converter_name}_{stamp}.dxf"
            try:
                converter(source, converted_path)
                analysis = analyze_dxf(converted_path, display_path=source)
                candidates.append((converter_name, analysis))
                logger.info(
                    "DWG 转换成功（%s）：%s → 滚筒规格 %d / 轮廓 %d",
                    converter_name,
                    source.name,
                    len(analysis.roller_variants),
                    len(analysis.profiles),
                )
            except (DwgConversionError, OSError, ValueError, ezdxf.DXFError) as error:
                errors.append(f"{converter_name}: {error}")
                logger.warning(
                    "DWG 转换器 %s 失败：%s（%s）",
                    converter_name,
                    source.name,
                    error,
                )

        if candidates:
            # 若首选已有滚筒规格，仍看其它转换器是否识别出更多规格。
            best_name, best = max(
                candidates, key=lambda item: _analysis_richness(item[1])
            )
            if len(candidates) > 1:
                logger.info(
                    "DWG 选用转换结果：%s（滚筒 %d）← 候选 %s",
                    best_name,
                    len(best.roller_variants),
                    ", ".join(
                        f"{name}:{len(item.roller_variants)}"
                        for name, item in candidates
                    ),
                )
            return best

        # 两路都失败：仅当图名像滚筒尺寸图时回退。
        joined = "；".join(errors) if errors else "DWG 转换失败。"
        raise DwgConversionError(joined)
    except (DwgConversionError, OSError, ValueError) as error:
        if not filename_rollers:
            raise
        # 斜滚筒专用图等：转换全失败时，仍按图名进入滚筒流程。
        logger.warning(
            "DWG 转换失败，回退为文件名滚筒规格：%s（%s）",
            source.name,
            error,
        )
        return DrawingAnalysis(
            source,
            "未指定（按毫米显示）",
            (),
            (),
            (),
            (0.0, 0.0, 1.0, 1.0),
            "文件名回退",
            filename_rollers,
        )
