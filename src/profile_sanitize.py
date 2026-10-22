from __future__ import annotations

import math
from dataclasses import replace

from cad_analyzer import Primitive, SketchSegment, primitive_bounds


Point = tuple[float, float]


def _dist(a: Point, b: Point) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _segment_intersection(
    a1: Point,
    a2: Point,
    b1: Point,
    b2: Point,
    *,
    tolerance: float,
) -> bool:
    """Proper intersection of open segments (shared endpoints ignored)."""

    def orient(p: Point, q: Point, r: Point) -> float:
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    o1 = orient(a1, a2, b1)
    o2 = orient(a1, a2, b2)
    o3 = orient(b1, b2, a1)
    o4 = orient(b1, b2, a2)
    if (
        (o1 > tolerance and o2 < -tolerance or o1 < -tolerance and o2 > tolerance)
        and (o3 > tolerance and o4 < -tolerance or o3 < -tolerance and o4 > tolerance)
    ):
        return True
    return False


def contour_self_intersects(
    points: tuple[Point, ...],
    *,
    tolerance: float = 1e-6,
) -> bool:
    if len(points) < 4:
        return False
    ring = points
    if _dist(ring[0], ring[-1]) <= tolerance:
        ring = ring[:-1]
    n = len(ring)
    if n < 4:
        return False
    edges = [(ring[i], ring[(i + 1) % n]) for i in range(n)]
    for i, (a1, a2) in enumerate(edges):
        for j, (b1, b2) in enumerate(edges):
            if j <= i + 1:
                continue
            if i == 0 and j == n - 1:
                continue
            if _segment_intersection(a1, a2, b1, b2, tolerance=tolerance):
                return True
    return False


def fit_circle_3points(
    a: Point,
    b: Point,
    c: Point,
) -> tuple[Point, float] | None:
    """三点定圆；共线时返回 None。"""

    ax, ay = a
    bx, by = b
    cx, cy = c
    d = 2.0 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) <= 1e-12:
        return None
    a2 = ax * ax + ay * ay
    b2 = bx * bx + by * by
    c2 = cx * cx + cy * cy
    ux = (a2 * (by - cy) + b2 * (cy - ay) + c2 * (ay - by)) / d
    uy = (a2 * (cx - bx) + b2 * (ax - cx) + c2 * (bx - ax)) / d
    center = (ux, uy)
    radius = _dist(center, a)
    if radius <= 1e-9:
        return None
    return center, radius


def _arc_midpoint(segment: SketchSegment) -> Point | None:
    if segment.center is None or abs(segment.sweep_angle) <= 1e-10:
        return None
    start_angle = math.atan2(
        segment.start[1] - segment.center[1],
        segment.start[0] - segment.center[0],
    )
    mid_angle = start_angle + segment.sweep_angle * 0.5
    radius = _dist(segment.center, segment.start)
    return (
        segment.center[0] + radius * math.cos(mid_angle),
        segment.center[1] + radius * math.sin(mid_angle),
    )


def _sweep_through_mid(
    center: Point,
    start: Point,
    mid: Point,
    end: Point,
) -> float:
    """从 start 经 mid 到 end 的有向圆心角（弧度，范围约 (-2π, 2π)）。"""

    def angle(point: Point) -> float:
        return math.atan2(point[1] - center[1], point[0] - center[0])

    a0 = angle(start)
    a1 = angle(mid)
    a2 = angle(end)

    def delta(from_angle: float, to_angle: float) -> float:
        value = to_angle - from_angle
        while value <= -math.pi:
            value += math.tau
        while value > math.pi:
            value -= math.tau
        return value

    first = delta(a0, a1)
    second = delta(a1, a2)
    sweep = first + second
    # 三点拟合后偶发落到反向短弧，按原扫掠方向纠正。
    if abs(sweep) < 1e-8:
        sweep = delta(a0, a2)
    return sweep


def densify_closed_profile(
    profile: Primitive,
    *,
    segments_per_arc: int = 24,
) -> Primitive:
    """把闭合轮廓上的圆弧离散成折线顶点，仅用于量包围盒等临时计算。"""

    if not profile.closed or profile.is_bend:
        return profile
    if profile.kind.upper() == "CIRCLE" and profile.circle_center and profile.circle_radius:
        cx, cy = profile.circle_center
        radius = profile.circle_radius
        count = max(segments_per_arc, 8)
        points = [
            (
                cx + radius * math.cos(math.tau * index / count),
                cy + radius * math.sin(math.tau * index / count),
            )
            for index in range(count)
        ]
        points.append(points[0])
        curves = tuple(
            SketchSegment(start, end)
            for start, end in zip(points, points[1:])
        )
        return replace(
            profile,
            points=tuple(points),
            curve_segments=curves,
            kind="LINE_LOOP",
            circle_center=None,
            circle_radius=None,
        )

    if not profile.curve_segments:
        return profile

    points: list[Point] = []
    for segment in profile.curve_segments:
        if not points:
            points.append(segment.start)
        elif _dist(points[-1], segment.start) > 1e-9:
            points.append(segment.start)

        if segment.center is None or abs(segment.sweep_angle) <= 1e-10:
            if _dist(points[-1], segment.end) > 1e-9:
                points.append(segment.end)
            continue

        radius = _dist(segment.center, segment.start)
        start_angle = math.atan2(
            segment.start[1] - segment.center[1],
            segment.start[0] - segment.center[0],
        )
        steps = max(2, int(abs(segment.sweep_angle) / math.tau * segments_per_arc + 0.5))
        for step in range(1, steps + 1):
            angle = start_angle + segment.sweep_angle * (step / steps)
            point = (
                segment.center[0] + radius * math.cos(angle),
                segment.center[1] + radius * math.sin(angle),
            )
            if _dist(points[-1], point) > 1e-9:
                points.append(point)

    if len(points) < 3:
        return profile
    if _dist(points[0], points[-1]) > 1e-9:
        points.append(points[0])
    curves = tuple(
        SketchSegment(start, end)
        for start, end in zip(points, points[1:])
        if _dist(start, end) > 1e-9
    )
    return replace(
        profile,
        points=tuple(points),
        curve_segments=curves,
        kind="LINE_LOOP",
        circle_center=None,
        circle_radius=None,
    )



def _remove_out_and_back_spikes(points: list[Point], tol: float) -> list[Point]:
    """去掉 A→B→A 尖刺（来回走的零宽凸起）。"""
    cleaned = list(points)
    if len(cleaned) >= 2 and _dist(cleaned[0], cleaned[-1]) <= tol:
        cleaned = cleaned[:-1]
    changed = True
    while changed and len(cleaned) >= 4:
        changed = False
        n = len(cleaned)
        nxt: list[Point] = []
        i = 0
        while i < n:
            a = cleaned[i]
            b = cleaned[(i + 1) % n]
            c = cleaned[(i + 2) % n]
            if _dist(a, c) <= tol and _dist(a, b) > tol:
                if not nxt or _dist(nxt[-1], a) > tol:
                    nxt.append(a)
                i += 3  # 跳过 tip 与重复的 A
                changed = True
                continue
            nxt.append(a)
            i += 1
        if len(nxt) >= 3 and _dist(nxt[0], nxt[-1]) <= tol:
            nxt.pop()
        if len(nxt) >= 3:
            cleaned = nxt
        else:
            break
    return cleaned


def _drop_out_and_back_segments(
    segments: list[SketchSegment],
    tol: float,
) -> list[SketchSegment]:
    """去掉 A→B→A 的来回线段对（零宽尖刺/双线）。

    点表里的尖刺在 ``_remove_out_and_back_spikes`` 已清掉，但原曲线段是整段
    留下的；只要这两段还在，SolidWorks 就会把草图看成两个环（真实案例：
    3625.036→3624.953→3625.036 一条 2 mm 长、0.08 mm 宽的缝）。
    """
    if len(segments) < 3:
        return segments
    kept: list[SketchSegment] = []
    removed = False
    index = 0
    while index < len(segments):
        segment = segments[index]
        if index + 1 < len(segments):
            nxt = segments[index + 1]
            if (
                _dist(segment.end, nxt.start) <= tol
                and _dist(nxt.end, segment.start) <= tol
                and _dist(segment.start, segment.end) > tol
            ):
                # 来回一趟：两段都丢，前一段的终点正好接在后一段的终点上。
                index += 2
                removed = True
                continue
        kept.append(segment)
        index += 1
    if not removed or len(kept) < 3:
        return segments
    return kept


def sanitize_closed_profile(
    profile: Primitive,
    *,
    min_edge_mm: float = 0.05,
) -> Primitive:
    """去掉重复点与过短边，重建线段，降低 SolidWorks 基体法兰失败率。"""

    if not profile.closed or profile.is_bend:
        return profile
    if not math.isfinite(min_edge_mm) or min_edge_mm <= 0:
        min_edge_mm = 0.05

    raw = list(profile.points)
    if len(raw) >= 2 and _dist(raw[0], raw[-1]) <= min_edge_mm:
        raw = raw[:-1]
    if len(raw) < 3:
        return profile

    # 1) 合并过近的连续顶点。
    cleaned: list[Point] = [raw[0]]
    for point in raw[1:]:
        if _dist(cleaned[-1], point) > min_edge_mm:
            cleaned.append(point)
    if len(cleaned) >= 2 and _dist(cleaned[0], cleaned[-1]) <= min_edge_mm:
        cleaned.pop()
    if len(cleaned) < 3:
        return profile

    # 1b) 去掉 A→B→A 尖刺（释放槽被分析器收成来回走），否则 SW 会报双环。
    cleaned = _remove_out_and_back_spikes(cleaned, max(min_edge_mm, 0.05))
    if len(cleaned) < 3:
        return profile

    # 2) 去掉几乎共线的中间点，减少碎边。
    simplified: list[Point] = []
    count = len(cleaned)
    for index, point in enumerate(cleaned):
        prev_pt = cleaned[(index - 1) % count]
        next_pt = cleaned[(index + 1) % count]
        ax, ay = point[0] - prev_pt[0], point[1] - prev_pt[1]
        bx, by = next_pt[0] - point[0], next_pt[1] - point[1]
        cross = abs(ax * by - ay * bx)
        # 面积很小且边都不长时视为毛刺/共线。
        if (
            cross <= min_edge_mm * max(_dist(prev_pt, point), _dist(point, next_pt), 1.0)
            and _dist(prev_pt, next_pt) > min_edge_mm
            and _dist(prev_pt, point) <= min_edge_mm * 8
        ):
            continue
        simplified.append(point)
    if len(simplified) < 3:
        simplified = cleaned

    # 3) 优先保留足够长的原曲线段；否则按折线重建，避免碎弧导致自交。
    kept_curves: list[SketchSegment] = []
    for segment in profile.curve_segments:
        length = _dist(segment.start, segment.end)
        if segment.center is not None and abs(segment.sweep_angle) > 1e-8:
            radius = _dist(segment.center, segment.start)
            length = max(length, abs(segment.sweep_angle) * radius)
        if length < min_edge_mm:
            continue
        kept_curves.append(segment)

    # 2b) 曲线段里的来回尖刺一并去掉，否则点表干净、草图仍多一个环。
    kept_curves = _drop_out_and_back_segments(
        kept_curves, max(min_edge_mm, 0.05)
    )

    use_curves = False
    if kept_curves:
        # 曲线段端点需能拼成与简化顶点相近的环。
        curve_points = [kept_curves[0].start]
        for segment in kept_curves:
            if _dist(curve_points[-1], segment.start) > min_edge_mm * 2:
                curve_points.append(segment.start)
            curve_points.append(segment.end)
        if _dist(curve_points[0], curve_points[-1]) <= min_edge_mm * 2:
            curve_points.pop()
        if len(curve_points) >= 3 and not contour_self_intersects(
            tuple(curve_points),
            tolerance=min_edge_mm * 0.5,
        ):
            use_curves = True
            simplified = _remove_out_and_back_spikes(
                list(curve_points), max(min_edge_mm, 0.05)
            )
            if len(simplified) < 3:
                use_curves = False
                simplified = cleaned

    if not use_curves:
        kept_curves = [
            SketchSegment(start, end)
            for start, end in zip(
                simplified,
                simplified[1:] + simplified[:1],
            )
            if _dist(start, end) > min_edge_mm
        ]

    if len(simplified) < 3 or len(kept_curves) < 3:
        return profile

    closed_points = tuple(simplified) + (simplified[0],)
    if contour_self_intersects(tuple(simplified), tolerance=min_edge_mm * 0.5):
        # 自交时退回纯折线并再清一次短边。
        kept_curves = [
            SketchSegment(start, end)
            for start, end in zip(
                simplified,
                simplified[1:] + simplified[:1],
            )
            if _dist(start, end) > min_edge_mm
        ]
        if len(kept_curves) < 3:
            return profile
        closed_points = tuple(simplified) + (simplified[0],)

    return replace(
        profile,
        points=closed_points,
        kind="LINE_LOOP" if profile.kind == "LINE_LOOP" else profile.kind,
        curve_segments=tuple(kept_curves),
        circle_center=None if profile.kind != "CIRCLE" else profile.circle_center,
        circle_radius=None if profile.kind != "CIRCLE" else profile.circle_radius,
    )


def _is_true_arc(segment: SketchSegment) -> bool:
    return segment.center is not None and abs(segment.sweep_angle) > 1e-8


def _fit_fillet_arc(
    points: list[Point],
    *,
    tolerance_mm: float,
) -> tuple[Point, float] | None:
    """从密化短边折线拟合圆角；成功返回 (center, sweep)。

    至少需要 4 个顶点（3 段短边），避免把两条长直角边误拟成大圆弧。
    """

    length = len(points)
    if length < 4:
        return None
    edge_lengths = [
        _dist(points[offset], points[offset + 1]) for offset in range(length - 1)
    ]
    if any(value <= 1e-9 for value in edge_lengths):
        return None
    mid = points[length // 2]
    fitted = fit_circle_3points(points[0], mid, points[-1])
    if fitted is None:
        return None
    center, radius = fitted
    if radius < tolerance_mm * 2:
        return None
    # 密化圆角的弦长短且均匀；夹进长直边则拒绝。
    max_edge = max(edge_lengths)
    median_edge = sorted(edge_lengths)[len(edge_lengths) // 2]
    if max_edge > max(3.0, 0.9 * radius):
        return None
    if max_edge > median_edge * 2.5 + 1e-9:
        return None
    for point in points[1:-1]:
        if abs(_dist(center, point) - radius) > tolerance_mm:
            return None
    turns: list[float] = []
    for offset in range(length - 2):
        a = points[offset]
        b = points[offset + 1]
        c = points[offset + 2]
        ab = (b[0] - a[0], b[1] - a[1])
        bc = (c[0] - b[0], c[1] - b[1])
        cross = ab[0] * bc[1] - ab[1] * bc[0]
        turns.append(cross)
    if not turns or any(value * turns[0] < -1e-12 for value in turns):
        return None
    sweep = _sweep_through_mid(center, points[0], mid, points[-1])
    # 钣金圆角多为 45°–180°；过浅的长弧多半是误拟合。
    if abs(sweep) < math.radians(25) or abs(sweep) > math.radians(185):
        return None
    return center, sweep


def _refit_closed_polyline_ring(
    ring: list[Point],
    *,
    min_points: int,
    max_points: int,
    tolerance_mm: float,
) -> list[SketchSegment] | None:
    """闭合折线环：贪心把圆角拟成单段弧（可跨首尾）。"""

    count = len(ring)
    if count < 4:
        return None
    used = [False] * count
    rebuilt: list[SketchSegment] = []
    index = 0
    guard = 0
    while guard < count * 2 and len(rebuilt) < count:
        guard += 1
        if all(used):
            break
        while used[index % count]:
            index += 1
            if index > count * 2:
                break
        start_index = index % count
        if used[start_index]:
            break
        best: tuple[int, Point, float] | None = None
        for length in range(min_points, min(max_points, count - 1) + 1):
            points = [ring[(start_index + offset) % count] for offset in range(length)]
            if any(used[(start_index + offset) % count] for offset in range(length - 1)):
                break
            fitted = _fit_fillet_arc(points, tolerance_mm=tolerance_mm)
            if fitted is None:
                continue
            center, sweep = fitted
            if best is None or length > best[0]:
                best = (length, center, sweep)
        if best is not None:
            length, center, sweep = best
            start = ring[start_index]
            end = ring[(start_index + length - 1) % count]
            rebuilt.append(SketchSegment(start, end, center, sweep))
            for offset in range(length - 1):
                used[(start_index + offset) % count] = True
            index = start_index + length - 1
            continue
        end_index = (start_index + 1) % count
        rebuilt.append(SketchSegment(ring[start_index], ring[end_index]))
        used[start_index] = True
        index = start_index + 1

    if len(rebuilt) < 3:
        return None
    if not any(_is_true_arc(segment) for segment in rebuilt):
        return None
    return rebuilt


def refit_circular_fillets(
    profile: Primitive,
    *,
    min_points: int = 4,
    max_points: int = 48,
    tolerance_mm: float = 0.15,
) -> Primitive:
    """把密化折线圆角重拟成单段真圆弧；已有圆弧段原样保留。

    图纸/缩短后常见把圆角拆成多段短直线；生成 SolidWorks 草图前应恢复为 CreateArc。
    """

    if not profile.closed or profile.is_bend:
        return profile
    if profile.kind.upper() == "CIRCLE":
        return profile

    source_segments = list(profile.curve_segments)
    if not source_segments and len(profile.points) >= 3:
        body = list(profile.points)
        if _dist(body[0], body[-1]) <= 1e-9:
            body = body[:-1]
        source_segments = [
            SketchSegment(start, end)
            for start, end in zip(body, body[1:] + body[:1])
            if _dist(start, end) > 1e-9
        ]
    if len(source_segments) < 3:
        return profile

    # 已全是真圆弧则无需处理。
    if all(_is_true_arc(segment) for segment in source_segments):
        return profile

    has_true_arc = any(_is_true_arc(segment) for segment in source_segments)
    if has_true_arc:
        # 混合轮廓：保留真弧，只对折线缝做局部重拟（不跨真弧）。
        rebuilt: list[SketchSegment] = []
        run: list[Point] = []

        def flush_open_run() -> None:
            nonlocal run
            if len(run) < 2:
                run = []
                return
            # 开环：不能用闭合环算法，逐段贪心。
            local = 0
            while local < len(run) - 1:
                best: tuple[int, Point, float] | None = None
                upper = min(max_points, len(run) - local)
                for length in range(min_points, upper + 1):
                    points = run[local : local + length]
                    fitted = _fit_fillet_arc(points, tolerance_mm=tolerance_mm)
                    if fitted is None:
                        continue
                    center, sweep = fitted
                    if best is None or length > best[0]:
                        best = (length, center, sweep)
                if best is not None:
                    length, center, sweep = best
                    rebuilt.append(
                        SketchSegment(run[local], run[local + length - 1], center, sweep)
                    )
                    local += length - 1
                    continue
                rebuilt.append(SketchSegment(run[local], run[local + 1]))
                local += 1
            run = []

        for segment in source_segments:
            if _is_true_arc(segment):
                if run and _dist(run[-1], segment.start) > 1e-9:
                    run.append(segment.start)
                flush_open_run()
                rebuilt.append(segment)
                continue
            if not run:
                run = [segment.start]
            elif _dist(run[-1], segment.start) > 1e-9:
                run.append(segment.start)
            if _dist(run[-1], segment.end) > 1e-9:
                run.append(segment.end)
        flush_open_run()
    else:
        ring: list[Point] = [source_segments[0].start]
        for segment in source_segments:
            if _dist(ring[-1], segment.start) > 1e-9:
                ring.append(segment.start)
            if _dist(ring[-1], segment.end) > 1e-9:
                ring.append(segment.end)
        if len(ring) >= 2 and _dist(ring[0], ring[-1]) <= 1e-9:
            ring = ring[:-1]
        fitted_ring = _refit_closed_polyline_ring(
            ring,
            min_points=min_points,
            max_points=max_points,
            tolerance_mm=tolerance_mm,
        )
        if fitted_ring is None:
            return profile
        rebuilt = fitted_ring

    if len(rebuilt) < 3:
        return profile
    if not any(_is_true_arc(segment) for segment in rebuilt):
        return profile

    points: list[Point] = [rebuilt[0].start]
    for segment in rebuilt:
        if _dist(points[-1], segment.start) > 1e-9:
            points.append(segment.start)
        points.append(segment.end)
    if _dist(points[0], points[-1]) > 1e-9:
        points.append(points[0])
    return replace(
        profile,
        points=tuple(points),
        curve_segments=tuple(rebuilt),
        kind="LINE_LOOP",
        circle_center=None,
        circle_radius=None,
    )


def reverse_closed_profile(profile: Primitive) -> Primitive:
    points = list(profile.points)
    if len(points) >= 2 and _dist(points[0], points[-1]) <= 1e-9:
        body = list(reversed(points[:-1]))
        points = body + [body[0]]
    else:
        points = list(reversed(points))
    curves = tuple(
        SketchSegment(
            segment.end,
            segment.start,
            segment.center,
            -segment.sweep_angle if segment.center is not None else 0.0,
        )
        for segment in reversed(profile.curve_segments)
    )
    return replace(profile, points=tuple(points), curve_segments=curves)


def profile_span_mm(profile: Primitive) -> tuple[float, float]:
    min_x, min_y, max_x, max_y = primitive_bounds(profile)
    return max_x - min_x, max_y - min_y
