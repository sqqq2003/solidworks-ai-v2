"""Sheet-metal profile, bend-line and relief geometry.

Pure geometry; nothing here calls COM or needs a SolidWorks session.
``solidworks_generator`` re-exports every name for existing callers.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Iterable

from cad_analyzer import (
    DrawingAnalysis,
    Primitive,
    SketchSegment,
    primitive_bounds,
)
from profile_sanitize import profile_span_mm
from profile_selection import contained_hole_indices


# 写死：矩形释放槽扩级（绝对值，不是板厚比例）。
# step0 不扩；step1 长宽各 +1.0mm；之后每级再 +0.5mm。
# 累计：step≥1 → 1.0 + (step-1)*0.5
RECT_RELIEF_FIRST_EXPAND_MM = 1.0
RECT_RELIEF_EXPAND_MM = 0.5


def rect_relief_extra_mm(relief_step: int) -> float:
    """relief_step 对应的矩形释放槽边长累计扩量（mm）。step≤0 → 0。"""
    if relief_step <= 0:
        return 0.0
    return RECT_RELIEF_FIRST_EXPAND_MM + (relief_step - 1) * RECT_RELIEF_EXPAND_MM


@dataclass(frozen=True)
class ReliefCutout:
    center: tuple[float, float]
    radius_mm: float
    replaced_profile_index: int | None = None


def _line_intersection(
    first: Primitive,
    second: Primitive,
) -> tuple[float, float] | None:
    first_start, first_end = first.points[0], first.points[-1]
    second_start, second_end = second.points[0], second.points[-1]
    first_dx = first_end[0] - first_start[0]
    first_dy = first_end[1] - first_start[1]
    second_dx = second_end[0] - second_start[0]
    second_dy = second_end[1] - second_start[1]
    denominator = first_dx * second_dy - first_dy * second_dx
    if abs(denominator) <= 1e-10:
        return None
    offset_x = second_start[0] - first_start[0]
    offset_y = second_start[1] - first_start[1]
    factor = (offset_x * second_dy - offset_y * second_dx) / denominator
    return (
        first_start[0] + factor * first_dx,
        first_start[1] + factor * first_dy,
    )


def _segment_intersection(
    first_start: tuple[float, float],
    first_end: tuple[float, float],
    second_start: tuple[float, float],
    second_end: tuple[float, float],
) -> tuple[float, float] | None:
    first_dx = first_end[0] - first_start[0]
    first_dy = first_end[1] - first_start[1]
    second_dx = second_end[0] - second_start[0]
    second_dy = second_end[1] - second_start[1]
    denominator = first_dx * second_dy - first_dy * second_dx
    if abs(denominator) <= 1e-12:
        return None
    offset_x = second_start[0] - first_start[0]
    offset_y = second_start[1] - first_start[1]
    first_factor = (offset_x * second_dy - offset_y * second_dx) / denominator
    second_factor = (offset_x * first_dy - offset_y * first_dx) / denominator
    tolerance = 1e-9
    if not -tolerance <= first_factor <= 1.0 + tolerance:
        return None
    if not -tolerance <= second_factor <= 1.0 + tolerance:
        return None
    return (
        first_start[0] + first_factor * first_dx,
        first_start[1] + first_factor * first_dy,
    )


def _bend_profile_intersections(
    bend: Primitive,
    profile: Primitive,
) -> tuple[tuple[float, float], ...]:
    """折弯线与外轮廓的交点，即折弯端部需要释放空间的位置。"""
    start, end = bend.points[0], bend.points[-1]
    points = profile.points
    found: list[tuple[float, float]] = []
    for first, second in zip(points, points[1:]):
        hit = _segment_intersection(start, end, first, second)
        if hit is not None:
            found.append(hit)
    return tuple(found)


def _ray_profile_hit(
    origin: tuple[float, float],
    direction: tuple[float, float],
    profile: Primitive,
) -> tuple[float, float] | None:
    """从 origin 沿 direction 射出，返回与外轮廓最近的交点。"""
    origin_x, origin_y = origin
    direction_x, direction_y = direction
    points = profile.points
    best_distance: float | None = None
    best_point: tuple[float, float] | None = None
    for first, second in zip(points, points[1:]):
        edge_x = second[0] - first[0]
        edge_y = second[1] - first[1]
        denominator = direction_x * edge_y - direction_y * edge_x
        if abs(denominator) <= 1e-12:
            continue
        offset_x = first[0] - origin_x
        offset_y = first[1] - origin_y
        ray_factor = (offset_x * edge_y - offset_y * edge_x) / denominator
        edge_factor = (
            offset_x * direction_y - offset_y * direction_x
        ) / denominator
        if ray_factor < -1e-9 or not -1e-9 <= edge_factor <= 1.0 + 1e-9:
            continue
        if best_distance is not None and ray_factor >= best_distance:
            continue
        best_distance = ray_factor
        best_point = (
            origin_x + direction_x * ray_factor,
            origin_y + direction_y * ray_factor,
        )
    return best_point


def _bend_outline_ends(
    bend: Primitive,
    profile: Primitive,
) -> tuple[tuple[float, float], ...]:
    """折弯两端与外轮廓的交点。

    折弯线本身就跨过轮廓时直接取交点；图纸里把折弯线画成悬在零件内部
    的短线段时（常见于两端各画一小段示意），则沿折弯方向延长到轮廓，
    否则软件无法给出释放槽位置，只能放弃生成。
    """
    start, end = bend.points[0], bend.points[-1]
    direct = _bend_profile_intersections(bend, profile)
    if direct:
        return direct
    delta_x = end[0] - start[0]
    delta_y = end[1] - start[1]
    length = math.hypot(delta_x, delta_y)
    if length <= 1e-12:
        return ()
    unit_x, unit_y = delta_x / length, delta_y / length
    found: list[tuple[float, float]] = []
    forward = _ray_profile_hit(end, (unit_x, unit_y), profile)
    if forward is not None:
        found.append(forward)
    backward = _ray_profile_hit(start, (-unit_x, -unit_y), profile)
    if backward is not None:
        found.append(backward)
    return tuple(found)


def _bend_feature_outline_span(
    bend: Primitive,
    profile: Primitive,
) -> tuple[tuple[float, float], tuple[float, float]] | None:
    """特征草图用的整段穿越：即使红线只碰到一条边，也取这条线上离得最远的两个交点。"""

    start, end = bend.points[0], bend.points[-1]
    delta_x = end[0] - start[0]
    delta_y = end[1] - start[1]
    length = math.hypot(delta_x, delta_y)
    if length <= 1e-12:
        return None
    unit_x, unit_y = delta_x / length, delta_y / length
    found: list[tuple[float, float]] = list(_bend_profile_intersections(bend, profile))
    midpoint = ((start[0] + end[0]) / 2.0, (start[1] + end[1]) / 2.0)
    for origin, direction in (
        (end, (unit_x, unit_y)),
        (start, (-unit_x, -unit_y)),
        (midpoint, (unit_x, unit_y)),
        (midpoint, (-unit_x, -unit_y)),
    ):
        hit = _ray_profile_hit(origin, direction, profile)
        if hit is not None:
            found.append(hit)
    if len(found) < 2:
        return None

    def _along(point: tuple[float, float]) -> float:
        return point[0] * unit_x + point[1] * unit_y

    found.sort(key=_along)
    if math.dist(found[0], found[-1]) <= 1e-6:
        return None
    return found[0], found[-1]


def _profile_ring_points(
    profile: Primitive,
) -> list[tuple[float, float]]:
    points = list(profile.points)
    if len(points) > 1 and math.dist(points[0], points[-1]) <= 1e-9:
        points = points[:-1]
    return points


def _polyline_from_ring(
    profile: Primitive,
    ring: list[tuple[float, float]],
) -> Primitive:
    if len(ring) < 3:
        return profile
    closed = list(ring)
    if math.dist(closed[0], closed[-1]) > 1e-9:
        closed.append(closed[0])
    segments = tuple(
        SketchSegment(start, end)
        for start, end in zip(closed, closed[1:])
        if math.dist(start, end) > 1e-12
    )
    return replace(
        profile,
        points=tuple(closed),
        closed=True,
        curve_segments=segments,
        circle_center=None,
        circle_radius=None,
        kind=profile.kind if profile.kind not in ("CIRCLE",) else "LINE_LOOP",
    )


def _is_axis_aligned_pair(
    a: tuple[float, float],
    b: tuple[float, float],
    *,
    tol: float = 1e-6,
) -> bool:
    return abs(a[0] - b[0]) <= tol or abs(a[1] - b[1]) <= tol


def axis_aligned_rect_bounds(
    profile: Primitive,
    *,
    tol: float = 1e-4,
) -> tuple[float, float, float, float] | None:
    """若轮廓是轴对齐矩形，返回 (minx, miny, maxx, maxy)。"""

    ring = _profile_ring_points(profile)
    if len(ring) < 4:
        return None
    for start, end in zip(ring, ring[1:] + ring[:1]):
        if not _is_axis_aligned_pair(start, end, tol=tol):
            return None
    xs = [point[0] for point in ring]
    ys = [point[1] for point in ring]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    if max_x - min_x <= tol or max_y - min_y <= tol:
        return None
    for x, y in ring:
        on_v = abs(x - min_x) <= tol or abs(x - max_x) <= tol
        on_h = abs(y - min_y) <= tol or abs(y - max_y) <= tol
        if not (on_v or on_h):
            return None
        if on_v and not (min_y - tol <= y <= max_y + tol):
            return None
        if on_h and not (min_x - tol <= x <= max_x + tol):
            return None
    return min_x, min_y, max_x, max_y


def expand_axis_aligned_rect_profile(
    profile: Primitive,
    extra_mm: float,
) -> Primitive:
    """矩形孔：长、宽各加大 extra_mm，中心不变。"""

    if extra_mm <= 0:
        return profile
    bounds = axis_aligned_rect_bounds(profile)
    if bounds is None:
        return profile
    min_x, min_y, max_x, max_y = bounds
    width = max_x - min_x
    height = max_y - min_y
    center = ((min_x + max_x) / 2.0, (min_y + max_y) / 2.0)
    half_w = (width + extra_mm) / 2.0
    half_h = (height + extra_mm) / 2.0
    ring = [
        (center[0] - half_w, center[1] - half_h),
        (center[0] + half_w, center[1] - half_h),
        (center[0] + half_w, center[1] + half_h),
        (center[0] - half_w, center[1] + half_h),
    ]
    return _polyline_from_ring(profile, ring)


def _distance_point_to_segment(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length_sq = dx * dx + dy * dy
    if length_sq <= 1e-18:
        return math.dist(point, start)
    factor = ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length_sq
    factor = min(1.0, max(0.0, factor))
    return math.dist(point, (start[0] + factor * dx, start[1] + factor * dy))


def _panel_sign_from_bends(
    axis: str,
    cx: float,
    cy: float,
    bend_lines: tuple[Primitive, ...],
) -> float | None:
    """离槽最近的折弯线：沿法向哪一侧已经在板面里，扩槽就继续往哪一侧。"""

    best: tuple[tuple[float, float], tuple[float, float]] | None = None
    best_distance = 1e9
    for bend in bend_lines:
        if len(bend.points) < 2:
            continue
        start, end = bend.points[0], bend.points[-1]
        distance = _distance_point_to_segment((cx, cy), start, end)
        if distance < best_distance:
            best_distance = distance
            best = (start, end)
    if best is None or best_distance > 25.0:
        return None
    start, end = best
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length = math.hypot(dx, dy)
    if length <= 1e-9:
        return None
    normal_x, normal_y = -dy / length, dx / length
    signed = (cx - start[0]) * normal_x + (cy - start[1]) * normal_y
    component = signed * (normal_x if axis == "x" else normal_y)
    if abs(component) <= 1e-6:
        return None
    return 1.0 if component > 0.0 else -1.0


def _one_sided_panel_sign(
    axis: str,
    cluster: list[tuple[int, float, float, bool, bool]],
    ring: list[tuple[float, float]],
    bend_lines: tuple[Primitive, ...],
) -> float:
    """两侧对推时不再各分一半。整份 extra 只加在朝板面的一侧。"""

    cx = sum(ring[item[0]][0] for item in cluster) / len(cluster)
    cy = sum(ring[item[0]][1] for item in cluster) / len(cluster)
    from_bend = _panel_sign_from_bends(axis, cx, cy, bend_lines)
    if from_bend is not None:
        return from_bend
    part_x = sum(point[0] for point in ring) / len(ring)
    part_y = sum(point[1] for point in ring) / len(ring)
    delta = (part_x - cx) if axis == "x" else (part_y - cy)
    if abs(delta) <= 1e-6:
        return 1.0
    return 1.0 if delta > 0.0 else -1.0


def expand_rectangular_relief_notches(
    profile: Primitive,
    extra_mm: float,
    *,
    max_notch_edge_mm: float | None = None,
    bend_lines: tuple[Primitive, ...] = (),
) -> Primitive:
    """外轮廓轴对齐矩形释放槽：长与宽各加大 extra_mm，只朝板面一侧。

    凹角按槽簇处理。某一轴上只有一侧有凹角时，整份 extra 推那一侧。
    两侧都有凹角时也不再各推 extra/2：深度轴整份推向折弯中心线的板面一侧
    （没有折弯线时推向零件内部），宽度轴整份加在稳定的一侧。
    邻点增量用 merge-max，避免叠成双倍。不把槽口改成斜切。
    """

    if extra_mm <= 0:
        return profile
    ring = _profile_ring_points(profile)
    n = len(ring)
    if n < 6:
        return profile

    area = 0.0
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        area += x1 * y2 - x2 * y1
    ccw = area > 0

    span_x = max(p[0] for p in ring) - min(p[0] for p in ring)
    span_y = max(p[1] for p in ring) - min(p[1] for p in ring)
    if max_notch_edge_mm is None:
        max_notch_edge_mm = max(8.0, min(40.0, 0.12 * min(span_x, span_y)))

    def _merge(old: float, new: float) -> float:
        if new == 0.0:
            return old
        if old == 0.0:
            return new
        if (old > 0 and new > 0) or (old < 0 and new < 0):
            return math.copysign(max(abs(old), abs(new)), new)
        # 相反方向：保留幅度更大者
        return new if abs(new) >= abs(old) else old

    # Detect concave AA corners and their raw push directions.
    corners: list[tuple[int, float, float, bool, bool]] = []
    for i in range(n):
        prev_pt = ring[(i - 1) % n]
        point = ring[i]
        next_pt = ring[(i + 1) % n]
        if not (
            _is_axis_aligned_pair(prev_pt, point)
            and _is_axis_aligned_pair(point, next_pt)
        ):
            continue
        len_in = math.dist(prev_pt, point)
        len_out = math.dist(point, next_pt)
        if len_in > max_notch_edge_mm or len_out > max_notch_edge_mm:
            continue
        if len_in <= 1e-9 or len_out <= 1e-9:
            continue
        cross = (point[0] - prev_pt[0]) * (next_pt[1] - point[1]) - (
            point[1] - prev_pt[1]
        ) * (next_pt[0] - point[0])
        is_concave = cross < 0 if ccw else cross > 0
        if not is_concave:
            continue
        horizontal_in = abs(point[1] - prev_pt[1]) <= 1e-6
        horizontal_out = abs(point[1] - next_pt[1]) <= 1e-6
        if horizontal_in == horizontal_out:
            continue
        ua = (prev_pt[0] - point[0], prev_pt[1] - point[1])
        ub = (next_pt[0] - point[0], next_pt[1] - point[1])
        sx = 0.0
        sy = 0.0
        if abs(ua[0] + ub[0]) > 1e-12:
            sx = -math.copysign(1.0, ua[0] + ub[0])
        if abs(ua[1] + ub[1]) > 1e-12:
            sy = -math.copysign(1.0, ua[1] + ub[1])
        if sx == 0.0 and sy == 0.0:
            continue
        corners.append((i, sx, sy, horizontal_in, horizontal_out))

    if not corners:
        return profile

    ordered = sorted(corners, key=lambda item: item[0])
    clusters: list[list[tuple[int, float, float, bool, bool]]] = []
    current = [ordered[0]]
    for item in ordered[1:]:
        if item[0] - current[-1][0] <= 1:
            current.append(item)
        else:
            clusters.append(current)
            current = [item]
    if clusters and (ordered[0][0] + n - current[-1][0]) <= 1:
        current.extend(clusters[0])
        clusters[0] = current
    else:
        clusters.append(current)

    deltas = [(0.0, 0.0) for _ in range(n)]
    for cluster in clusters:
        # 长宽各加 extra，但整份只推向板面一侧，不两侧均分。
        # 凹角更多的一侧就是槽往板面凹进去的方向；两侧一样多时，
        # 深度轴跟最近的折弯中心线（没有线就跟零件内部），宽度轴只动一侧。
        # 现场：往翼板侧扩几乎无效，槽要往板面越过中心线才折得成。
        def _axis_scale(sign: float, n_pos: int, n_neg: int, axis: str) -> float:
            if sign == 0.0 or n_pos == 0 or n_neg == 0:
                return 1.0
            if n_pos != n_neg:
                major = 1.0 if n_pos > n_neg else -1.0
                return 1.0 if sign == major else 0.0
            chosen = _one_sided_panel_sign(axis, cluster, ring, bend_lines)
            return 1.0 if sign == chosen else 0.0

        n_pos_x = sum(1 for _, sx, _, _, _ in cluster if sx > 0)
        n_neg_x = sum(1 for _, sx, _, _, _ in cluster if sx < 0)
        n_pos_y = sum(1 for _, _, sy, _, _ in cluster if sy > 0)
        n_neg_y = sum(1 for _, _, sy, _, _ in cluster if sy < 0)
        for i, sx, sy, horizontal_in, horizontal_out in cluster:
            dpx = extra_mm * sx * _axis_scale(sx, n_pos_x, n_neg_x, "x")
            dpy = extra_mm * sy * _axis_scale(sy, n_pos_y, n_neg_y, "y")
            deltas[i] = (_merge(deltas[i][0], dpx), _merge(deltas[i][1], dpy))
            prev_i = (i - 1) % n
            next_i = (i + 1) % n
            if horizontal_in:
                deltas[prev_i] = (
                    deltas[prev_i][0],
                    _merge(deltas[prev_i][1], dpy),
                )
            else:
                deltas[prev_i] = (
                    _merge(deltas[prev_i][0], dpx),
                    deltas[prev_i][1],
                )
            if horizontal_out:
                deltas[next_i] = (
                    deltas[next_i][0],
                    _merge(deltas[next_i][1], dpy),
                )
            else:
                deltas[next_i] = (
                    _merge(deltas[next_i][0], dpx),
                    deltas[next_i][1],
                )

    if all(abs(dx) <= 1e-15 and abs(dy) <= 1e-15 for dx, dy in deltas):
        return profile
    expanded = [
        (point[0] + delta[0], point[1] + delta[1])
        for point, delta in zip(ring, deltas)
    ]
    return _polyline_from_ring(profile, expanded)


def is_small_rectangular_relief_hole(
    hole: Primitive,
    outer: Primitive,
    *,
    max_side_mm: float | None = None,
) -> bool:
    bounds = axis_aligned_rect_bounds(hole)
    if bounds is None:
        return False
    min_x, min_y, max_x, max_y = bounds
    width = max_x - min_x
    height = max_y - min_y
    span_x, span_y = profile_span_mm(outer)
    if max_side_mm is None:
        max_side_mm = max(8.0, min(40.0, 0.12 * min(span_x, span_y)))
    return max(width, height) <= max_side_mm + 1e-9


def expand_rect_hole_one_side(
    hole: Primitive,
    extra_mm: float,
    panel_x: float,
    panel_y: float,
) -> Primitive:
    """矩形孔长、宽各加 extra_mm，增量只加在 panel_x / panel_y 指向的一侧。"""

    if extra_mm <= 0:
        return hole
    bounds = axis_aligned_rect_bounds(hole)
    if bounds is None:
        return hole
    min_x, min_y, max_x, max_y = bounds

    def grow(low: float, high: float, sign: float) -> tuple[float, float]:
        if sign < 0:
            return low - extra_mm, high
        return low, high + extra_mm

    min_x, max_x = grow(min_x, max_x, panel_x)
    min_y, max_y = grow(min_y, max_y, panel_y)
    ring = [
        (min_x, min_y),
        (max_x, min_y),
        (max_x, max_y),
        (min_x, max_y),
    ]
    return _polyline_from_ring(hole, ring)


def _rect_hole_growth_signs(
    hole: Primitive,
    bend_lines: tuple[Primitive, ...],
    outer: Primitive,
) -> tuple[float, float]:
    bounds = axis_aligned_rect_bounds(hole)
    if bounds is None:
        return 1.0, 1.0
    cx = (bounds[0] + bounds[2]) / 2.0
    cy = (bounds[1] + bounds[3]) / 2.0
    sign_x = _panel_sign_from_bends("x", cx, cy, bend_lines)
    sign_y = _panel_sign_from_bends("y", cx, cy, bend_lines)
    outer_bounds = primitive_bounds(outer)
    part_x = (outer_bounds[0] + outer_bounds[2]) / 2.0
    part_y = (outer_bounds[1] + outer_bounds[3]) / 2.0
    if sign_x is None:
        sign_x = 1.0 if part_x >= cx else -1.0
    if sign_y is None:
        sign_y = 1.0 if part_y >= cy else -1.0
    return sign_x, sign_y


def apply_rectangular_relief_expansion(
    profile: Primitive,
    hole_profiles: tuple[tuple[Primitive, tuple[tuple[float, float], ...]], ...],
    relief_step: int,
    bend_lines: tuple[Primitive, ...] = (),
) -> tuple[
    Primitive,
    tuple[tuple[Primitive, tuple[tuple[float, float], ...]], ...],
    int,
]:
    """按级别扩大外轮廓矩形槽与小型矩形内孔。返回 (轮廓, 孔, 改动计数)。"""

    if relief_step <= 0:
        return profile, hole_profiles, 0
    extra = rect_relief_extra_mm(relief_step)
    expanded_profile = expand_rectangular_relief_notches(
        profile,
        extra,
        bend_lines=bend_lines,
    )
    changed = 0 if expanded_profile is profile else 1
    # 顶点坐标变化才算改动
    if expanded_profile.points != profile.points:
        changed = 1
        profile = expanded_profile
    else:
        profile = expanded_profile

    new_holes: list[tuple[Primitive, tuple[tuple[float, float], ...]]] = []
    for hole, hole_points in hole_profiles:
        if is_small_rectangular_relief_hole(hole, profile):
            notch = convert_border_hole_to_notch(profile, hole, grow=extra)
            if notch is not None:
                # 贴边槽孔转成外轮廓缺口，并从孔列表删除该孔。
                profile = notch
                changed += 1
                continue
            sign_x, sign_y = _rect_hole_growth_signs(hole, bend_lines, profile)
            grown = expand_rect_hole_one_side(hole, extra, sign_x, sign_y)
            if grown.points != hole.points:
                changed += 1
                ring = _profile_ring_points(grown)
                new_holes.append((grown, tuple(ring)))
                continue
        new_holes.append((hole, hole_points))
    return profile, tuple(new_holes), changed


# 补槽不预开固定长度。每次失败只在向上、向内各加一点点。
RELIEF_FLANGE_BITE_MM = 0.2


def relief_cut_extents_mm(relief_step: int) -> tuple[float, float]:
    """返回这一级的 (向上, 向内)。两个方向同一小增量，不按板厚换算。"""

    extra = rect_relief_extra_mm(relief_step)
    return extra, extra


def minimal_relief_width_mm(thickness_mm: float) -> float:
    """工艺槽宽 k≥t（五金厂局部弯曲），同时不低于 SendCutSend 的 0.5t 下限。"""

    return max(float(thickness_mm), 0.5)


def minimal_relief_depth_past_centerline_mm(
    thickness_mm: float,
    radius_mm: float,
) -> float:
    """自折弯中心线朝板面的最小深度：t + R + 0.5mm（SendCutSend，从折弯线量）。

    现场约 3.4mm 越过中心线才折得成，和 t=2、R≈1 时的这个公式是同一量级。
    初槽用公式，不把 3.4 写成固定开口，薄板才不会一口开太大；
    折不成再按 step 只朝板面加深。
    """

    return float(thickness_mm) + float(radius_mm) + 0.5


def _interior_run_mm(
    profile: Primitive,
    origin: tuple[float, float],
    direction: tuple[float, float],
    *,
    limit_mm: float = 400.0,
) -> float:
    step = 0.5
    distance = 0.0
    bounds = primitive_bounds(profile)
    while distance < limit_mm:
        distance += step
        point = (
            origin[0] + direction[0] * distance,
            origin[1] + direction[1] * distance,
        )
        if not _point_in_profile(point, profile, bounds):
            return max(0.0, distance - step)
    return limit_mm


def _panel_axis_signs(
    profile: Primitive,
    point: tuple[float, float],
) -> tuple[float, float]:
    """从交点往 ±X / ±Y 看，材料更厚的一侧是板面。"""

    positive_x = _interior_run_mm(profile, point, (1.0, 0.0))
    negative_x = _interior_run_mm(profile, point, (-1.0, 0.0))
    positive_y = _interior_run_mm(profile, point, (0.0, 1.0))
    negative_y = _interior_run_mm(profile, point, (0.0, -1.0))
    sign_x = 1.0 if positive_x >= negative_x else -1.0
    sign_y = 1.0 if positive_y >= negative_y else -1.0
    return sign_x, sign_y


def _rectangle_hole(
    min_x: float,
    min_y: float,
    max_x: float,
    max_y: float,
) -> tuple[Primitive, tuple[tuple[float, float], ...]]:
    ring = (
        (min_x, min_y),
        (max_x, min_y),
        (max_x, max_y),
        (min_x, max_y),
        (min_x, min_y),
    )
    segments = tuple(SketchSegment(start, end) for start, end in zip(ring, ring[1:]))
    hole = Primitive(ring, True, False, "RELIEF", "LINE_LOOP", segments)
    return hole, ring


def ensure_intersection_reliefs(
    profile: Primitive,
    hole_profiles: tuple[tuple[Primitive, tuple[tuple[float, float], ...]], ...],
    bend_lines: tuple[Primitive, ...],
    thickness_mm: float,
    radius_mm: float,
    *,
    relief_step: int = 0,
) -> tuple[
    Primitive,
    tuple[tuple[Primitive, tuple[tuple[float, float], ...]], ...],
    int,
]:
    """交汇折弯附近没有释放槽时，补一块直角矩形槽，不斜切。

    step0 不新开槽。之后向上、向内各加本级的一小段（先 1.0mm，再每次 0.5mm），
    两个方向都加，不单走一边，也不一次开成固定长槽。已有槽则不动。
    """

    del radius_mm
    if len(bend_lines) < 2:
        return profile, hole_profiles, 0
    upward_mm, inward_mm = relief_cut_extents_mm(relief_step)
    if upward_mm <= 0 or inward_mm <= 0:
        return profile, hole_profiles, 0
    reach = max(3.0, min(max(upward_mm, inward_mm), 8.0))
    bounds = primitive_bounds(profile)
    added: list[tuple[Primitive, tuple[tuple[float, float], ...]]] = []
    seen: list[tuple[float, float]] = []
    for first_index, first in enumerate(bend_lines):
        for second in bend_lines[first_index + 1 :]:
            point = _line_intersection(first, second)
            if point is None:
                continue
            if not _point_in_profile(point, profile, bounds):
                continue
            near_limit = max(6.0, thickness_mm * 3.0)
            if (
                _distance_point_to_segment(point, first.points[0], first.points[-1])
                > near_limit
                or _distance_point_to_segment(point, second.points[0], second.points[-1])
                > near_limit
            ):
                continue
            if any(math.dist(point, previous) <= reach for previous in seen):
                continue
            sign_x, sign_y = _panel_axis_signs(profile, point)
            # 向上、向内都挖，不把增量只留给材料更长的那一侧。
            extent_x = upward_mm
            extent_y = inward_mm
            min_x = point[0] if sign_x > 0 else point[0] - extent_x
            max_x = point[0] + extent_x if sign_x > 0 else point[0]
            min_y = point[1] if sign_y > 0 else point[1] - extent_y
            max_y = point[1] + extent_y if sign_y > 0 else point[1]
            center = ((min_x + max_x) / 2.0, (min_y + max_y) / 2.0)
            if not _point_in_profile(center, profile, bounds):
                continue
            if any(math.dist(point, vertex) <= reach for vertex in profile.points):
                continue
            blocked = False
            for hole, _hole_points in (*hole_profiles, *added):
                hole_bounds = primitive_bounds(hole)
                if _point_in_profile(point, hole, hole_bounds) or _point_in_profile(
                    center, hole, hole_bounds
                ):
                    blocked = True
                    break
                if any(math.dist(point, vertex) <= reach for vertex in hole.points):
                    blocked = True
                    break
            if blocked:
                continue
            notch_profile = _border_intersection_notch(
                profile, point, extent_x, extent_y
            )
            if notch_profile is not None:
                # 距板边 ≤2mm：补槽跨过端头从板边伸进材料，直接开成缺口，
                # 不再留与外环相交的内孔。找不到可贴的直角边才退回板内孔。
                profile = notch_profile
                bounds = primitive_bounds(profile)
                seen.append(point)
                continue
            added.append(_rectangle_hole(min_x, min_y, max_x, max_y))
            seen.append(point)
    if not added:
        return profile, hole_profiles, 0
    return profile, hole_profiles + tuple(added), len(added)


def suggest_relief_cutouts(
    analysis: DrawingAnalysis,
    profiles: tuple[Primitive, ...],
    outer_profile_index: int,
    bend_indices: Iterable[int],
    thickness_mm: float,
    relief_step: int,
) -> tuple[ReliefCutout, ...]:
    """建议折弯交点 / 端点附近的圆形释放槽（仅预览用；生成路径不调用）。

    ``relief_step``：
    - 0：不预开圆孔（step0 只用图纸原槽）；
    - 1..N：圆孔半径 = max(已有圆孔, 0) + step×0.5×t，不与矩形扩槽叠加进实体。
    """

    indices = tuple(dict.fromkeys(int(index) for index in bend_indices))
    if not indices:
        raise ValueError("无法自动定位释放槽：没有可用的折弯线。")
    if relief_step < 0:
        raise ValueError("释放槽重试级数不能为负数。")
    if not 0 <= outer_profile_index < len(profiles):
        raise ValueError("外轮廓索引无效。")

    # step0：原槽，不建议额外圆孔。
    if relief_step <= 0:
        return ()

    minimum_separation = max(thickness_mm * 0.5, 0.05)
    outer_profile = profiles[outer_profile_index]
    outer_bounds = primitive_bounds(outer_profile)
    centers: list[tuple[float, float]] = []
    # 优先：折弯线延长交点（拐角最需要释放）。
    for first_position, first_index in enumerate(indices):
        for second_index in indices[first_position + 1 :]:
            intersection = _line_intersection(
                analysis.bend_lines[first_index],
                analysis.bend_lines[second_index],
            )
            if intersection is None:
                continue
            if not _point_in_profile(intersection, outer_profile, outer_bounds):
                continue
            if all(
                math.dist(intersection, center) > minimum_separation
                for center in centers
            ):
                centers.append(intersection)
    # 再补：每条折弯与外轮廓的端部交点（即使有交点，端部也常需要槽）。
    for index in indices:
        for point in _bend_outline_ends(
            analysis.bend_lines[index],
            outer_profile,
        ):
            if not _point_in_profile(point, outer_profile, outer_bounds):
                # 交点在边上时 _point_in_profile 视为 True；若仍在外则内偏一点。
                continue
            if all(
                math.dist(point, center) > minimum_separation
                for center in centers
            ):
                centers.append(point)
    if not centers:
        listed_bends = ", ".join(str(index + 1) for index in indices)
        raise ValueError(
            f"第 {listed_bends} 条折弯线既没有可用交点，也没有落在外轮廓上，"
            "无法自动定位释放槽；请手动检查折弯线是否穿过零件。"
        )

    cutouts: list[ReliefCutout] = []
    existing_hole_indices = contained_hole_indices(
        profiles,
        outer_profile_index,
    )
    for center in centers:
        matched_profile: int | None = None
        base_radius = 0.0
        for profile_index in existing_hole_indices:
            profile = profiles[profile_index]
            if profile.kind != "CIRCLE":
                continue
            circle_center = profile.circle_center
            circle_radius = profile.circle_radius
            if circle_center is None or circle_radius is None:
                continue
            match_tolerance = max(thickness_mm * 2.0, 0.1)
            if math.dist(circle_center, center) <= match_tolerance:
                matched_profile = profile_index
                base_radius = circle_radius
                break
        # step0 → 0.5t；之后每级 +0.5t。已有圆孔则在其上继续扩大。
        # 仅 retry 时建议圆孔：半径 = 已有圆孔(若有) + step×0.5t；不强制预开 0.5t。
        radius = base_radius + relief_step * (thickness_mm * 0.5)
        if radius <= 1e-9:
            radius = thickness_mm * 0.5
        cutouts.append(ReliefCutout(center, radius, matched_profile))
    return tuple(cutouts)


def _point_in_profile(
    point: tuple[float, float],
    profile: Primitive,
    bounds: tuple[float, float, float, float] | None = None,
) -> bool:
    x, y = point
    vertices = profile.points
    if len(vertices) < 4:
        return False
    if bounds is None:
        bounds = (
            min(vertex[0] for vertex in vertices),
            min(vertex[1] for vertex in vertices),
            max(vertex[0] for vertex in vertices),
            max(vertex[1] for vertex in vertices),
        )
    min_x, min_y, max_x, max_y = bounds
    if x < min_x or x > max_x or y < min_y or y > max_y:
        return False

    inside = False
    for start, end in zip(vertices, vertices[1:]):
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        cross = (x - start[0]) * dy - (y - start[1]) * dx
        if abs(cross) <= 1e-7 and (
            min(start[0], end[0]) - 1e-7 <= x <= max(start[0], end[0]) + 1e-7
            and min(start[1], end[1]) - 1e-7 <= y <= max(start[1], end[1]) + 1e-7
        ):
            return True
        if (start[1] > y) != (end[1] > y):
            crossing_x = start[0] + (y - start[1]) * dx / dy
            if x < crossing_x:
                inside = not inside
    return inside


def profile_bend_indices(
    profile: Primitive,
    bends: Iterable[Primitive],
    holes: Iterable[Primitive] = (),
) -> tuple[int, ...]:
    """折弯线中点落在外轮廓内；剔除落在内孔里的短线（孔中心十字线）。"""
    if not profile.closed:
        return ()
    hole_list = [
        (
            hole,
            (
                min(point[0] for point in hole.points),
                min(point[1] for point in hole.points),
                max(point[0] for point in hole.points),
                max(point[1] for point in hole.points),
            ),
        )
        for hole in holes
        if hole.closed and hole.points
    ]
    bounds = (
        min(point[0] for point in profile.points),
        min(point[1] for point in profile.points),
        max(point[0] for point in profile.points),
        max(point[1] for point in profile.points),
    )
    matches: list[int] = []
    for index, bend in enumerate(bends):
        midpoint = (
            (bend.points[0][0] + bend.points[-1][0]) / 2,
            (bend.points[0][1] + bend.points[-1][1]) / 2,
        )
        if (
            bounds[0] <= midpoint[0] <= bounds[2]
            and bounds[1] <= midpoint[1] <= bounds[3]
            and _point_in_profile(midpoint, profile, bounds)
            and not any(
                hb[0] <= midpoint[0] <= hb[2]
                and hb[1] <= midpoint[1] <= hb[3]
                and _point_in_profile(midpoint, hole, hb)
                # 只剔孔中心十字：线长不超过孔尺寸 1.5 倍 + 6 mm；
                # 真正的折弯线贯穿板面，远长于孔。
                and math.dist(bend.points[0], bend.points[-1])
                <= 1.5 * max(hb[2] - hb[0], hb[3] - hb[1]) + 6.0
                for hole, hb in hole_list
            )
        ):
            matches.append(index)
    return tuple(matches)


def _bends_are_roughly_parallel(
    first: Primitive,
    second: Primitive,
    *,
    angle_tol_deg: float = 12.0,
) -> bool:
    dx1 = first.points[-1][0] - first.points[0][0]
    dy1 = first.points[-1][1] - first.points[0][1]
    dx2 = second.points[-1][0] - second.points[0][0]
    dy2 = second.points[-1][1] - second.points[0][1]
    len1 = math.hypot(dx1, dy1)
    len2 = math.hypot(dx2, dy2)
    if len1 <= 1e-12 or len2 <= 1e-12:
        return False
    cos_abs = abs((dx1 * dx2 + dy1 * dy2) / (len1 * len2))
    cos_abs = min(1.0, cos_abs)
    return math.degrees(math.acos(cos_abs)) <= angle_tol_deg


def _bends_are_collinear(
    first: Primitive,
    second: Primitive,
    *,
    distance_tol_mm: float = 1.0,
) -> bool:
    """两条折弯线落在同一条直线上。SolidWorks 同草图里放两条共线折弯会报错。"""

    if not _bends_are_roughly_parallel(first, second, angle_tol_deg=3.0):
        return False
    start, end = first.points[0], first.points[-1]
    length = math.hypot(end[0] - start[0], end[1] - start[1])
    if length <= 1e-9:
        return False

    def _offset(point: tuple[float, float]) -> float:
        return abs(
            (point[0] - start[0]) * (end[1] - start[1])
            - (point[1] - start[1]) * (end[0] - start[0])
        ) / length

    return all(_offset(point) <= distance_tol_mm for point in (second.points[0], second.points[-1]))


def collapse_collinear_bend_indices(
    analysis: DrawingAnalysis,
    bend_indices: tuple[int, ...],
) -> tuple[int, ...]:
    """共线的折弯线只留第一条进折弯特征草图。识别结果本身不合并、不接长。"""

    kept: list[int] = []
    for index in bend_indices:
        bend = analysis.bend_lines[index]
        if any(
            _bends_are_collinear(bend, analysis.bend_lines[previous])
            for previous in kept
        ):
            continue
        kept.append(index)
    return tuple(kept)


def _partition_bend_groups(
    analysis: DrawingAnalysis,
    bend_indices: tuple[int, ...],
) -> list[tuple[int, ...]]:
    """把折弯线分成「近似平行」组：同组可共草图一次折，交叉组再分批。"""

    remaining = list(bend_indices)
    groups: list[tuple[int, ...]] = []
    while remaining:
        seed = remaining.pop(0)
        group = [seed]
        still: list[int] = []
        for index in remaining:
            if _bends_are_roughly_parallel(
                analysis.bend_lines[seed], analysis.bend_lines[index]
            ):
                group.append(index)
            else:
                still.append(index)
        remaining = still
        groups.append(tuple(group))
    return groups


# 只让折弯特征草图穿出板边。识别结果和「折弯线_手折参考」仍用原长。
BEND_FEATURE_PIERCE_MM = 1.0


def _extended_bend_segment(
    bend: Primitive,
    outer_profile: Primitive,
    thickness_mm: float,
) -> tuple[tuple[float, float], tuple[float, float]]:
    """原样返回折弯线端点。识别和手折参考草图不延长。"""

    del outer_profile, thickness_mm
    start, end = bend.points[0], bend.points[-1]
    if math.dist(start, end) <= 1e-7:
        raise ValueError("折弯线长度为零。")
    return start, end


def _bend_feature_segment(
    bend: Primitive,
    outer_profile: Primitive,
    thickness_mm: float,
) -> tuple[tuple[float, float], tuple[float, float]]:
    """折弯特征草图用的线段：沿原方向穿出外轮廓一点点。

    SolidWorks 草图折弯要求折弯线穿过板面。图上的红线往往只是短标记，
    原长放进特征草图时折弯会被拒绝。这里只在特征草图里延伸到轮廓交点，
    每端再探出约 1mm，不改识别结果，也不把线无限拉长。
    """

    start, end = _extended_bend_segment(bend, outer_profile, thickness_mm)
    span = _bend_feature_outline_span(bend, outer_profile)
    if span is None:
        return start, end
    hits = span
    length = math.dist(start, end)
    unit_x = (end[0] - start[0]) / length
    unit_y = (end[1] - start[1]) / length
    hit_a, hit_b = hits[0], hits[1]
    if (hit_b[0] - hit_a[0]) * unit_x + (hit_b[1] - hit_a[1]) * unit_y < 0:
        hit_a, hit_b = hit_b, hit_a
    pierce = max(BEND_FEATURE_PIERCE_MM, 0.25 * thickness_mm)
    return (
        (hit_a[0] - unit_x * pierce, hit_a[1] - unit_y * pierce),
        (hit_b[0] + unit_x * pierce, hit_b[1] + unit_y * pierce),
    )


def _same_feature_span(
    first: tuple[tuple[float, float], tuple[float, float]],
    second: tuple[tuple[float, float], tuple[float, float]],
    tolerance: float = 0.3,
) -> bool:
    a0, a1 = first
    b0, b1 = second
    forward = math.dist(a0, b0) <= tolerance and math.dist(a1, b1) <= tolerance
    reverse = math.dist(a0, b1) <= tolerance and math.dist(a1, b0) <= tolerance
    return forward or reverse


ARTIFACT_LOOP_MAX_EDGE_MM = 2.0
ARTIFACT_LOOP_MAX_AREA_MM2 = 0.6


def _closed_loop_metrics(
    profile: Primitive,
) -> tuple[float, float] | None:
    """闭环的最大边长与面积（mm / mm²）；开环或不足三点时返回 None。"""

    if not profile.closed:
        return None
    ring = _profile_ring_points(profile)
    if len(ring) < 3:
        return None
    edges = list(zip(ring, ring[1:] + ring[:1]))
    max_edge = max(math.dist(start, end) for start, end in edges)
    area = abs(
        sum(start[0] * end[1] - end[0] * start[1] for start, end in edges)
    ) / 2.0
    return max_edge, area


def _is_drawing_artifact_loop(profile: Primitive) -> bool:
    """尺寸箭头之类的图纸标注残留：闭环最大边 ≤2 mm 且面积 ≤0.6 mm²。

    Φ2 孔面积 3.14 mm²，3×3 mm 方孔最大边 3 mm，两者都照常切。
    """

    metrics = _closed_loop_metrics(profile)
    if metrics is None:
        return False
    max_edge, area = metrics
    return (
        max_edge <= ARTIFACT_LOOP_MAX_EDGE_MM
        and area <= ARTIFACT_LOOP_MAX_AREA_MM2
    )


BORDER_NOTCH_MIN_COVERAGE = 0.8
BORDER_NOTCH_MAX_GAP_MM = 0.75
BORDER_NOTCH_EDGE_TOL_MM = 1e-6
BORDER_RELIEF_MAX_DISTANCE_MM = 2.0


def _ring_orientation_ccw(ring: list[tuple[float, float]]) -> bool:
    area = 0.0
    for index in range(len(ring)):
        x1, y1 = ring[index]
        x2, y2 = ring[(index + 1) % len(ring)]
        area += x1 * y2 - x2 * y1
    return area > 0


def _border_edge_candidates(
    profile: Primitive,
) -> tuple[
    tuple[int, tuple[float, float], tuple[float, float], tuple[float, float], float],
    ...,
]:
    """外轮廓的轴对齐边：(边序号, 起点, 单位方向, 内法向, 边长)。"""

    ring = _profile_ring_points(profile)
    if len(ring) < 3:
        return ()
    ccw = _ring_orientation_ccw(ring)
    edges = []
    for index in range(len(ring)):
        start = ring[index]
        end = ring[(index + 1) % len(ring)]
        if not _is_axis_aligned_pair(start, end):
            continue
        length = math.dist(start, end)
        if length <= 1e-9:
            continue
        u = ((end[0] - start[0]) / length, (end[1] - start[1]) / length)
        normal = (-u[1], u[0]) if ccw else (u[1], -u[0])
        edges.append((index, start, u, normal, length))
    return tuple(edges)


def _cut_border_notch(
    profile: Primitive,
    edge_index: int,
    mouth_start_s: float,
    mouth_end_s: float,
    depth_mm: float,
) -> Primitive:
    """把外轮廓第 edge_index 条边挖成三边直角缺口，其余曲线段原样保留。"""

    ring = _profile_ring_points(profile)
    count = len(ring)
    if not 0 <= edge_index < count or depth_mm <= 1e-9:
        return profile
    start = ring[edge_index]
    end = ring[(edge_index + 1) % count]
    length = math.dist(start, end)
    if length <= 1e-9:
        return profile
    u = ((end[0] - start[0]) / length, (end[1] - start[1]) / length)
    normal = (-u[1], u[0]) if _ring_orientation_ccw(ring) else (u[1], -u[0])
    mouth_start = min(max(mouth_start_s, 0.0), length)
    mouth_end = min(max(mouth_end_s, 0.0), length)
    if mouth_end - mouth_start <= 1e-9:
        return profile

    def _at(along: float, depth: float) -> tuple[float, float]:
        return (
            start[0] + u[0] * along + normal[0] * depth,
            start[1] + u[1] * along + normal[1] * depth,
        )

    inserts: list[tuple[float, float]] = []
    if mouth_start > BORDER_NOTCH_EDGE_TOL_MM:
        inserts.append(_at(mouth_start, 0.0))
    inserts.append(_at(mouth_start, depth_mm))
    inserts.append(_at(mouth_end, depth_mm))
    if mouth_end < length - BORDER_NOTCH_EDGE_TOL_MM:
        inserts.append(_at(mouth_end, 0.0))
    new_ring = list(ring[: edge_index + 1]) + inserts + list(ring[edge_index + 1 :])

    if profile.curve_segments:
        rebuilt: list[SketchSegment] = []
        replaced = False
        for segment in profile.curve_segments:
            if (
                not replaced
                and segment.center is None
                and math.dist(segment.start, start) <= 1e-9
                and math.dist(segment.end, end) <= 1e-9
            ):
                chain = [start, *inserts, end]
                rebuilt.extend(
                    SketchSegment(a, b)
                    for a, b in zip(chain, chain[1:])
                    if math.dist(a, b) > 1e-12
                )
                replaced = True
                continue
            rebuilt.append(segment)
        if replaced:
            return replace(
                profile,
                points=tuple(new_ring) + (new_ring[0],),
                curve_segments=tuple(rebuilt),
            )
    return _polyline_from_ring(profile, new_ring)


def convert_border_hole_to_notch(
    outer: Primitive,
    hole: Primitive,
    grow: float = 0.0,
) -> Primitive | None:
    """贴板边的矩形槽孔 → 外轮廓缺口；不贴边或搭边不足时返回 None。

    与外环相交的内环 SolidWorks 不接受，越过板边的部分也没有材料可切，
    所以这种孔要挖成板边缺口并从孔列表删除。孔离板边只剩 ≤0.75mm 细缝
    （图纸画法/浮点误差）时先把那一侧拉伸到板边，不留悬空窄条。
    """

    if grow < 0:
        raise ValueError("缺口扩量不能为负数")
    if not outer.closed or not hole.closed:
        return None
    bounds = axis_aligned_rect_bounds(hole)
    if bounds is None:
        return None
    corners = (
        (bounds[0], bounds[1]),
        (bounds[2], bounds[1]),
        (bounds[2], bounds[3]),
        (bounds[0], bounds[3]),
    )
    best: tuple[tuple[float, float], int, float, float, float] | None = None
    for edge_index, start, u, normal, length in _border_edge_candidates(outer):
        across = tuple(
            (point[0] - start[0]) * normal[0] + (point[1] - start[1]) * normal[1]
            for point in corners
        )
        along = tuple(
            (point[0] - start[0]) * u[0] + (point[1] - start[1]) * u[1]
            for point in corners
        )
        if min(across) < -BORDER_NOTCH_EDGE_TOL_MM:
            continue  # 孔越过板边：不是贴边孔
        if min(across) > BORDER_NOTCH_MAX_GAP_MM:
            continue  # 离板边太远：仍是内孔
        span = max(along) - min(along)
        if span <= 1e-9:
            continue
        overlap = min(max(along), length) - max(min(along), 0.0)
        if overlap < BORDER_NOTCH_MIN_COVERAGE * span - 1e-9:
            continue  # 搭边不足 80%：转缺口切不干净，保持为孔
        depth = max(across) + grow
        if depth <= 1e-9:
            continue
        # 角部孔会同时贴两条边：先比搭边比例，再比实际贴合长度（缺口开在
        # 孔真正沿着走的那条边上），仍相同则按轮廓边顺序，保证结果确定。
        candidate = (
            (overlap / span, overlap),
            edge_index,
            min(along) - grow / 2.0,
            max(along) + grow / 2.0,
            depth,
        )
        if best is None or candidate[0] > best[0]:
            best = candidate
    if best is None:
        return None
    _rank, edge_index, mouth_start, mouth_end, depth = best
    notch = _cut_border_notch(outer, edge_index, mouth_start, mouth_end, depth)
    return None if notch.points == outer.points else notch


def _border_intersection_notch(
    profile: Primitive,
    point: tuple[float, float],
    extent_x: float,
    extent_y: float,
) -> Primitive | None:
    """交汇点距板边 ≤2mm 时，补槽从板边伸进材料并转成缺口。

    深度 = 到板边的距离 + 本级增量（跨过端头），宽度 = 另一轴增量，
    以交汇点为中心。找不到可贴的直角边就返回 None，退回板内孔。
    """

    best: tuple[float, int, float, float, float] | None = None
    for edge_index, start, u, normal, length in _border_edge_candidates(profile):
        across = (point[0] - start[0]) * normal[0] + (point[1] - start[1]) * normal[1]
        along = (point[0] - start[0]) * u[0] + (point[1] - start[1]) * u[1]
        if across < -BORDER_NOTCH_EDGE_TOL_MM:
            continue
        if across > BORDER_RELIEF_MAX_DISTANCE_MM:
            continue
        if not 0.0 <= along <= length:
            continue
        vertical_edge = abs(u[0]) <= 1e-12
        depth = across + (extent_x if vertical_edge else extent_y)
        width = extent_y if vertical_edge else extent_x
        if depth <= 1e-9 or width <= 1e-9:
            continue
        distance = abs(across)
        candidate = (-distance, edge_index, along - width / 2.0, along + width / 2.0, depth)
        if best is None or candidate[0] > best[0]:
            best = candidate
    if best is None:
        return None
    _rank, edge_index, mouth_start, mouth_end, depth = best
    notch = _cut_border_notch(profile, edge_index, mouth_start, mouth_end, depth)
    return None if notch.points == profile.points else notch
