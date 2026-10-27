from __future__ import annotations

import math
from dataclasses import replace

from cad_analyzer import DrawingAnalysis, Primitive, SketchSegment, primitive_bounds
from profile_sanitize import (
    _arc_midpoint,
    _sweep_through_mid,
    densify_closed_profile,
    fit_circle_3points,
    refit_circular_fillets,
    sanitize_closed_profile,
)
from profile_selection import contained_hole_indices, point_hits_profile


def _transform_point(
    point: tuple[float, float],
    *,
    center: tuple[float, float],
    scale_x: float,
    scale_y: float,
) -> tuple[float, float]:
    return (
        center[0] + (point[0] - center[0]) * scale_x,
        center[1] + (point[1] - center[1]) * scale_y,
    )


def _polyline_segments(
    points: tuple[tuple[float, float], ...],
    *,
    closed: bool,
) -> tuple[SketchSegment, ...]:
    body = list(points)
    if len(body) >= 2 and math.dist(body[0], body[-1]) <= 1e-9:
        body = body[:-1]
    if len(body) < 2:
        return ()
    pairs = (
        zip(body, body[1:] + body[:1])
        if closed
        else zip(body, body[1:])
    )
    return tuple(
        SketchSegment(start, end)
        for start, end in pairs
        if math.dist(start, end) > 1e-9
    )


def _points_from_segments(
    segments: tuple[SketchSegment, ...],
    *,
    closed: bool,
) -> tuple[tuple[float, float], ...]:
    if not segments:
        return ()
    points: list[tuple[float, float]] = [segments[0].start]
    for segment in segments:
        if math.dist(points[-1], segment.start) > 1e-9:
            points.append(segment.start)
        points.append(segment.end)
    if closed:
        if math.dist(points[0], points[-1]) > 1e-9:
            points.append(points[0])
    return tuple(points)


def _transform_arc_segment(
    segment: SketchSegment,
    *,
    center: tuple[float, float],
    scale_x: float,
    scale_y: float,
) -> SketchSegment:
    """各向异性缩放后仍输出单段真圆弧（三点拟合），禁止折线密化冒充圆角。"""

    start = _transform_point(
        segment.start, center=center, scale_x=scale_x, scale_y=scale_y
    )
    end = _transform_point(
        segment.end, center=center, scale_x=scale_x, scale_y=scale_y
    )
    mid = _arc_midpoint(segment)
    if mid is None:
        return SketchSegment(start, end)
    mid_t = _transform_point(mid, center=center, scale_x=scale_x, scale_y=scale_y)
    fitted = fit_circle_3points(start, mid_t, end)
    if fitted is None:
        return SketchSegment(start, end)
    arc_center, _radius = fitted
    sweep = _sweep_through_mid(arc_center, start, mid_t, end)
    if abs(sweep) <= 1e-10:
        return SketchSegment(start, end)
    # 与原扫掠同向；若拟合扫掠反向则翻到同侧长/短弧。
    if segment.sweep_angle * sweep < 0:
        if sweep > 0:
            sweep -= math.tau
        else:
            sweep += math.tau
    return SketchSegment(start, end, arc_center, sweep)


def _transform_primitive(
    primitive: Primitive,
    *,
    center: tuple[float, float],
    scale_x: float,
    scale_y: float,
) -> Primitive:
    anisotropic = not math.isclose(scale_x, scale_y, rel_tol=1e-9, abs_tol=1e-12)

    # 整圆在单向缩放下会变椭圆：仅整圆退回折线；轮廓圆角必须保持单段弧。
    if anisotropic and primitive.kind.upper() == "CIRCLE":
        densified = densify_closed_profile(primitive)
        points = tuple(
            _transform_point(point, center=center, scale_x=scale_x, scale_y=scale_y)
            for point in densified.points
        )
        curves = _polyline_segments(points, closed=True)
        result = replace(
            primitive,
            points=points,
            curve_segments=curves,
            circle_center=None,
            circle_radius=None,
            kind="LINE_LOOP",
        )
        return sanitize_closed_profile(result, min_edge_mm=0.05)

    if primitive.curve_segments:
        curves: list[SketchSegment] = []
        for segment in primitive.curve_segments:
            if segment.center is not None and abs(segment.sweep_angle) > 1e-10:
                if anisotropic:
                    curves.append(
                        _transform_arc_segment(
                            segment,
                            center=center,
                            scale_x=scale_x,
                            scale_y=scale_y,
                        )
                    )
                else:
                    curves.append(
                        SketchSegment(
                            _transform_point(
                                segment.start,
                                center=center,
                                scale_x=scale_x,
                                scale_y=scale_y,
                            ),
                            _transform_point(
                                segment.end,
                                center=center,
                                scale_x=scale_x,
                                scale_y=scale_y,
                            ),
                            _transform_point(
                                segment.center,
                                center=center,
                                scale_x=scale_x,
                                scale_y=scale_y,
                            ),
                            segment.sweep_angle,
                        )
                    )
            else:
                curves.append(
                    SketchSegment(
                        _transform_point(
                            segment.start,
                            center=center,
                            scale_x=scale_x,
                            scale_y=scale_y,
                        ),
                        _transform_point(
                            segment.end,
                            center=center,
                            scale_x=scale_x,
                            scale_y=scale_y,
                        ),
                    )
                )
        curve_tuple = tuple(curves)
        points = _points_from_segments(curve_tuple, closed=primitive.closed)
        if not points:
            points = tuple(
                _transform_point(
                    point, center=center, scale_x=scale_x, scale_y=scale_y
                )
                for point in primitive.points
            )
        circle_center = (
            _transform_point(
                primitive.circle_center,
                center=center,
                scale_x=scale_x,
                scale_y=scale_y,
            )
            if primitive.circle_center is not None and not anisotropic
            else None
        )
        circle_radius = (
            primitive.circle_radius * abs(scale_x)
            if primitive.circle_radius is not None and not anisotropic
            else None
        )
        result = replace(
            primitive,
            points=points,
            curve_segments=curve_tuple,
            circle_center=circle_center,
            circle_radius=circle_radius,
            kind=primitive.kind,
        )
    else:
        points = tuple(
            _transform_point(point, center=center, scale_x=scale_x, scale_y=scale_y)
            for point in primitive.points
        )
        curves = _polyline_segments(points, closed=primitive.closed)
        result = replace(
            primitive,
            points=points,
            curve_segments=curves,
            circle_center=(
                _transform_point(
                    primitive.circle_center,
                    center=center,
                    scale_x=scale_x,
                    scale_y=scale_y,
                )
                if primitive.circle_center is not None
                else None
            ),
            circle_radius=(
                primitive.circle_radius * abs(scale_x)
                if primitive.circle_radius is not None
                else None
            ),
            kind=primitive.kind,
        )

    if result.closed and not result.is_bend:
        # 缩短后清短边/重复点，但保留仍有效的单段圆弧。
        result = sanitize_closed_profile(result, min_edge_mm=0.05)
        # CAD 若把圆角拆成折线，缩短后重拟成 CreateArc，避免输出多线段。
        result = refit_circular_fillets(result)
    return result


def _point_in_profile(
    point: tuple[float, float],
    profile: Primitive,
) -> bool:
    hits, _distance = point_hits_profile(point, profile, edge_tolerance=1e-6)
    return hits


def _bend_indices_for_profile(
    profile: Primitive,
    bend_lines: tuple[Primitive, ...],
) -> tuple[int, ...]:
    min_x, min_y, max_x, max_y = primitive_bounds(profile)
    selected: list[int] = []
    for index, bend in enumerate(bend_lines):
        mid = (
            (bend.points[0][0] + bend.points[-1][0]) / 2,
            (bend.points[0][1] + bend.points[-1][1]) / 2,
        )
        if not (min_x <= mid[0] <= max_x and min_y <= mid[1] <= max_y):
            continue
        if _point_in_profile(mid, profile):
            selected.append(index)
    return tuple(selected)


def _primitive_midpoint(primitive: Primitive) -> tuple[float, float] | None:
    if primitive.circle_center is not None:
        return primitive.circle_center
    if not primitive.points:
        return None
    return (
        sum(point[0] for point in primitive.points) / len(primitive.points),
        sum(point[1] for point in primitive.points) / len(primitive.points),
    )


def _hole_reference_point(primitive: Primitive) -> tuple[float, float] | None:
    """孔/槽的参考点（圆心或长圆孔槽心），用于缩放时移动位置。

    圆孔用圆心；长圆孔用包围盒中心（槽心）。非独立圆孔或长圆孔返回 None，
    表示「保持规格」暂不支持该孔型。
    """
    if primitive.kind.upper() == "CIRCLE" and primitive.circle_center is not None:
        return primitive.circle_center
    if _looks_like_obround(primitive):
        min_x, min_y, max_x, max_y = primitive_bounds(primitive)
        return ((min_x + max_x) / 2.0, (min_y + max_y) / 2.0)
    return None


def _looks_like_obround(primitive: Primitive) -> bool:
    """长圆孔（槽）：闭合轮廓，由两条平行直边 + 两端半圆弧组成。

    判定为「近似长圆孔」：闭合 LINE_LOOP，且既有直线段又有圆弧段，
    且非整圆（整圆是 CIRCLE kind，已单独处理）。
    """
    if not primitive.closed or primitive.kind.upper() != "LINE_LOOP":
        return False
    if primitive.circle_center is not None:
        return False
    segments = primitive.curve_segments
    if len(segments) < 3:
        return False
    has_line = any(seg.center is None for seg in segments)
    has_arc = any(seg.center is not None for seg in segments)
    return has_line and has_arc


def _translate_primitive(
    primitive: Primitive,
    dx: float,
    dy: float,
) -> Primitive:
    """整体平移图元，尺寸与形状完全不变。"""
    move = lambda p: (p[0] + dx, p[1] + dy)
    segments = tuple(
        SketchSegment(
            move(seg.start),
            move(seg.end),
            move(seg.center) if seg.center is not None else None,
            seg.sweep_angle,
        )
        for seg in primitive.curve_segments
    )
    return replace(
        primitive,
        points=tuple(move(p) for p in primitive.points),
        curve_segments=segments,
        circle_center=(
            move(primitive.circle_center)
            if primitive.circle_center is not None
            else None
        ),
    )


def _hole_safe_inside(hole: Primitive, outer: Primitive) -> bool:
    """保持尺寸平移后的孔，其采样点都必须落在外轮廓内，否则越界。"""
    if hole.circle_center is not None and hole.circle_radius is not None:
        x, y = hole.circle_center
        r = hole.circle_radius
        return all(
            _point_in_profile(
                (x + r * math.cos(t * math.tau / 32), y + r * math.sin(t * math.tau / 32)),
                outer,
            )
            for t in range(32)
        )
    samples = hole.points
    if len(samples) >= 2 and samples[0] == samples[-1]:
        samples = samples[:-1]
    return all(_point_in_profile(p, outer) for p in samples)


def _holes_overlap(a: Primitive, b: Primitive) -> bool:
    """两个保持尺寸的孔是否重叠（包围盒 + 中心距粗判）。"""
    a_min_x, a_min_y, a_max_x, a_max_y = primitive_bounds(a)
    b_min_x, b_min_y, b_max_x, b_max_y = primitive_bounds(b)
    if a_max_x < b_min_x or b_max_x < a_min_x or a_max_y < b_min_y or b_max_y < a_min_y:
        return False
    ac = _hole_reference_point(a)
    bc = _hole_reference_point(b)
    if ac is None or bc is None:
        # 无法精确判定时，包围盒相交即视为可能重叠，保守阻断。
        return True
    dist = math.dist(ac, bc)
    a_radius = max(a_max_x - a_min_x, a_max_y - a_min_y) / 2.0
    b_radius = max(b_max_x - b_min_x, b_max_y - b_min_y) / 2.0
    return dist <= a_radius + b_radius


def _primitive_inside_outer(
    primitive: Primitive,
    outer: Primitive,
    *,
    outer_bounds: tuple[float, float, float, float],
) -> bool:
    """判断图元是否属于所选外轮廓内的孔/槽/边线，缩短时需同步变换。"""

    if primitive.is_bend:
        return False
    mid = _primitive_midpoint(primitive)
    if mid is None:
        return False
    min_x, min_y, max_x, max_y = outer_bounds
    pad = max(max_x - min_x, max_y - min_y, 1.0) * 0.002
    if not (
        min_x - pad <= mid[0] <= max_x + pad
        and min_y - pad <= mid[1] <= max_y + pad
    ):
        return False
    if _point_in_profile(mid, outer):
        return True
    hits, distance = point_hits_profile(
        mid,
        outer,
        edge_tolerance=max(pad, 0.25),
    )
    return hits and distance <= max(pad, 0.25)


def resize_profile_dimensions(
    analysis: DrawingAnalysis,
    profile_index: int,
    *,
    width_mm: float | None = None,
    height_mm: float | None = None,
    preserve_circle_holes: bool = False,
) -> DrawingAnalysis:
    """按包围盒一键改所选轮廓的长度（X）或宽度（Y）。

    同步缩放该轮廓内的折弯线、内部闭合切除轮廓，以及构成孔/槽的原始线段。
    单向缩短时：用离散副本只量包围盒；输出轮廓的圆角仍保持单段真圆弧
    （三点拟合），避免折线密化造成「多个圆角」。
    """

    if not 0 <= profile_index < len(analysis.profiles):
        raise ValueError("轮廓编号无效。")
    if width_mm is None and height_mm is None:
        raise ValueError("请至少填写新的长度或宽度。")

    profile = analysis.profiles[profile_index]
    # 离散副本仅用于量包围盒，不写回结果。
    densified_outer = densify_closed_profile(profile)
    min_x, min_y, max_x, max_y = primitive_bounds(densified_outer)
    old_width = max_x - min_x
    old_height = max_y - min_y
    if old_width <= 1e-9 or old_height <= 1e-9:
        raise ValueError("当前轮廓尺寸过小，无法调整。")

    if width_mm is not None:
        if not math.isfinite(width_mm) or width_mm <= 0:
            raise ValueError("长度必须是大于 0 的有限数值。")
        scale_x = width_mm / old_width
    else:
        scale_x = 1.0
    if height_mm is not None:
        if not math.isfinite(height_mm) or height_mm <= 0:
            raise ValueError("宽度必须是大于 0 的有限数值。")
        scale_y = height_mm / old_height
    else:
        scale_y = 1.0

    if math.isclose(scale_x, 1.0, abs_tol=1e-12) and math.isclose(
        scale_y, 1.0, abs_tol=1e-12
    ):
        return analysis

    center = ((min_x + max_x) / 2.0, (min_y + max_y) / 2.0)
    hole_indices = set(contained_hole_indices(analysis.profiles, profile_index))
    # Use the same semantic bend/mark classification as single and batch export.
    # A classifier error propagates: never silently guess marking or bending.
    from batch_export import part_bend_indices
    bend_indices = set(part_bend_indices(analysis, profile_index))
    if preserve_circle_holes:
        if bend_indices:
            raise ValueError('孔径保持不变暂不支持带折弯线的零件')
        unsupported = [
            i
            for i in hole_indices
            if _hole_reference_point(analysis.profiles[i]) is None
        ]
        if unsupported:
            raise ValueError(
                '孔径保持不变目前仅支持独立圆孔和长圆孔，其他孔型需另行复核'
            )
    outer_bounds = (min_x, min_y, max_x, max_y)

    target_profiles = {profile_index} | hole_indices
    # 先把 CAD 折线圆角重拟成真弧，再变换；单向缩放才能走三点重拟而不是越拉越歪的折线。
    prepared_profiles = {
        profile_index: refit_circular_fillets(profile),
        **{
            index: refit_circular_fillets(analysis.profiles[index])
            for index in hole_indices
        },
    }
    prepared_bends = {
        index: analysis.bend_lines[index] for index in bend_indices
    }

    def _apply_scales(
        sx: float,
        sy: float,
        sources: dict[int, Primitive],
    ) -> dict[int, Primitive]:
        return {
            index: _transform_primitive(
                source,
                center=center,
                scale_x=sx,
                scale_y=sy,
            )
            for index, source in sources.items()
        }

    # 圆弧三点重拟后包围盒相对线性缩放略有非线性；迭代校正到目标长宽。
    for _ in range(5):
        transformed_profiles = _apply_scales(scale_x, scale_y, prepared_profiles)
        densified_result = densify_closed_profile(
            transformed_profiles[profile_index]
        )
        res_min_x, res_min_y, res_max_x, res_max_y = primitive_bounds(
            densified_result
        )
        actual_width = res_max_x - res_min_x
        actual_height = res_max_y - res_min_y
        corr_x = 1.0
        corr_y = 1.0
        if width_mm is not None and actual_width > 1e-9:
            corr_x = width_mm / actual_width
        if height_mm is not None and actual_height > 1e-9:
            corr_y = height_mm / actual_height
        if math.isclose(corr_x, 1.0, abs_tol=1e-6) and math.isclose(
            corr_y, 1.0, abs_tol=1e-6
        ):
            break
        scale_x *= corr_x
        scale_y *= corr_y

    transformed_profiles = _apply_scales(scale_x, scale_y, prepared_profiles)
    if preserve_circle_holes:
        # 保持孔/槽规格：只把孔心（圆孔圆心 / 长圆孔槽心）按比例移动到新位置，
        # 孔/槽本身的尺寸（孔径、槽宽、槽长）保持不变。
        def translate_hole(index):
            hole = analysis.profiles[index]
            ref = _hole_reference_point(hole)
            new_ref = _transform_point(
                ref, center=center, scale_x=scale_x, scale_y=scale_y
            )
            dx, dy = new_ref[0] - ref[0], new_ref[1] - ref[1]
            return _translate_primitive(hole, dx, dy)

        transformed_profiles.update(
            {i: translate_hole(i) for i in hole_indices}
        )
        outer = transformed_profiles[profile_index]
        kept_holes = [transformed_profiles[i] for i in hole_indices]
        for hole in kept_holes:
            if not _hole_safe_inside(hole, outer):
                raise ValueError('保持孔规格后孔超出零件轮廓，禁止生成')
        for i, a in enumerate(kept_holes):
            for b in kept_holes[i + 1:]:
                if _holes_overlap(a, b):
                    raise ValueError('保持孔规格后孔发生重叠，禁止生成')
    transformed_bends = _apply_scales(scale_x, scale_y, prepared_bends)

    new_profiles = tuple(
        transformed_profiles.get(index, profile_item)
        for index, profile_item in enumerate(analysis.profiles)
    )
    new_bends = tuple(
        transformed_bends.get(index, bend)
        for index, bend in enumerate(analysis.bend_lines)
    )

    id_map = {
        id(analysis.profiles[index]): transformed_profiles[index]
        for index in transformed_profiles
    }
    id_map.update(
        {
            id(analysis.bend_lines[index]): transformed_bends[index]
            for index in transformed_bends
        }
    )

    new_primitives_list: list[Primitive] = []
    for primitive in analysis.primitives:
        mapped = id_map.get(id(primitive))
        if mapped is not None:
            new_primitives_list.append(mapped)
            continue
        if _primitive_inside_outer(
            primitive, densified_outer, outer_bounds=outer_bounds
        ):
            new_primitives_list.append(
                _transform_primitive(
                    primitive,
                    center=center,
                    scale_x=scale_x,
                    scale_y=scale_y,
                )
            )
            continue
        new_primitives_list.append(primitive)
    new_primitives = tuple(new_primitives_list)

    geometry_bounds = [primitive_bounds(primitive) for primitive in new_primitives]
    if not geometry_bounds:
        bounds = analysis.bounds
    else:
        bounds = (
            min(item[0] for item in geometry_bounds),
            min(item[1] for item in geometry_bounds),
            max(item[2] for item in geometry_bounds),
            max(item[3] for item in geometry_bounds),
        )

    return replace(
        analysis,
        primitives=new_primitives,
        bend_lines=new_bends,
        profiles=new_profiles,
        bounds=bounds,
    )
