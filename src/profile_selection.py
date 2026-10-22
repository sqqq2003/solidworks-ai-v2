from __future__ import annotations

import math
from dataclasses import dataclass

from cad_analyzer import Primitive, primitive_bounds


@dataclass(frozen=True)
class _ProfileBounds:
    index: int
    points: tuple[tuple[float, float], ...]
    min_x: float
    min_y: float
    max_x: float
    max_y: float
    area: float

    @property
    def centroid(self) -> tuple[float, float]:
        return ((self.min_x + self.max_x) / 2.0, (self.min_y + self.max_y) / 2.0)

    @property
    def diagonal(self) -> float:
        return max(
            ((self.max_x - self.min_x) ** 2 + (self.max_y - self.min_y) ** 2) ** 0.5,
            1.0,
        )


def _signed_area(points: tuple[tuple[float, float], ...]) -> float:
    return sum(
        start[0] * end[1] - end[0] * start[1]
        for start, end in zip(points, points[1:] + points[:1])
    ) / 2


def _contains_point(
    point: tuple[float, float],
    polygon: tuple[tuple[float, float], ...],
    tolerance: float,
) -> bool:
    x, y = point
    inside = False
    for start, end in zip(polygon, polygon[1:] + polygon[:1]):
        dx, dy = end[0] - start[0], end[1] - start[1]
        cross = (x - start[0]) * dy - (y - start[1]) * dx
        if (
            abs(cross) <= tolerance * max(abs(dx), abs(dy), 1.0)
            and min(start[0], end[0]) - tolerance <= x <= max(start[0], end[0]) + tolerance
            and min(start[1], end[1]) - tolerance <= y <= max(start[1], end[1]) + tolerance
        ):
            return True
        if (start[1] > y) != (end[1] > y):
            span = end[1] - start[1]
            if abs(span) <= 1e-18:
                continue
            if x < start[0] + (y - start[1]) * dx / span:
                inside = not inside
    return inside


def _profile_bounds(index: int, profile: Primitive) -> _ProfileBounds | None:
    if not profile.closed or profile.is_bend or len(profile.points) < 4:
        return None
    points = profile.points
    if points[0] == points[-1]:
        points = points[:-1]
    if len(points) < 3:
        return None
    area = abs(_signed_area(points))
    if area <= 1e-9:
        return None
    min_x, min_y, max_x, max_y = primitive_bounds(profile)
    return _ProfileBounds(
        index,
        points,
        min_x,
        min_y,
        max_x,
        max_y,
        area,
    )


def _sample_points(inner: _ProfileBounds) -> tuple[tuple[float, float], ...]:
    return tuple(
        point
        for start, end in zip(inner.points, inner.points[1:] + inner.points[:1])
        for point in (
            start,
            ((start[0] + end[0]) / 2, (start[1] + end[1]) / 2),
        )
    )


def _aabb_contains(
    inner: _ProfileBounds,
    outer: _ProfileBounds,
    *,
    margin: float = 0.0,
) -> bool:
    return (
        outer.min_x - margin <= inner.min_x
        and outer.min_y - margin <= inner.min_y
        and outer.max_x + margin >= inner.max_x
        and outer.max_y + margin >= inner.max_y
    )


def _contains_profile(inner: _ProfileBounds, outer: _ProfileBounds) -> bool:
    """严格一点的包含：用于孔/槽切除与缩短同步。"""

    if (
        outer.index == inner.index
        or outer.area <= inner.area * (1 + 1e-9)
        or not _aabb_contains(inner, outer, margin=0.0)
    ):
        return False
    # CAD 导出常有 0.1~0.5 mm 缝；按外轮廓对角线放宽。
    tolerance = max(outer.diagonal * 2e-3, 0.5)
    samples = _sample_points(inner)
    if not samples:
        return False
    hits = sum(
        1 for point in samples if _contains_point(point, outer.points, tolerance)
    )
    return hits >= max(1, int(len(samples) * 0.85 + 0.999))


def _loosely_enclosed(inner: _ProfileBounds, outer: _ProfileBounds) -> bool:
    """宽松包含：从外轮廓候选里隐藏内部孔、槽、方，以及嵌在外框里的细节。"""

    if outer.index == inner.index or outer.area <= inner.area * 1.15:
        return False
    if _contains_profile(inner, outer):
        return True
    # 包围盒明显落在外轮廓内，且面积显著更小 → 视为内部细节，不参与钣金外轮廓。
    inset = max(outer.diagonal * 0.01, 0.2)
    if not _aabb_contains(inner, outer, margin=-inset):
        return False
    if inner.area > outer.area * 0.55:
        return False
    tolerance = max(outer.diagonal * 2e-3, 0.5)
    if _contains_point(inner.centroid, outer.points, tolerance):
        return True
    # C 形等开口轮廓：内部孔洞的质心可能落在材料外，但仍在外框包围盒内。
    return _aabb_contains(inner, outer, margin=-inset)


def _is_round(bounds: _ProfileBounds) -> bool:
    width = bounds.max_x - bounds.min_x
    height = bounds.max_y - bounds.min_y
    short = min(width, height)
    if short <= 1e-6:
        return False
    if max(width, height) / short > 1.25:
        return False
    ellipse = math.pi * (width / 2.0) * (height / 2.0)
    return bounds.area >= ellipse * 0.7


def _looks_like_part(bounds: _ProfileBounds) -> bool:
    """能单独做成一块钣金的闭合外形，排除圆孔和很小的槽。"""

    width = bounds.max_x - bounds.min_x
    height = bounds.max_y - bounds.min_y
    return (
        bounds.area >= 700.0
        and min(width, height) >= 16.0
        and not _is_round(bounds)
    )


def _directly_inside(
    inner: _ProfileBounds,
    outer: _ProfileBounds,
    metadata: list[_ProfileBounds],
) -> bool:
    if not (
        _contains_profile(inner, outer) or _loosely_enclosed(inner, outer)
    ):
        return False
    for other in metadata:
        if other.index in (inner.index, outer.index):
            continue
        if not (
            _contains_profile(other, outer) or _loosely_enclosed(other, outer)
        ):
            continue
        if other.area <= inner.area:
            continue
        if _contains_profile(inner, other) or _loosely_enclosed(inner, other):
            return False
    return True


def _is_sheet_frame(container: _ProfileBounds, metadata: list[_ProfileBounds]) -> bool:
    """图框：里面放着两块以上互不包含的零件，本身不是要折的那一块。"""

    siblings = [
        inner
        for inner in metadata
        if inner.index != container.index
        and _looks_like_part(inner)
        and _directly_inside(inner, container, metadata)
    ]
    return len(siblings) >= 2


def _metadata(profiles: tuple[Primitive, ...]) -> list[_ProfileBounds]:
    return [
        bounds
        for index, profile in enumerate(profiles)
        if (bounds := _profile_bounds(index, profile)) is not None
    ]


def is_sheet_frame_index(
    profiles: tuple[Primitive, ...],
    profile_index: int,
) -> bool:
    """整张图框不是一块钣金，不能拿去生成。"""

    metadata = _metadata(profiles)
    selected = next(
        (item for item in metadata if item.index == profile_index),
        None,
    )
    if selected is None:
        return False
    return _is_sheet_frame(selected, metadata)


def candidate_profile_indices(
    profiles: tuple[Primitive, ...],
    *,
    include_enclosed: bool = False,
) -> tuple[int, ...]:
    """Return outer part boundaries, hiding closed loops enclosed as holes or details."""
    metadata = _metadata(profiles)

    if include_enclosed:
        return tuple(profile.index for profile in metadata)

    frames = {
        item.index for item in metadata if _is_sheet_frame(item, metadata)
    }
    visible: list[int] = []
    for inner in metadata:
        if inner.index in frames:
            continue
        containers = [
            outer
            for outer in metadata
            if outer.index != inner.index and _loosely_enclosed(inner, outer)
        ]
        part_containers = [
            outer for outer in containers if outer.index not in frames
        ]
        if part_containers:
            continue
        visible.append(inner.index)
    return tuple(visible)


def contained_hole_indices(
    profiles: tuple[Primitive, ...],
    outer_index: int,
) -> tuple[int, ...]:
    """Return every closed contour contained inside the selected outer profile."""
    if not 0 <= outer_index < len(profiles):
        raise IndexError("轮廓编号无效。")
    bounds = [
        item
        for index, profile in enumerate(profiles)
        if (item := _profile_bounds(index, profile)) is not None
    ]
    # _profile_bounds 对退化轮廓（点数不足、零面积）会返回 None 并被过滤掉。
    # 这时 outer_index 可能不在 bounds 里，裸 next() 会抛 StopIteration，
    # 而调用方（出图前统计折弯线）没有兜底，整个分析结果就装配不起来 ——
    # 表现出来就是「图纸分析完了，但轮廓列表是空的、点画布也没反应」。
    selected = next((item for item in bounds if item.index == outer_index), None)
    if selected is None:
        return ()
    holes: list[int] = []
    for inner in bounds:
        if inner.index == selected.index:
            continue
        if not _contains_profile(inner, selected):
            continue
        holes.append(inner.index)
    return tuple(holes)


def outermost_containing_profile_index(
    profiles: tuple[Primitive, ...],
    profile_index: int,
) -> int:
    """若所选是内部孔/槽，升到包住它的最外闭合轮廓。"""

    if not 0 <= profile_index < len(profiles):
        raise IndexError("轮廓编号无效。")
    bounds = [
        item
        for index, profile in enumerate(profiles)
        if (item := _profile_bounds(index, profile)) is not None
    ]
    selected = next(
        (item for item in bounds if item.index == profile_index),
        None,
    )
    if selected is None:
        return profile_index
    containers = [
        candidate
        for candidate in bounds
        if candidate.index != selected.index
        and candidate.area > selected.area
        and (
            _contains_profile(selected, candidate)
            or _loosely_enclosed(selected, candidate)
        )
    ]
    if not containers:
        return profile_index
    # 图框里的零件不要升到图框；孔仍然升到包住它的那块零件。
    frames = {item.index for item in bounds if _is_sheet_frame(item, bounds)}
    chosen = profile_index
    for container in sorted(containers, key=lambda item: item.area):
        if container.index in frames and _looks_like_part(selected):
            break
        chosen = container.index
        selected = container
    return chosen


def sort_profile_indices_by_area(
    profiles: tuple[Primitive, ...],
    indices: tuple[int, ...],
    *,
    descending: bool = True,
) -> tuple[int, ...]:
    def area_of(index: int) -> float:
        bounds = _profile_bounds(index, profiles[index])
        return bounds.area if bounds is not None else 0.0

    return tuple(
        sorted(indices, key=area_of, reverse=descending)
    )


def point_hits_profile(
    point: tuple[float, float],
    profile: Primitive,
    *,
    edge_tolerance: float,
) -> tuple[bool, float]:
    """点击是否命中轮廓：面内或边距内。返回 (命中, 到边的距离)。"""

    points = profile.points
    if len(points) >= 2 and points[0] == points[-1]:
        closed_points = points[:-1]
    else:
        closed_points = points
    if len(closed_points) < 2:
        return False, float("inf")

    closest = float("inf")
    for start, end in zip(points, points[1:] + (points[:1] if profile.closed else ())):
        dx, dy = end[0] - start[0], end[1] - start[1]
        length_squared = dx * dx + dy * dy
        if length_squared <= 1e-18:
            distance = ((point[0] - start[0]) ** 2 + (point[1] - start[1]) ** 2) ** 0.5
        else:
            projection = max(
                0.0,
                min(
                    1.0,
                    ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy)
                    / length_squared,
                ),
            )
            closest_point = (
                start[0] + projection * dx,
                start[1] + projection * dy,
            )
            distance = (
                (point[0] - closest_point[0]) ** 2
                + (point[1] - closest_point[1]) ** 2
            ) ** 0.5
        closest = min(closest, distance)

    if closest <= edge_tolerance:
        return True, closest
    if profile.closed and len(closed_points) >= 3:
        tolerance = max(edge_tolerance, 1e-6)
        if _contains_point(point, closed_points, tolerance):
            return True, closest
    return False, closest


def profile_area(profile: Primitive) -> float:
    bounds = _profile_bounds(0, profile)
    return bounds.area if bounds is not None else 0.0
