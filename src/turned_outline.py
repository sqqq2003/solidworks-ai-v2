# -*- coding: utf-8 -*-
"""车件轮廓选取（P0）。

工程图里面积最大的闭合环几乎总是图框。零件半边外形往往不是一条闭合多段线，
而是中心线两侧的直线和圆弧。这里沿中心线取外半边包络，供旋转成形。

不做的事（留给后续步骤）：
- 键槽、倒角、外圆滚花、六角对边、螺纹造型、内孔台阶、薄壁管
- SLDDRW / 工程图导出
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, replace
from pathlib import Path

from cad_analyzer import DrawingAnalysis, Primitive, primitive_bounds

Point = tuple[float, float]

_TITLE_HINTS = (
    "审核",
    "制图",
    "比例",
    "材料",
    "图号",
    "批准",
    "设计",
    "技术要求",
    "绘图",
    "審核",
    "設計",
    "繪圖",
    "圖號",
)
_NUMBER = re.compile(r"^\d+(?:\.\d+)?$")
_DIAMETER_MARK = ("%%C", "%%c", "Ø", "Φ", "φ", "⌀", "∅")


@dataclass(frozen=True)
class TurnedSilhouette:
    """拼好的整圈外形，以及截半边时要用的轴线。"""

    outline: Primitive
    axis: str
    position: float
    source: str
    score: float


@dataclass(frozen=True)
class _Axis:
    orientation: str
    position: float
    start: float
    end: float
    center_layer: bool

    @property
    def length(self) -> float:
        return self.end - self.start


def _ring(points: tuple[Point, ...] | list[Point]) -> list[Point]:
    ring = list(points)
    if len(ring) > 1 and math.dist(ring[0], ring[-1]) <= 1e-6:
        ring = ring[:-1]
    return ring


def _poly_area(points: list[Point]) -> float:
    if len(points) < 3:
        return 0.0
    return abs(
        sum(
            start[0] * end[1] - end[0] * start[1]
            for start, end in zip(points, points[1:] + points[:1])
        )
        / 2.0
    )


def is_round_profile(profile: Primitive) -> bool:
    """端面圆。这种环转出来是球或短饼，不是轴的侧视外形。"""

    if profile.kind == "CIRCLE" or profile.circle_center is not None:
        return True
    if not profile.closed:
        return False
    min_x, min_y, max_x, max_y = primitive_bounds(profile)
    width = max_x - min_x
    height = max_y - min_y
    short = min(width, height)
    if short < 1.0:
        return False
    if max(width, height) / short > 1.15:
        return False
    points = _ring(profile.points)
    if len(points) < 12:
        return False
    return _poly_area(points) >= 0.65 * width * height


def is_sheet_frame(profile: Primitive, analysis: DrawingAnalysis) -> bool:
    """图框：贴着图纸边界的扁矩形，并且包住标题栏文字。"""

    if not profile.closed:
        return False
    points = _ring(profile.points)
    if not 4 <= len(points) <= 6:
        return False
    min_x, min_y, max_x, max_y = primitive_bounds(profile)
    width = max_x - min_x
    height = max_y - min_y
    short = min(width, height)
    if short < 80.0 or width < 1.0 or height < 1.0:
        return False
    aspect = max(width, height) / short
    if not 1.15 <= aspect <= 2.05:
        return False
    if _poly_area(points) < 0.90 * width * height:
        return False
    bounds = analysis.bounds
    drawing_w = max(bounds[2] - bounds[0], 1e-6)
    drawing_h = max(bounds[3] - bounds[1], 1e-6)
    if width < 0.75 * drawing_w or height < 0.75 * drawing_h:
        return False
    hits = 0
    for note in analysis.text_entities:
        if not (min_x - 1.0 <= note.x <= max_x + 1.0 and min_y - 1.0 <= note.y <= max_y + 1.0):
            continue
        compact = "".join(note.text.split())
        if any(hint in compact for hint in _TITLE_HINTS):
            hits += 1
            if hits >= 2:
                return True
    return False


def _project(point: Point, axis: _Axis) -> tuple[float, float]:
    if axis.orientation == "horizontal":
        return point[0], point[1] - axis.position
    return point[1], point[0] - axis.position


def _world(axial: float, radius: float, axis: _Axis) -> Point:
    if axis.orientation == "horizontal":
        return axial, axis.position + radius
    return axis.position + radius, axial


def _segment_distance(point: Point, start: Point, end: Point) -> float:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length_sq = dx * dx + dy * dy
    if length_sq <= 1e-12:
        return math.dist(point, start)
    factor = max(0.0, min(1.0, ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length_sq))
    return math.hypot(point[0] - (start[0] + factor * dx), point[1] - (start[1] + factor * dy))


def _near_edges(point: Point, segments: list[tuple[Point, Point]], tolerance: float) -> bool:
    for start, end in segments:
        min_x = min(start[0], end[0]) - tolerance
        max_x = max(start[0], end[0]) + tolerance
        min_y = min(start[1], end[1]) - tolerance
        max_y = max(start[1], end[1]) + tolerance
        if point[0] < min_x or point[0] > max_x or point[1] < min_y or point[1] > max_y:
            continue
        if _segment_distance(point, start, end) <= tolerance:
            return True
    return False


def _mostly_axial(start: Point, end: Point, orientation: str) -> bool:
    """长对角线多半是引出线或断裂线；短倒角和圆弧碎段保留。"""

    dx = abs(end[0] - start[0])
    dy = abs(end[1] - start[1])
    length = math.hypot(dx, dy)
    if length <= 4.0:
        return True
    if orientation == "horizontal":
        along, across = dx, dy
    else:
        along, across = dy, dx
    # 夹角恒按「偏离轴向」来算。原来 along < across 时取了 atan2(along, across)，
    # 量的是偏离"垂直方向"的角度：断裂线越垂直轴线，这个值反而越小（A-020 实测
    # 11.96°），于是近乎竖直的断裂线被当成轴向边，把 outer_radius 撑到 20.3。
    angle = math.degrees(math.atan2(across, max(along, 1e-9)))
    return angle <= 22.0


def _axis_seeds(analysis: DrawingAnalysis) -> list[_Axis]:
    seeds: list[_Axis] = []
    for primitive in analysis.primitives:
        if primitive.closed or len(primitive.points) < 2:
            continue
        layer = primitive.layer
        folded = layer.casefold()
        center_layer = any(word in layer for word in ("中心", "轴线")) or any(
            word in folded for word in ("center", "centre", "axis")
        )
        if not primitive.is_bend and not center_layer:
            continue
        start, end = primitive.points[0], primitive.points[-1]
        dx = abs(end[0] - start[0])
        dy = abs(end[1] - start[1])
        length = math.hypot(dx, dy)
        if length < 8.0:
            continue
        if dy <= 0.40 and dy <= max(0.02 * length, 0.25):
            seeds.append(
                _Axis(
                    "horizontal",
                    (start[1] + end[1]) / 2.0,
                    min(start[0], end[0]),
                    max(start[0], end[0]),
                    center_layer,
                )
            )
        elif dx <= 0.40 and dx <= max(0.02 * length, 0.25):
            seeds.append(
                _Axis(
                    "vertical",
                    (start[0] + end[0]) / 2.0,
                    min(start[1], end[1]),
                    max(start[1], end[1]),
                    center_layer,
                )
            )
    return seeds


def _interval_gap(left_start: float, left_end: float, right_start: float, right_end: float) -> float:
    if left_end < right_start:
        return right_start - left_end
    if right_end < left_start:
        return left_start - right_end
    return 0.0


def _merge_axes(seeds: list[_Axis]) -> list[_Axis]:
    ordered = sorted(seeds, key=lambda item: (item.orientation, round(item.position, 2), item.start))
    merged: list[_Axis] = []
    for seed in ordered:
        if not merged:
            merged.append(seed)
            continue
        last = merged[-1]
        # 只接同一条点划线上的小缝（断裂线两侧），不要把远处的端面十字并进来。
        gap = _interval_gap(last.start, last.end, seed.start, seed.end)
        if (
            last.orientation == seed.orientation
            and abs(last.position - seed.position) <= 0.45
            and gap <= 8.0
        ):
            length = last.length + seed.length
            position = (
                (last.position * last.length + seed.position * seed.length) / length
                if length > 1e-6
                else last.position
            )
            merged[-1] = _Axis(
                last.orientation,
                position,
                min(last.start, seed.start),
                max(last.end, seed.end),
                last.center_layer or seed.center_layer,
            )
            continue
        merged.append(seed)
    return merged


def _circles(analysis: DrawingAnalysis) -> list[tuple[float, float, float]]:
    found: list[tuple[float, float, float]] = []
    for primitive in analysis.profiles:
        if primitive.circle_center is None or primitive.circle_radius is None:
            continue
        center = primitive.circle_center
        found.append((center[0], center[1], primitive.circle_radius))
    return found


def _is_end_view(
    axis: _Axis,
    axes: list[_Axis],
    circles: list[tuple[float, float, float]],
    longest: float,
) -> bool:
    """端面十字中心线：和另一条差不多长的中心线交叉，旁边有圆，或本身远短于主轴。"""

    for other in axes:
        if other.orientation == axis.orientation:
            continue
        if axis.orientation == "horizontal":
            cross_x, cross_y = other.position, axis.position
            on_self = axis.start - 1.0 <= cross_x <= axis.end + 1.0
            on_other = other.start - 1.0 <= cross_y <= other.end + 1.0
            self_at = cross_x
            other_at = cross_y
        else:
            cross_x, cross_y = axis.position, other.position
            on_self = axis.start - 1.0 <= cross_y <= axis.end + 1.0
            on_other = other.start - 1.0 <= cross_x <= other.end + 1.0
            self_at = cross_y
            other_at = cross_x
        if not on_self or not on_other:
            continue
        self_mid = (axis.start + axis.end) / 2.0
        other_mid = (other.start + other.end) / 2.0
        if abs(self_at - self_mid) > 0.38 * max(axis.length, 1.0):
            continue
        if abs(other_at - other_mid) > 0.38 * max(other.length, 1.0):
            continue
        ratio = other.length / max(axis.length, 1e-6)
        if not 0.55 <= ratio <= 1.85:
            continue
        shorter = min(axis.length, other.length)
        if shorter < 0.55 * longest:
            return True
        for center_x, center_y, radius in circles:
            if math.hypot(center_x - cross_x, center_y - cross_y) > max(3.0, 0.3 * radius):
                continue
            diameter = 2.0 * radius
            limit = max(4.0, 0.35 * max(axis.length, other.length))
            if abs(diameter - axis.length) <= limit or abs(diameter - other.length) <= limit:
                return True
    return False


def _is_frame_line(points, bounds) -> bool:
    """图框边线：横平竖直，贴着图幅某一边，长度还占该边的大半。

    图框的四条边本身就是长直线，混进轮廓几何里会把包络撑到整张图幅，
    于是后面的「像图框」判断必被触发，中心线包络永远选不出来。
    """

    if len(points) < 2:
        return False
    min_x, min_y, max_x, max_y = bounds
    width = max(max_x - min_x, 1e-6)
    height = max(max_y - min_y, 1e-6)
    # 内框离外框有 4~5mm（A-020 实测 4.5mm），1% 的带只有 2.8mm，正好漏掉它；
    # 漏掉内框后，标题栏那条横线会被内框顶边"镜像支撑"，outer_radius 直接冲到 81mm。
    band = max(2.0, 0.035 * max(width, height))
    start, end = points[0], points[-1]
    dx = abs(end[0] - start[0])
    dy = abs(end[1] - start[1])
    if dy <= band and dx >= 0.5 * width:
        mid = (start[1] + end[1]) / 2.0
        return min(abs(mid - min_y), abs(mid - max_y)) <= band
    if dx <= band and dy >= 0.5 * height:
        mid = (start[0] + end[0]) / 2.0
        return min(abs(mid - min_x), abs(mid - max_x)) <= band
    return False


def _sheet_has_frame(analysis: DrawingAnalysis) -> bool:
    """图纸里有图框吗？两种表现都算：整圈闭合的图框，或四条独立的边界线。

    SolidWorks 转出来的图（A-016）只有四条边界线、没有闭合图框，
    只按「有无闭合图框」判断会被当成无框简图，标题栏过滤随之失效。
    """

    bounds = analysis.bounds
    for profile in analysis.profiles:
        if is_sheet_frame(profile, analysis):
            return True
    count = 0
    for primitive in analysis.primitives:
        if primitive.is_bend or primitive.closed:
            continue
        if primitive.kind not in ("LINE", "ARC", "LWPOLYLINE", "POLYLINE"):
            continue
        if _is_frame_line(primitive.points, bounds):
            count += 1
            if count >= 2:
                return True
    return False


def _is_frame_loop(points, bounds, frame_detected: bool, ratio: float = 0.85) -> bool:
    """闭合环的包围盒几乎铺满图幅 —— 图框的内外两道边都算。

    外框能被 is_sheet_frame 认出来，内框认不出来：它跟着"实线"层被拼成闭合环，
    于是四条边会逐条喂进轮廓几何，把包络撑到整张图幅。首尾点重合，
    _is_frame_line 那种"看整条折线两端"的判据对它无效，只能看包围盒。
    """

    if not frame_detected or len(points) < 3:
        return False
    min_x, min_y, max_x, max_y = bounds
    width = max(max_x - min_x, 1e-6)
    height = max(max_y - min_y, 1e-6)
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return (max(xs) - min(xs)) >= ratio * width and (max(ys) - min(ys)) >= ratio * height


def _is_title_block_loop(points, bounds, frame_detected: bool) -> bool:
    """贴在图纸边角的闭合环 —— 标题栏。

    标题栏通常压在图幅的左下角，两条边和图框重合；零件视图要留地方标尺寸，
    不可能同时贴住两条边。判定前先确认图纸里确实有图框，否则无框简图的
    外形本来就贴着图幅外沿，会被误杀。
    """

    if not frame_detected or len(points) < 3:
        return False
    min_x, min_y, max_x, max_y = bounds
    tolerance = max(0.5, 0.004 * max(max_x - min_x, max_y - min_y))
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    touches = sum(
        (
            abs(min(xs) - min_x) <= tolerance,
            abs(max(xs) - max_x) <= tolerance,
            abs(min(ys) - min_y) <= tolerance,
            abs(max(ys) - max_y) <= tolerance,
        )
    )
    return touches >= 2


def _outline_polylines(analysis: DrawingAnalysis) -> list[list[Point]]:
    polylines: list[list[Point]] = []
    bounds = analysis.bounds
    frame_indexes = {
        index
        for index, profile in enumerate(analysis.profiles)
        if is_sheet_frame(profile, analysis)
    }
    frame_detected = _sheet_has_frame(analysis)
    for primitive in analysis.primitives:
        if primitive.is_bend or primitive.closed or len(primitive.points) < 2:
            continue
        if primitive.kind not in ("LINE", "ARC", "LWPOLYLINE", "POLYLINE"):
            continue
        if _is_frame_line(primitive.points, bounds):
            continue
        polylines.append(list(primitive.points))
    for index, profile in enumerate(analysis.profiles):
        if index in frame_indexes or not profile.closed or is_round_profile(profile):
            continue
        points = list(profile.points)
        if len(points) < 2:
            continue
        # 内框是逐条边喂进来的闭合环，标题栏则压在图幅边角，都不算零件。
        if _is_frame_loop(points, bounds, frame_detected):
            continue
        if _is_title_block_loop(points, bounds, frame_detected):
            continue
        if math.dist(points[0], points[-1]) > 1e-6:
            points.append(points[0])
        polylines.append(points)
    return polylines


def _flat_segments(polylines: list[list[Point]]) -> list[tuple[Point, Point]]:
    segments: list[tuple[Point, Point]] = []
    for polyline in polylines:
        for start, end in zip(polyline, polyline[1:]):
            if math.dist(start, end) >= 0.02:
                segments.append((start, end))
    return segments


def _symmetry_score(
    axis: _Axis,
    polylines: list[list[Point]],
    segments: list[tuple[Point, Point]],
) -> float:
    del polylines  # 采样只走轴对齐的边，躲开单侧引出线。
    samples: list[Point] = []
    for start, end in segments:
        if not _mostly_axial(start, end, axis.orientation):
            continue
        for point in (start, end):
            axial, radius = _project(point, axis)
            if axial < axis.start - 12.0 or axial > axis.end + 12.0:
                continue
            if not 0.45 <= abs(radius) <= 120.0:
                continue
            samples.append(point)
    if len(samples) < 12:
        return 0.0
    if len(samples) > 180:
        stride = len(samples) / 180.0
        samples = [samples[int(index * stride)] for index in range(180)]
    hits = 0
    for point in samples:
        if axis.orientation == "horizontal":
            mirrored = (point[0], 2.0 * axis.position - point[1])
        else:
            mirrored = (2.0 * axis.position - point[0], point[1])
        if _near_edges(mirrored, segments, 0.65):
            hits += 1
    return hits / len(samples)


def _outer_radius(axis: _Axis, segments: list[tuple[Point, Point]]) -> float | None:
    supported: list[tuple[float, float]] = []
    for start, end in segments:
        if not _mostly_axial(start, end, axis.orientation):
            continue
        axial_start, radius_start = _project(start, axis)
        axial_end, radius_end = _project(end, axis)
        if max(axial_start, axial_end) < axis.start - 12.0 or min(axial_start, axial_end) > axis.end + 12.0:
            continue
        if abs(abs(radius_start) - abs(radius_end)) > 0.45:
            continue
        length = math.dist(start, end)
        if length < 2.0:
            continue
        radius = (abs(radius_start) + abs(radius_end)) / 2.0
        if not 0.6 <= radius <= 120.0:
            continue
        midpoint = ((start[0] + end[0]) / 2.0, (start[1] + end[1]) / 2.0)
        if axis.orientation == "horizontal":
            mirrored = (midpoint[0], 2.0 * axis.position - midpoint[1])
        else:
            mirrored = (2.0 * axis.position - midpoint[0], midpoint[1])
        if _near_edges(mirrored, segments, 0.7):
            supported.append((radius, length))
    if not supported:
        return None
    supported.sort()
    clusters: list[list[float]] = []
    for radius, length in supported:
        if clusters and radius - clusters[-1][0] <= 0.45:
            clusters[-1][1] += length
            clusters[-1][2] += radius * length
        else:
            clusters.append([radius, length, radius * length])
    minimum = max(6.0, 0.10 * axis.length)
    qualified = [item for item in clusters if item[1] >= minimum]
    if not qualified:
        qualified = [item for item in clusters if item[1] >= 4.0]
    if not qualified:
        return None
    best = max(qualified, key=lambda item: item[2] / item[1])
    return best[2] / best[1]


def _boundary_segments(
    axis: _Axis,
    polylines: list[list[Point]],
    outer_radius: float,
) -> tuple[list[tuple[float, float, float, float]], float]:
    """轴线坐标下、朝选定一侧的边界段：(轴向起, 半径起, 轴向止, 半径止)。"""

    cap = outer_radius + max(0.6, 0.03 * outer_radius)
    span_start, span_end = axis.start, axis.end
    chosen: list[tuple[Point, Point]] = []
    for _ in range(4):
        window_start = span_start - 2.8
        window_end = span_end + 2.8
        chosen = []
        next_start, next_end = span_start, span_end
        for polyline in polylines:
            for start, end in zip(polyline, polyline[1:]):
                if math.dist(start, end) < 0.02:
                    continue
                if not _mostly_axial(start, end, axis.orientation):
                    continue
                axial_start, radius_start = _project(start, axis)
                axial_end, radius_end = _project(end, axis)
                if max(abs(radius_start), abs(radius_end)) > cap:
                    continue
                if max(axial_start, axial_end) < window_start or min(axial_start, axial_end) > window_end:
                    continue
                chosen.append((start, end))
                next_start = min(next_start, axial_start, axial_end)
                next_end = max(next_end, axial_start, axial_end)
        span_start, span_end = next_start, next_end
        if not chosen:
            break

    positive = 0.0
    negative = 0.0
    for start, end in chosen:
        _, radius_start = _project(start, axis)
        _, radius_end = _project(end, axis)
        length = math.dist(start, end)
        mean = (radius_start + radius_end) / 2.0
        if mean > 0.15:
            positive += length
        elif mean < -0.15:
            negative += length
    sign = 1.0 if positive >= negative else -1.0

    segments: list[tuple[float, float, float, float]] = []
    for start, end in chosen:
        axial_start, radius_start = _project(start, axis)
        axial_end, radius_end = _project(end, axis)
        radius_start *= sign
        radius_end *= sign
        if axial_start > axial_end:
            axial_start, axial_end = axial_end, axial_start
            radius_start, radius_end = radius_end, radius_start
        clipped = _clip_positive(axial_start, radius_start, axial_end, radius_end)
        segments.extend(clipped)
    return segments, cap


def _clip_positive(
    x0: float,
    r0: float,
    x1: float,
    r1: float,
) -> list[tuple[float, float, float, float]]:
    if r0 >= -0.02 and r1 >= -0.02:
        return [(x0, max(r0, 0.0), x1, max(r1, 0.0))]
    if r0 < -0.02 and r1 < -0.02:
        return []
    if abs(r1 - r0) <= 1e-9:
        return []
    factor = (0.0 - r0) / (r1 - r0)
    cross = x0 + factor * (x1 - x0)
    if r0 >= -0.02:
        return [(x0, max(r0, 0.0), cross, 0.0)]
    return [(cross, 0.0, x1, max(r1, 0.0))]


def _radius_at(
    segments: list[tuple[float, float, float, float]],
    axial: float,
    *,
    incoming: bool,
) -> float | None:
    best: float | None = None
    # Analytic event coordinates must not extend a small fillet over a shaft land.
    tolerance = 1e-7
    for x0, r0, x1, r1 in segments:
        if x1 - x0 <= 1e-6:
            continue
        if incoming:
            if not (x0 < axial - 1e-6 and axial <= x1 + tolerance):
                continue
        elif not (x0 - tolerance <= axial and axial < x1 - 1e-6):
            continue
        factor = (axial - x0) / (x1 - x0)
        if factor < -0.05 or factor > 1.05:
            continue
        factor = min(1.0, max(0.0, factor))
        radius = r0 + (r1 - r0) * factor
        best = radius if best is None else max(best, radius)
    return best


def _cluster_axis(values: list[float], tolerance: float = 1e-7) -> list[float]:
    if not values:
        return []
    ordered = sorted(values)
    groups: list[list[float]] = [[ordered[0]]]
    for value in ordered[1:]:
        if value - groups[-1][0] <= tolerance:
            groups[-1].append(value)
        else:
            groups.append([value])
    return [sum(group) / len(group) for group in groups]


def _upper_envelope(segments: list[tuple[float, float, float, float]]) -> list[Point]:
    if not segments:
        return []
    events = _cluster_axis([value for segment in segments for value in (segment[0], segment[2])])
    points: list[Point] = []
    for axial in events:
        incoming = _radius_at(segments, axial, incoming=True)
        outgoing = _radius_at(segments, axial, incoming=False)
        if incoming is None and outgoing is None:
            continue
        if incoming is None:
            incoming = 0.0
        if outgoing is None:
            outgoing = 0.0
        for radius in (max(0.0, incoming), max(0.0, outgoing)):
            if points and abs(points[-1][0] - axial) <= 1e-3 and abs(points[-1][1] - radius) <= 1e-3:
                continue
            points.append((axial, radius))
    return _bridge_breaks(points)


def _bridge_breaks(points: list[Point]) -> list[Point]:
    """断裂画法会在中段把半径掉到 0。短缺口按两侧肩部接上，两端仍收到轴线上。"""

    if len(points) < 4:
        return points
    length = points[-1][0] - points[0][0]
    max_gap = max(12.0, 0.08 * length)
    floor = 0.25
    bridged: list[Point] = []
    index = 0
    while index < len(points):
        axial, radius = points[index]
        if radius > floor or not bridged or bridged[-1][1] <= floor:
            bridged.append(points[index])
            index += 1
            continue
        lookahead = index
        while lookahead < len(points) and points[lookahead][1] <= floor:
            lookahead += 1
        if (
            lookahead < len(points)
            and points[lookahead][1] > floor
            and points[lookahead][0] - bridged[-1][0] <= max_gap
        ):
            index = lookahead
            continue
        bridged.append(points[index])
        index += 1
    return bridged


def _outline_primitive(envelope: list[Point], axis: _Axis) -> Primitive | None:
    cleaned: list[Point] = []
    for point in envelope:
        if cleaned and abs(cleaned[-1][0] - point[0]) <= 1e-4 and abs(cleaned[-1][1] - point[1]) <= 1e-4:
            continue
        cleaned.append(point)
    if len(cleaned) < 4:
        return None
    if cleaned[0][1] > 0.05:
        cleaned.insert(0, (cleaned[0][0], 0.0))
    if cleaned[-1][1] > 0.05:
        cleaned.append((cleaned[-1][0], 0.0))
    upper = [_world(axial, radius, axis) for axial, radius in cleaned]
    lower = [_world(axial, -radius, axis) for axial, radius in reversed(cleaned)]
    points = upper + lower[1:]
    if math.dist(points[0], points[-1]) > 1e-4:
        points.append(points[0])
    if _poly_area(points) <= 1.0:
        return None
    return Primitive(tuple(points), True, False, "车件外形", "LINE_LOOP")


def _rejects_sheet(
    outline: Primitive,
    analysis: DrawingAnalysis,
) -> bool:
    frames = [profile for profile in analysis.profiles if is_sheet_frame(profile, analysis)]
    if not frames:
        return False
    min_x, min_y, max_x, max_y = primitive_bounds(outline)
    width = max_x - min_x
    height = max_y - min_y
    for frame in frames:
        frame_box = primitive_bounds(frame)
        frame_w = frame_box[2] - frame_box[0]
        frame_h = frame_box[3] - frame_box[1]
        if width > 0.80 * frame_w and height > 0.80 * frame_h:
            return True
    return False


def _silhouette_for_axis(
    axis: _Axis,
    analysis: DrawingAnalysis,
    polylines: list[list[Point]],
    segments: list[tuple[Point, Point]],
) -> TurnedSilhouette | None:
    if axis.length < 12.0:
        return None
    score = _symmetry_score(axis, polylines, segments)
    if score < 0.55:
        return None
    outer_radius = _outer_radius(axis, segments)
    if outer_radius is None or outer_radius < 0.4:
        return None
    boundary, _cap = _boundary_segments(axis, polylines, outer_radius)
    envelope = _upper_envelope(boundary)
    outline = _outline_primitive(envelope, axis)
    if outline is None or _rejects_sheet(outline, analysis):
        return None
    # 候选轴线只来自中心线层，或被分析器标成折弯的点划线/红中心线。
    return TurnedSilhouette(
        outline,
        axis.orientation,
        axis.position,
        "centerline",
        score * axis.length,
    )


def select_turned_silhouettes(analysis: DrawingAnalysis) -> tuple[TurnedSilhouette, ...]:
    """按中心线生成零件整圈外形。没有可用中心线时返回空，调用方再退回闭合轮廓。"""

    seeds = _merge_axes(_axis_seeds(analysis))
    if not seeds:
        return ()
    longest = max(item.length for item in seeds)
    circles = _circles(analysis)
    axes = [item for item in seeds if not _is_end_view(item, seeds, circles, longest)]
    if not axes:
        return ()
    polylines = _outline_polylines(analysis)
    segments = _flat_segments(polylines)
    if not segments:
        return ()
    found: list[TurnedSilhouette] = []
    for axis in axes:
        silhouette = _silhouette_for_axis(axis, analysis, polylines, segments)
        if silhouette is not None:
            found.append(silhouette)
    found.sort(key=lambda item: item.score, reverse=True)
    unique: list[TurnedSilhouette] = []
    for silhouette in found:
        box = primitive_bounds(silhouette.outline)
        if any(_same_part(box, primitive_bounds(other.outline)) for other in unique):
            continue
        unique.append(silhouette)
    return tuple(unique)


def _same_part(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
) -> bool:
    left_c = ((left[0] + left[2]) / 2.0, (left[1] + left[3]) / 2.0)
    right_c = ((right[0] + right[2]) / 2.0, (right[1] + right[3]) / 2.0)
    left_span = max(left[2] - left[0], left[3] - left[1], 1.0)
    return math.dist(left_c, right_c) <= 0.35 * left_span


def _override_number(text: str) -> float | None:
    raw = (text or "").strip()
    if not raw or raw in {"<>", "%%<>"}:
        return None
    cleaned = raw
    for mark in _DIAMETER_MARK:
        cleaned = cleaned.replace(mark, "")
    cleaned = "".join(cleaned.split())
    if _NUMBER.fullmatch(cleaned):
        return float(cleaned)
    return None


def _dimension_targets(
    path: Path,
    length_mm: float,
    radius_mm: float,
    axis: str,
) -> tuple[float | None, float]:
    """标注与图线不一致时，用标注值校正轴向长度和最大半径。

    f19 这类断裂/非 1:1 图：测量长度约 200、文字却是 385，直径测量 12、文字 Ø15。
    测量值已经和选出的外形一致时，才允许改写成文字覆盖值，避免把选错的图框缩放到主尺寸。
    """

    if length_mm <= 1.0 or radius_mm <= 0.2 or not path.is_file():
        return None, 1.0
    try:
        import ezdxf
    except ImportError:
        return None, 1.0
    try:
        document = ezdxf.readfile(path)
    except Exception:
        return None, 1.0

    length_hits: list[tuple[float, float | None]] = []
    radius_hits: list[tuple[float, float | None, str]] = []
    # 尺寸在图纸布局（SW_Model_1）里，不在模型空间：所有布局都要扫。
    for layout in document.layouts:
        for entity in layout:
            if entity.dxftype() != "DIMENSION":
                continue
            try:
                measurement = float(entity.get_measurement())
            except Exception:
                continue
            if measurement < 1.0:
                continue
            text = str(entity.dxf.get("text") or "")
            override = _override_number(text)
            if abs(measurement - length_mm) / length_mm <= 0.08:
                aligned = True
                if entity.dxf.hasattr("defpoint2") and entity.dxf.hasattr("defpoint3"):
                    start = entity.dxf.defpoint2
                    end = entity.dxf.defpoint3
                    dx = abs(end.x - start.x)
                    dy = abs(end.y - start.y)
                    if axis == "horizontal":
                        aligned = dx >= dy
                    else:
                        aligned = dy >= dx
                if aligned:
                    length_hits.append((measurement, override))
            if abs(measurement - 2.0 * radius_mm) / (2.0 * radius_mm) <= 0.10:
                radius_hits.append((measurement, override, text))

    target_length: float | None = None
    if length_hits:
        overridden = [
            item
            for item in length_hits
            if item[1] is not None and abs(item[1] - item[0]) / item[0] > 0.02
        ]
        if overridden:
            _measurement, override = min(overridden, key=lambda item: abs(item[0] - length_mm))
            if override is not None and 0.5 * length_mm <= override <= 4.0 * length_mm:
                target_length = override
        else:
            measurement, _override = min(length_hits, key=lambda item: abs(item[0] - length_mm))
            relative = abs(measurement - length_mm) / length_mm
            if 0.0015 < relative <= 0.03:
                target_length = measurement

    radius_scale = 1.0
    overridden_radii = [
        item
        for item in radius_hits
        if item[1] is not None and abs(item[1] - item[0]) / item[0] > 0.02
    ]
    if overridden_radii:
        measurement, override, _text = min(
            overridden_radii,
            key=lambda item: abs(item[0] - 2.0 * radius_mm),
        )
        if override is not None and measurement > 0:
            scale = override / measurement
            if 0.7 <= scale <= 1.8:
                radius_scale = scale
    return target_length, radius_scale


def apply_dimension_overrides(plan, analysis: DrawingAnalysis):
    """把半边轮廓的轴向/半径改到与主标注一致。标注不矛盾时原样返回。"""

    # 尺寸标注要用转出来的 DXF 读，DWG 本身 ezdxf 打不开。
    source = getattr(analysis, "dxf_path", None) or getattr(analysis, "path", None)
    target_length, radius_scale = _dimension_targets(
        Path(source),
        plan.length_mm,
        plan.max_radius_mm,
        plan.axis,
    )
    length_scale = 1.0 if target_length is None else target_length / plan.length_mm
    if abs(length_scale - 1.0) < 0.002 and abs(radius_scale - 1.0) < 0.002:
        return plan
    origin = min(point[0] for point in plan.profile)
    profile = tuple(
        (origin + (point[0] - origin) * length_scale, point[1] * radius_scale)
        for point in plan.profile
    )
    holes = []
    for hole in plan.holes:
        if plan.axis == "horizontal" and hole.x is not None:
            holes.append(replace(hole, x=origin + (hole.x - origin) * length_scale))
        elif plan.axis == "vertical" and hole.y is not None:
            holes.append(replace(hole, y=origin + (hole.y - origin) * length_scale))
        else:
            holes.append(hole)
    return replace(plan, profile=profile, holes=tuple(holes))
