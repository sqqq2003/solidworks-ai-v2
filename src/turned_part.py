# -*- coding: utf-8 -*-
"""车件：整根外形截一半，绕中心线旋转，或按件类凸台拉伸。

P0 轮廓选取见 turned_outline：不用图框矩形，改沿中心线取零件半边。
生成时的单位、旋转轴和六角/方钢/薄壁见 turned_generate，说明在 NOTES-P1.md。
键槽、中孔、倒角、端部车削和化妆螺纹见 turned_features，说明在 NOTES-P1-features.md。
不做工程图导出。
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, replace
from pathlib import Path

from cad_analyzer import DrawingAnalysis, DrawingText, Primitive, primitive_bounds

Point = tuple[float, float]

_THREAD = re.compile(
    r"M\s*(\d+(?:\.\d+)?)(?:\s*[xX×*]\s*(\d+(?:\.\d+)?))?",
    re.IGNORECASE,
)
_DRILL = re.compile(
    r"(?:Φ|φ|⌀|Ø|∅)\s*(\d+(?:\.\d+)?)\s*(?:深|[xX×*])\s*(\d+(?:\.\d+)?)"
)
_DEPTH_ONLY = re.compile(r"(?:钻孔)?深\s*(\d+(?:\.\d+)?)")


@dataclass(frozen=True)
class TurnedThread:
    designation: str
    pitch_mm: float | None
    text: str
    x: float | None = None
    y: float | None = None


@dataclass(frozen=True)
class TurnedHole:
    diameter_mm: float
    depth_mm: float
    text: str
    x: float | None = None
    y: float | None = None
    thread: str = ""
    internal: bool = False


@dataclass(frozen=True)
class TurnedPartPlan:
    """半边旋转轮廓。profile 为 (轴向 mm, 半径 mm)，已闭合，含轴线。"""

    axis: str
    axis_position: float
    axis_source: str
    profile: tuple[Point, ...]
    threads: tuple[TurnedThread, ...]
    holes: tuple[TurnedHole, ...]
    profile_index: int = 0
    label: str = "件01"
    bounds: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    # revolve | hex | rect | tube | sprocket。尺寸：六角为对边，方钢为宽高，薄壁为外径和壁厚。
    stock: str = "revolve"
    stock_size_mm: tuple[float, ...] = ()
    keyways: tuple = ()
    bores: tuple = ()
    end_turns: tuple = ()
    chamfer_mm: float = 0.0
    knurl: str = ""
    teeth: int = 0
    hand_finish: tuple = ()

    @property
    def length_mm(self) -> float:
        xs = [point[0] for point in self.profile]
        return max(xs) - min(xs)

    @property
    def max_radius_mm(self) -> float:
        return max(point[1] for point in self.profile)

    @property
    def stock_label(self) -> str:
        from turned_generate import stock_label

        return stock_label(self.stock)


def _ring(profile: Primitive) -> list[Point]:
    points = list(profile.points)
    if len(points) > 1 and math.dist(points[0], points[-1]) <= 1e-6:
        points = points[:-1]
    return points


def _profile_area(points: list[Point]) -> float:
    if len(points) < 3:
        return 0.0
    return abs(
        sum(
            start[0] * end[1] - end[0] * start[1]
            for start, end in zip(points, points[1:] + points[:1])
        )
        / 2.0
    )


def _largest_outline(analysis: DrawingAnalysis) -> Primitive:
    from turned_outline import (
        is_round_profile,
        is_sheet_frame,
        _is_title_block_loop,
        _sheet_has_frame,
    )

    closed = [
        profile
        for profile in analysis.profiles
        if profile.closed and not profile.is_bend and len(profile.points) >= 4
    ]
    if not closed:
        raise ValueError("图上没有可用于旋转的闭合外形。")
    bounds = analysis.bounds
    drawing_w = max(bounds[2] - bounds[0], 1e-6)
    drawing_h = max(bounds[3] - bounds[1], 1e-6)
    # 只有图纸里确实存在图框时，才按「bbox 接近图幅」排除环。
    # 没有图框的简图，零件外形本来就可能占满整张，不能这么排除。
    frame_indexes = {
        index
        for index, profile in enumerate(closed)
        if is_sheet_frame(profile, analysis)
    }

    # 闭合图框 或 四条独立边界线，任一命中即认为有框。
    frame_detected = _sheet_has_frame(analysis)

    def _frame_like(index: int, profile: Primitive) -> bool:
        if index in frame_indexes:
            return True
        if not frame_detected:
            return False
        min_x, min_y, max_x, max_y = primitive_bounds(profile)
        # 图框常是内外两道边线：外框在标注线层，能被 is_sheet_frame 认出；
        # 内框却跟着实线一起被并进某个闭合环，于是漏网并包住整张图幅。
        # 零件视图不可能占满整张图纸，两个方向都接近图幅的环一律不算零件。
        return (max_x - min_x) >= 0.80 * drawing_w and (max_y - min_y) >= 0.80 * drawing_h

    def _furniture(index: int, profile: Primitive) -> bool:
        if _frame_like(index, profile):
            return True
        # 标题栏压在图幅边角，紧贴两条边，也比零件视图大：同样不算零件。
        # 这里必须用 frame_detected 而不是 frame_indexes —— A-016 的图框是四条
        # 独立边界线，frame_indexes 为空，传它会让过滤直接失效。
        return _is_title_block_loop(profile.points, bounds, frame_detected)

    usable = [profile for index, profile in enumerate(closed) if not _furniture(index, profile)]
    if not usable:
        raise ValueError("图上没有可用于旋转的零件外形（已跳过图框）。")
    elongated = [profile for profile in usable if not is_round_profile(profile)]
    pool = elongated or usable
    return max(pool, key=lambda profile: _profile_area(_ring(profile)))


def _line_length(primitive: Primitive) -> float:
    if len(primitive.points) < 2:
        return 0.0
    return math.dist(primitive.points[0], primitive.points[-1])


def _is_centerline(primitive: Primitive) -> bool:
    if primitive.closed or primitive.is_bend or _line_length(primitive) <= 1e-6:
        return False
    layer = primitive.layer.casefold()
    if any(word in primitive.layer for word in ("中心", "轴线")):
        return True
    return any(word in layer for word in ("center", "axis", "centre"))


def _explicit_axis(analysis: DrawingAnalysis, outline: Primitive) -> tuple[str, float] | None:
    lines = [item for item in analysis.primitives if _is_centerline(item)]
    if not lines:
        return None
    line = max(lines, key=_line_length)
    start, end = line.points[0], line.points[-1]
    bounds = primitive_bounds(outline)
    dx = abs(end[0] - start[0])
    dy = abs(end[1] - start[1])
    if dx >= dy:
        y = (start[1] + end[1]) / 2.0
        if bounds[1] - 1.0 <= y <= bounds[3] + 1.0:
            return "horizontal", y
    if dy > dx:
        x = (start[0] + end[0]) / 2.0
        if bounds[0] - 1.0 <= x <= bounds[2] + 1.0:
            return "vertical", x
    return None


def _symmetry_score(points: list[Point], mirror) -> float:
    if not points:
        return 0.0
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    tol = max(0.4, 0.015 * max(max(xs) - min(xs), max(ys) - min(ys), 1.0))
    mirrored = [mirror(point) for point in points]
    hits = 0
    for point in points:
        if any(math.dist(point, other) <= tol for other in mirrored):
            hits += 1
    return hits / len(points)


def _axis_of(outline: Primitive, analysis: DrawingAnalysis) -> tuple[str, float, str]:
    explicit = _explicit_axis(analysis, outline)
    if explicit is not None:
        return explicit[0], explicit[1], "centerline"
    points = _ring(outline)
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    mid_x = (min(xs) + max(xs)) / 2.0
    mid_y = (min(ys) + max(ys)) / 2.0
    horizontal = _symmetry_score(points, lambda point: (point[0], 2.0 * mid_y - point[1]))
    vertical = _symmetry_score(points, lambda point: (2.0 * mid_x - point[0], point[1]))
    long_horizontal = (max(xs) - min(xs)) >= (max(ys) - min(ys))
    if horizontal >= 0.75 or vertical >= 0.75:
        if horizontal >= vertical:
            return "horizontal", mid_y, "symmetry"
        return "vertical", mid_x, "symmetry"
    # 半剖视图：轮廓只画了轴线一侧，轴线就落在轮廓最外缘的长直边上，
    # 而不是几何中线。检测某条外缘边是否接近贯穿整个跨度（≥60%），
    # 且轮廓几乎全在同一侧。
    edge_axis = _edge_axis(points)
    # 外缘边只是「像」轴线：整视图的上下两条边同样贯穿、同样只有一侧有点，
    # 直接拿边线当轴就会把轮廓截成一条线。先试截，截不出实体就退回中线。
    if edge_axis is not None and _half_is_usable(outline, edge_axis[0], edge_axis[1]):
        return edge_axis[0], edge_axis[1], "half-section"
    if long_horizontal:
        return "horizontal", mid_y, "midline"
    return "vertical", mid_x, "midline"


def _half_is_usable(outline: Primitive, axis: str, position: float) -> bool:
    """该轴线能否截出可用的半边轮廓：有高度，且底边贴在轴线上。"""

    try:
        profile = half_profile(outline, axis, position)
    except ValueError:
        return False
    if len(profile) < 4:
        return False
    top = max(point[1] for point in profile)
    bottom = min(point[1] for point in profile)
    return top > 0.5 and abs(bottom) <= 0.05


def _edge_axis(points: list[Point]) -> tuple[str, float] | None:
    """半剖视图轴线：外缘一条接近贯穿的直边，轮廓点几乎全在它一侧。

    滚筒轴芯这类半剖图，轴线（y=min）由多段共线边拼成，跨度接近全长，
    而轮廓其余点都在轴线同侧（上或下）。返回 (orientation, position)。
    """

    if len(points) < 4:
        return None
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    span_x = max(xs) - min(xs)
    span_y = max(ys) - min(ys)
    if span_x <= 1.0 or span_y <= 1.0:
        return None
    band = max(0.5, 0.01 * max(span_x, span_y))

    def edge_span(coord_of, along_of, edge_value: float) -> float:
        """该缘值带上所有点的轴向跨度（首尾端点覆盖，不是连续边总长）。"""

        alongs = [along_of(point) for point in points if abs(coord_of(point) - edge_value) <= band]
        if not alongs:
            return 0.0
        return max(alongs) - min(alongs)

    candidates: list[tuple[str, float, float]] = []
    for edge_y, side in ((min(ys), -1), (max(ys), 1)):
        total = edge_span(lambda p: p[1], lambda p: p[0], edge_y)
        if total >= 0.6 * span_x:
            opposite = [p for p in points if side * (p[1] - edge_y) > band]
            if len(opposite) <= max(2, int(0.15 * len(points))):
                candidates.append(("horizontal", edge_y, total))
    for edge_x, side in ((min(xs), -1), (max(xs), 1)):
        total = edge_span(lambda p: p[0], lambda p: p[1], edge_x)
        if total >= 0.6 * span_y:
            opposite = [p for p in points if side * (p[0] - edge_x) > band]
            if len(opposite) <= max(2, int(0.15 * len(points))):
                candidates.append(("vertical", edge_x, total))
    if not candidates:
        return None
    orientation, position, _total = max(candidates, key=lambda item: item[2])
    return orientation, position


def _clip_half(points: list[Point], keep, intersect) -> list[Point]:
    if len(points) < 3:
        return []
    output: list[Point] = []
    for index, current in enumerate(points):
        previous = points[index - 1]
        previous_in = keep(previous)
        current_in = keep(current)
        if current_in:
            if not previous_in:
                output.append(intersect(previous, current))
            output.append(current)
        elif previous_in:
            output.append(intersect(previous, current))
    cleaned: list[Point] = []
    for point in output:
        if not cleaned or math.dist(cleaned[-1], point) > 1e-4:
            cleaned.append(point)
    if len(cleaned) > 1 and math.dist(cleaned[0], cleaned[-1]) <= 1e-4:
        cleaned.pop()
    return cleaned


def _to_axial(points: list[Point], axis: str, position: float) -> list[Point]:
    local: list[Point] = []
    for x, y in points:
        if axis == "horizontal":
            axial, radius = x, y - position
        else:
            axial, radius = y, x - position
        if radius < -0.05:
            continue
        local.append((axial, 0.0 if radius < 0.05 else radius))
    cleaned: list[Point] = []
    for point in local:
        if not cleaned or math.dist(cleaned[-1], point) > 1e-4:
            cleaned.append(point)
    if len(cleaned) > 1 and math.dist(cleaned[0], cleaned[-1]) <= 1e-4:
        cleaned.pop()
    if cleaned and math.dist(cleaned[0], cleaned[-1]) > 1e-4:
        cleaned.append(cleaned[0])
    return cleaned


def half_profile(outline: Primitive, axis: str, position: float) -> tuple[Point, ...]:
    """把整根外形沿轴线截成半边闭合轮廓，半径在轴线一侧。"""

    points = _ring(outline)
    tolerance = 1e-4

    if axis == "horizontal":
        def keep(point: Point) -> bool:
            return point[1] >= position - tolerance

        def intersect(start: Point, end: Point) -> Point:
            if abs(end[1] - start[1]) <= 1e-12:
                return (start[0], position)
            factor = (position - start[1]) / (end[1] - start[1])
            return (start[0] + factor * (end[0] - start[0]), position)
    else:
        def keep(point: Point) -> bool:
            return point[0] >= position - tolerance

        def intersect(start: Point, end: Point) -> Point:
            if abs(end[0] - start[0]) <= 1e-12:
                return (position, start[1])
            factor = (position - start[0]) / (end[0] - start[0])
            return (position, start[1] + factor * (end[1] - start[1]))

    clipped = _clip_half(points, keep, intersect)
    profile = _to_axial(clipped, axis, position)
    if len(profile) < 4 or max(point[1] for point in profile) <= 0.05:
        raise ValueError("无法从整根外形截出可旋转的半边轮廓。")
    return tuple(profile)


def _note_texts(analysis: DrawingAnalysis) -> list[DrawingText]:
    if analysis.text_entities:
        return list(analysis.text_entities)
    return [DrawingText(text, 0.0, 0.0, 0.0) for text in analysis.texts]


def _note_near_outline(note: DrawingText, outline: Primitive | None) -> bool:
    if outline is None:
        return True
    if note.height <= 0 and note.x == 0.0 and note.y == 0.0:
        return True
    min_x, min_y, max_x, max_y = primitive_bounds(outline)
    margin = max(25.0, 0.35 * max(max_x - min_x, max_y - min_y, 1.0))
    return min_x - margin <= note.x <= max_x + margin and min_y - margin <= note.y <= max_y + margin


def read_turned_notes(
    analysis: DrawingAnalysis,
    outline: Primitive | None = None,
) -> tuple[tuple[TurnedThread, ...], tuple[TurnedHole, ...]]:
    threads: list[TurnedThread] = []
    holes: list[TurnedHole] = []
    seen_threads: set[str] = set()
    seen_holes: set[tuple[float, float]] = set()
    for note in _note_texts(analysis):
        if not _note_near_outline(note, outline):
            continue
        text = note.text.strip()
        if not text:
            continue
        for match in _THREAD.finditer(text):
            size = match.group(1)
            pitch = float(match.group(2)) if match.group(2) else None
            designation = f"M{size}" if pitch is None else f"M{size}×{pitch:g}"
            if designation in seen_threads:
                continue
            seen_threads.add(designation)
            threads.append(
                TurnedThread(designation, pitch, text, note.x, note.y)
            )
        drill = _DRILL.search(text)
        if drill is not None:
            diameter = float(drill.group(1))
            depth = float(drill.group(2))
            key = (diameter, depth)
            if key not in seen_holes:
                seen_holes.add(key)
                holes.append(TurnedHole(diameter, depth, text, note.x, note.y))
            continue
        depth_only = _DEPTH_ONLY.search(text)
        if depth_only is not None and "螺纹" not in text:
            depth = float(depth_only.group(1))
            key = (0.0, depth)
            if key not in seen_holes:
                seen_holes.add(key)
                holes.append(TurnedHole(0.0, depth, text, note.x, note.y))
    return tuple(threads), tuple(holes)


def plan_turned_outline(
    analysis: DrawingAnalysis,
    outline: Primitive,
    *,
    profile_index: int = 0,
    label: str = "件01",
    axis_hint: tuple[str, float, str] | None = None,
) -> TurnedPartPlan:
    if axis_hint is None:
        axis, position, source = _axis_of(outline, analysis)
    else:
        axis, position, source = axis_hint
    profile = half_profile(outline, axis, position)
    threads, holes = read_turned_notes(analysis, outline)
    plan = TurnedPartPlan(
        axis,
        position,
        source,
        profile,
        threads,
        holes,
        profile_index,
        label,
        primitive_bounds(outline),
    )
    return _attach_stock(plan, analysis)


def _attach_features(plan: TurnedPartPlan, analysis: DrawingAnalysis) -> TurnedPartPlan:
    from turned_features import attach_feature_fields

    return attach_feature_fields(plan, analysis)


def _attach_stock(plan: TurnedPartPlan, analysis: DrawingAnalysis) -> TurnedPartPlan:
    from turned_generate import classify_stock

    notes = [note.text for note in _note_texts(analysis)]
    choice = classify_stock(notes, max_radius_mm=plan.max_radius_mm)
    return replace(plan, stock=choice.kind, stock_size_mm=choice.size_mm)


_DRAWING_SUFFIXES = {".dxf", ".dwg"}


def list_turned_drawings(folder: str | Path) -> tuple[Path, ...]:
    """文件夹里每一张 CAD 图一份。不递归隐藏目录。"""

    root = Path(folder)
    if not root.is_dir():
        raise ValueError(f"不是文件夹：{root}")
    found: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.casefold() not in _DRAWING_SUFFIXES:
            continue
        if any(part.startswith(".") for part in path.relative_to(root).parts):
            continue
        found.append(path)
    return tuple(
        sorted(
            found,
            key=lambda item: (
                item.name.casefold(),
                str(item.relative_to(root)).casefold(),
            ),
        )
    )


def turned_part_output_path(output_dir: str | Path, drawing: Path) -> Path:
    """一件图一个文件，主名用图名。重名时加短后缀。"""

    directory = Path(output_dir)
    candidate = directory / f"{drawing.stem}.SLDPRT"
    if not candidate.exists():
        return candidate
    number = 2
    while True:
        alt = directory / f"{drawing.stem}_{number}.SLDPRT"
        if not alt.exists():
            return alt
        number += 1


def _fallback_outline_indexes(analysis: DrawingAnalysis) -> tuple[int, ...]:
    """没有中心线包络时，用闭合外轮廓，并丢掉图框。"""

    from profile_selection import candidate_profile_indices

    from turned_outline import is_sheet_frame

    profiles = analysis.profiles
    raw = candidate_profile_indices(profiles, include_enclosed=False)
    visible = tuple(index for index in raw if not is_sheet_frame(profiles[index], analysis))
    if visible:
        return visible
    kept = [index for index, profile in enumerate(profiles) if not is_sheet_frame(profile, analysis)]
    if not kept:
        return ()
    subset = tuple(profiles[index] for index in kept)
    local = candidate_profile_indices(subset, include_enclosed=False)
    return tuple(kept[index] for index in local)


def _plan_from_silhouette(analysis: DrawingAnalysis, silhouette) -> TurnedPartPlan:
    from turned_outline import apply_dimension_overrides

    plan = plan_turned_outline(
        analysis,
        silhouette.outline,
        profile_index=-1,
        axis_hint=(silhouette.axis, silhouette.position, silhouette.source),
    )
    # 特征必须在尺寸覆盖之后再挂，断裂视图的长度才是零件长度。
    # 不做 SLDDRW / 工程图导出。
    plan = apply_dimension_overrides(plan, analysis)
    plan = _attach_stock(plan, analysis)
    return _attach_features(plan, analysis)


def plan_turned_part(analysis: DrawingAnalysis) -> TurnedPartPlan:
    from turned_outline import select_turned_silhouettes, apply_dimension_overrides

    silhouettes = select_turned_silhouettes(analysis)
    if silhouettes:
        return _plan_from_silhouette(analysis, silhouettes[0])
    outline = _largest_outline(analysis)
    plan = plan_turned_outline(analysis, outline)
    # 与轮廓路径同序：断裂视图画不满，先把长度/半径按主标注校正，再判毛坯。
    plan = _attach_stock(apply_dimension_overrides(plan, analysis), analysis)
    return _attach_features(plan, analysis)


def discover_turned_parts(analysis: DrawingAnalysis) -> tuple[TurnedPartPlan, ...]:
    """图上每根可旋转的外轮廓一件。顺序从上到下、从左到右。

    有中心线时走半边包络，避免把图框矩形旋成零件。
    """

    from turned_outline import select_turned_silhouettes

    found: list[tuple[tuple[float, float, float, float], TurnedPartPlan]] = []
    silhouettes = select_turned_silhouettes(analysis)
    if silhouettes:
        for silhouette in silhouettes:
            try:
                plan = _plan_from_silhouette(analysis, silhouette)
            except ValueError:
                continue
            found.append((plan.bounds, plan))
    else:
        for index in _fallback_outline_indexes(analysis):
            outline = analysis.profiles[index]
            try:
                plan = _attach_features(
                    plan_turned_outline(analysis, outline, profile_index=index),
                    analysis,
                )
            except ValueError:
                continue
            found.append((plan.bounds, plan))
    found.sort(key=lambda item: (-item[0][3], item[0][0]))
    labeled: list[TurnedPartPlan] = []
    for sequence, (_bounds, plan) in enumerate(found, start=1):
        labeled.append(replace(plan, label=f"件{sequence:02d}"))
    if not labeled:
        raise ValueError("图上没有可用于旋转的闭合外形。")
    return tuple(labeled)


def finish_turned_generation(output, *, saved, lease, post_save_error, release_error):
    """Keep a non-empty SLDPRT. Later COM failure is not a hard failure.

    Returns the path when the file stays on disk. Returns None when there is
    nothing to keep, so the original error still propagates. Does not delete
    the file and does not call ExitApp.
    """
    from part_verification import (
        PARTIAL_COM_DISCONNECT_STATUS,
        PARTIAL_REBIND_STATUS,
        PostSaveRebindFailed,
        is_member_not_found,
        product_file_ready,
    )

    if not saved or not product_file_ready(output):
        return None
    disconnected = bool(getattr(lease, "disconnected", False)) if lease is not None else False
    if lease is not None and (post_save_error is not None or release_error is not None or disconnected):
        if not getattr(lease, "post_save_outcome", None):
            if isinstance(post_save_error, PostSaveRebindFailed) or is_member_not_found(post_save_error):
                lease.post_save_outcome = PARTIAL_REBIND_STATUS
            else:
                lease.post_save_outcome = PARTIAL_COM_DISCONNECT_STATUS
    return str(output)


def generate_turned_part(plan: TurnedPartPlan, output_path: str) -> str:
    """按件类生成零件。轴类绕局部中心线旋转；六角和方钢凸台拉伸。

    草图先平移到原点再换成米。旋转轴用选择标记单独选中。
    实体外包与计划不符时抛错，不保存。
    """

    from pathlib import Path

    import solidworks_generator as sw
    import sw_session as session

    output = Path(output_path).expanduser().resolve()
    if output.suffix.casefold() != ".sldprt":
        raise ValueError("输出文件扩展名必须为 .SLDPRT。")
    if output.exists():
        raise FileExistsError(f"输出文件已存在：{output}")
    if not session.on_task_sta():
        return session.run_on_task_sta(
            lambda: generate_turned_part(plan, output_path),
            timeout=session.SW_SESSION_CALL_TIMEOUT_SEC,
            task_name="generate_turned_part",
        )
    lease = session.current_lease()
    session.require_model_write(lease)
    from turned_generate import REVOLVE_AXIS_MARK, build_turned, mm_point_to_m

    build = build_turned(plan)

    try:
        import pythoncom
        import win32com.client
    except ImportError as error:
        raise sw.SolidWorksGenerationError(
            "生成车件需要 pywin32；请使用配置了 SolidWorks 的 Python 环境。"
        ) from error

    solidworks = None
    document_title = None
    com_initialized = False
    typed_solidworks = None
    saved = False
    model = None
    post_save_error = None
    try:
        # The task STA already owns the apartment. A nested CoUninitialize
        # drops that count and the next call sees a dead proxy.
        if not getattr(lease, "com_initialized", False):
            pythoncom.CoInitialize()
            com_initialized = True

        solidworks, _created_here = sw._connect_task_solidworks(lease, win32com, pythoncom)
        # 目标机装的 SolidWorks 版本未必和开发机一致，主版本号要现探测。
        type_library = sw.ensure_solidworks_typelib()
        typed_solidworks = sw._as_interface(type_library, solidworks, "ISldWorks")
        if lease is not None:
            lease.note_bound_application(solidworks)
            lease.note_bound_application(typed_solidworks)
        sw._set_sw_automation_mode(typed_solidworks, True)
        template_path = typed_solidworks.GetUserPreferenceStringValue(
            sw.SW_DEFAULT_TEMPLATE_PART
        )
        if not template_path or not Path(template_path).is_file():
            raise sw.SolidWorksGenerationError("SolidWorks 的默认零件模板不可用。")
        raw_model = typed_solidworks.NewDocument(template_path, 0, 0.0, 0.0)
        if raw_model is None:
            raise sw.SolidWorksGenerationError("SolidWorks 未能创建新的零件文档。")
        model = sw._as_interface(type_library, raw_model, "IModelDoc2")
        document_title = model.GetTitle()
        if lease is not None and document_title:
            lease.note_owned_document(str(document_title), handle_id=id(raw_model))
        feature_manager = sw._as_interface(
            type_library, model.FeatureManager, "IFeatureManager"
        )
        sketch_manager = sw._as_interface(
            type_library, model.SketchManager, "ISketchManager"
        )
        planes = [
            feature
            for feature in sw._features(model, type_library)
            if feature.GetTypeName2() == "RefPlane"
        ]
        if not planes:
            raise sw.SolidWorksGenerationError("零件模板中没有可用的基准面。")
        plane = _front_plane(planes)

        def draw(
            contour: tuple[Point, ...],
            name: str,
            centerline: tuple[Point, Point] | None,
            segments: tuple = (),
        ):
            known = {
                feature.Name
                for feature in sw._features(model, type_library)
                if feature.GetTypeName2() == "ProfileFeature"
            }
            model.ClearSelection2(True)
            if not sw._as_interface(type_library, plane, "IEntity").Select4(False, None):
                raise sw.SolidWorksGenerationError(f"无法选择{name}草图基准面。")
            sketch_manager.InsertSketch(True)
            previous = sketch_manager.AddToDB
            sketch_manager.AddToDB = True
            try:
                if centerline is not None:
                    start = mm_point_to_m(centerline[0])
                    end = mm_point_to_m(centerline[1])
                    if sketch_manager.CreateCenterLine(*start, *end) is None:
                        raise sw.SolidWorksGenerationError(f"{name}的旋转轴没有写进草图。")
                if segments:
                    for piece in segments:
                        start = mm_point_to_m(piece.start)
                        end = mm_point_to_m(piece.end)
                        if piece.kind == "arc" and piece.via is not None:
                            via = mm_point_to_m(piece.via)
                            if sketch_manager.Create3PointArc(*start, *via, *end) is None:
                                raise sw.SolidWorksGenerationError(
                                    f"{name}有一段圆弧没有写进草图，已中止。"
                                )
                            continue
                        if sketch_manager.CreateLine(*start, *end) is None:
                            raise sw.SolidWorksGenerationError(
                                f"{name}有一段直线没有写进草图，已中止。"
                            )
                else:
                    loop = (
                        contour
                        if math.dist(contour[0], contour[-1]) <= 1e-6
                        else contour + (contour[0],)
                    )
                    for start_mm, end_mm in zip(loop, loop[1:]):
                        if math.dist(start_mm, end_mm) <= 1e-6:
                            continue
                        start = mm_point_to_m(start_mm)
                        end = mm_point_to_m(end_mm)
                        if sketch_manager.CreateLine(*start, *end) is None:
                            raise sw.SolidWorksGenerationError(
                                f"{name}有一段直线没有写进草图，已中止。"
                            )
            finally:
                sketch_manager.AddToDB = previous
            model.ClearSelection2(True)
            sketch_manager.InsertSketch(True)
            sketch = sw._latest_profile_sketch(model, type_library, known)
            if sketch is None:
                raise sw.SolidWorksGenerationError(f"SolidWorks 未能创建{name}草图。")
            _require_closed_contour(type_library, sketch, name)
            try:
                sketch.Name = name
            except Exception:
                pass
            return sketch

        def revolve(sketch, *, cut: bool, angle: float):
            _select_revolve_axis(model, type_library, sketch, REVOLVE_AXIS_MARK)
            if cut:
                feature = feature_manager.FeatureRevolveCut(
                    angle, False, 0.0, 0, 0, True, True
                )
            else:
                feature = feature_manager.FeatureRevolve2(
                    True, True, False, False, False, False, 0, 0,
                    angle, 0.0, False, False, 0.0, 0.0, 0, 0.0, 0.0,
                    True, True, True,
                )
            model.ClearSelection2(True)
            return feature

        def extrude(sketch, depth_mm: float):
            if not sw._as_interface(type_library, sketch, "IEntity").Select4(False, None):
                raise sw.SolidWorksGenerationError("无法选择凸台拉伸草图。")
            depth_m = depth_mm / 1000.0
            feature = None
            for merge in (False, True):
                try:
                    feature = feature_manager.FeatureExtrusion2(
                        True,
                        False,
                        False,
                        0,
                        0,
                        depth_m,
                        0.0,
                        False,
                        False,
                        False,
                        False,
                        0.0,
                        0.0,
                        False,
                        False,
                        False,
                        False,
                        merge,
                        True,
                        True,
                        0,
                        0.0,
                        False,
                    )
                except Exception:
                    feature = None
                if feature is not None:
                    break
            model.ClearSelection2(True)
            if feature is None:
                raise sw.SolidWorksGenerationError("SolidWorks 没有生成凸台拉伸，已中止保存。")
            model.EditRebuild3()
            try:
                feature.Name = "凸台拉伸"
            except Exception:
                pass
            return feature

        if build.extrude is not None:
            section = draw(build.extrude.contour_mm, "截面", None)
            extrude(section, build.extrude.depth_mm)
            mismatch = _body_mismatch(model, type_library, build.expected_dims_mm)
            if mismatch is not None:
                raise sw.SolidWorksGenerationError(
                    f"{build.label}几何不对，已中止保存。{mismatch}"
                )
            for cut in build.axial_cuts:
                _cut_axial(
                    model,
                    type_library,
                    sketch_manager,
                    feature_manager,
                    plane,
                    cut,
                    across_flats=(
                        plan.stock_size_mm[0] if build.kind == "hex" and plan.stock_size_mm else 0.0
                    ),
                )
        else:
            if build.revolve is None:
                raise sw.SolidWorksGenerationError("没有可生成的旋转轮廓。")
            profile_sketch = draw(
                build.revolve.contour_mm,
                "旋转轮廓",
                (build.revolve.axis_start_mm, build.revolve.axis_end_mm),
                build.revolve.segments,
            )
            feature = revolve(profile_sketch, cut=False, angle=2.0 * math.pi)
            try:
                model.EditRebuild3()
            except Exception:
                pass
            if feature is None:
                raise sw.SolidWorksGenerationError(
                    "SolidWorks 没有生成旋转特征，已中止保存。"
                )
            try:
                feature.Name = "旋转" if build.kind != "sprocket" else "轮毂"
            except Exception:
                pass
            mismatch = _body_mismatch(model, type_library, build.expected_dims_mm)
            if mismatch is not None:
                raise sw.SolidWorksGenerationError(
                    f"{build.label}几何不对，已中止保存。{mismatch}"
                )
            angle = 2.0 * math.pi
            for index, bore in enumerate(build.bore_cuts, start=1):
                _revolve_named(model, draw, revolve, bore, f"中孔{index}", angle)
            for index, chamfer in enumerate(build.chamfer_cuts, start=1):
                _revolve_named(model, draw, revolve, chamfer, f"倒角{index}", angle)
            for index, keyway in enumerate(build.keyway_cuts, start=1):
                _cut_keyway(model, type_library, feature_manager, draw, keyway, index)
            for index, hole in enumerate(build.hole_cuts, start=1):
                _revolve_named(model, draw, revolve, hole, f"钻孔{index}", angle)

        cosmetic_notes = _try_cosmetic_threads(
            model, type_library, plan, build
        )
        mismatch = _body_mismatch(model, type_library, build.expected_dims_mm)
        if mismatch is not None:
            raise sw.SolidWorksGenerationError(
                f"{build.label}几何不对，已中止保存。{mismatch}"
            )
        _write_turned_properties(
            model,
            build.label,
            build.length_mm,
            plan,
            extra_hand=tuple(build.warnings) + tuple(cosmetic_notes),
        )
        _prefer_millimeters(model, type_library)

        if not sw._com_read(model, "EditRebuild3"):
            raise sw.SolidWorksGenerationError("车件最终重建失败，不保存")
        output.parent.mkdir(parents=True, exist_ok=True)
        if output.exists():
            raise FileExistsError(f"输出已存在：{output}")
        session.require_model_write(lease)
        errors = model.SaveAs3(str(output), 0, 2)
        from part_verification import (
            PostSaveComDisconnect,
            assert_native_save,
            rebind_model_after_save,
        )
        assert_native_save(output, errors)
        saved = True
        if lease is not None:
            lease.generation_saved = True
            lease.generation_path = str(output)

        from part_verification import (
            PostSaveRebindFailed,
            read_active_document,
            read_com_property,
        )

        def _wrap_model(raw):
            if raw is None:
                return None
            return sw._as_interface(type_library, raw, "IModelDoc2")

        def _active_model(app):
            return _wrap_model(read_active_document(app))

        def _open_saved(app):
            from part_verification import is_member_not_found
            saved_path = str(output.resolve())
            found = None
            by_name = getattr(app, "GetOpenDocumentByName", None)
            if callable(by_name):
                try:
                    found = by_name(saved_path)
                except Exception as error:
                    if not is_member_not_found(error):
                        raise
                    found = None
            if found is None:
                opener = getattr(app, "OpenDoc6", None)
                if callable(opener):
                    opened = opener(saved_path, 1, 1, "", 0, 0)
                    found = opened[0] if isinstance(opened, tuple) else opened
            if found is None:
                try:
                    found = read_com_property(app, "ActiveDoc")
                except Exception as error:
                    if not is_member_not_found(error):
                        raise
                    found = None
            return _wrap_model(found)

        def _saved_title(rebound):
            try:
                return read_com_property(rebound, "GetTitle")
            except Exception as error:
                from part_verification import is_member_not_found
                if is_member_not_found(error):
                    return output.name
                raise

        rebound_title = document_title
        try:
            model, rebound_title = rebind_model_after_save(
                typed_solidworks,
                _active_model,
                _saved_title,
                lease=lease,
                open_saved=_open_saved,
            )
        except (PostSaveComDisconnect, PostSaveRebindFailed) as error:
            post_save_error = error
            from part_verification import product_file_ready
            if not product_file_ready(output):
                raise
            import logging
            logging.getLogger(__name__).warning(
                "post-save rebind failed; keeping %s; ExitApp was not called: %s",
                output,
                error,
            )
        if (
            lease is not None
            and document_title
            and rebound_title
            and rebound_title != document_title
            and lease.is_owned_title(document_title)
        ):
            lease.rename_owned(document_title, rebound_title)
        document_title = rebound_title
        return str(output)
    finally:
        import sys
        release_error = None
        keep_previous = False
        try:
            if lease is not None:
                keep_previous = bool(lease.keep_application_open)
                # Close only this document. Do not ExitApp from generation.
                lease.keep_application_open = True
            application = typed_solidworks if typed_solidworks is not None else solidworks
            if application is not None:
                # A failed rebind must not CloseDoc through the stale pointer.
                release_model = None if post_save_error is not None else model

                def _saved_title():
                    from part_verification import read_com_property
                    return read_com_property(release_model, "GetTitle")

                session.release_task_documents(
                    lease,
                    application,
                    title=str(document_title) if document_title else None,
                    close=bool(document_title),
                    resolve_title=_saved_title if saved and release_model is not None else None,
                )
        except Exception as error:
            release_error = error
        finally:
            if lease is not None:
                lease.keep_application_open = keep_previous
            if com_initialized:
                pythoncom.CoUninitialize()
        kept = finish_turned_generation(
            output,
            saved=saved,
            lease=lease,
            post_save_error=post_save_error,
            release_error=release_error,
        )
        pending = sys.exc_info()[1]
        if kept is not None and (pending is not None or post_save_error is not None or release_error is not None):
            import logging
            logging.getLogger(__name__).warning(
                "turned part kept after post-save COM failure; "
                "ExitApp was not called: %s",
                post_save_error or release_error or pending,
            )
        if kept is not None and pending is not None:
            return kept
        if release_error is not None and pending is None and kept is None:
            raise release_error


def _front_plane(planes):
    """前视基准面。特征表倒序时，最早的基准面在列表末尾，那就是前视。"""

    for plane in planes:
        name = str(getattr(plane, "Name", "") or "")
        if "前视" in name or "front" in name.casefold():
            return plane
    return planes[-1]


def _prefer_millimeters(model, type_library) -> None:
    """文档显示用毫米。草图 API 仍按米写入，这里只改用户看到的单位。"""

    try:
        mmgs = getattr(type_library, "swUnitSystem_MMGS", None)
        pref = getattr(type_library, "swUnitSystem", None)
        if mmgs is None or pref is None:
            return
        model.Extension.SetUserPreferenceInteger(int(pref), 0, int(mmgs))
    except Exception:
        return


def _require_closed_contour(type_library, sketch_feature, name: str) -> None:
    import solidworks_generator as sw

    sketch = sw._as_interface(
        type_library, sketch_feature.GetSpecificFeature2(), "ISketch"
    )
    contours = sketch.GetSketchContours() or ()
    closed = 0
    for contour in contours:
        try:
            if sw._as_interface(type_library, contour, "ISketchContour").IsClosed():
                closed += 1
        except Exception:
            continue
    if closed < 1:
        raise sw.SolidWorksGenerationError(
            f"{name}没有闭合轮廓，已中止保存，避免生成片体。"
        )


def _select_revolve_axis(model, type_library, sketch_feature, mark: int) -> None:
    """先选中心线（标记 16），再选草图。只选草图时，远离原点的轮廓会绕原点转成扁片。"""

    import solidworks_generator as sw

    model.ClearSelection2(True)
    sketch = sw._as_interface(
        type_library, sketch_feature.GetSpecificFeature2(), "ISketch"
    )
    segments = list(sketch.GetSketchSegments() or ())
    chosen = None
    for segment in segments:
        try:
            typed = sw._as_interface(type_library, segment, "ISketchSegment")
        except Exception:
            continue
        try:
            if typed.ConstructionGeometry:
                chosen = typed
                break
        except Exception:
            continue
    if chosen is None and segments:
        try:
            chosen = sw._as_interface(type_library, segments[0], "ISketchSegment")
        except Exception:
            chosen = None
    if chosen is None:
        raise sw.SolidWorksGenerationError(
            "旋转草图里没有中心线，已中止，避免绕原点扫成扁片。"
        )
    # SW2025 / pywin32 把 CreateSelectData 暴露成属性，加括号会报找不到成员。
    selection = model.SelectionManager.CreateSelectData
    selection.Mark = mark
    if not chosen.Select4(False, selection):
        raise sw.SolidWorksGenerationError(
            "无法选中旋转轴，已中止，避免绕原点扫成扁片。"
        )
    selection.Mark = 0
    if not sw._as_interface(type_library, sketch_feature, "IEntity").Select4(
        True, selection
    ):
        raise sw.SolidWorksGenerationError("无法选中旋转草图。")


def _body_mismatch(model, type_library, expected_mm: tuple[float, float, float]):
    from turned_generate import dims_mismatch

    readings, max_abs = _measured_dims_mm(model, type_library)
    if not readings:
        return "没有生成实体。"
    messages = []
    for dims in readings:
        message = dims_mismatch(dims, expected_mm)
        if message is None:
            return None
        messages.append(message)
    message = messages[0]
    if max_abs > 2.0 and max(expected_mm) < 2000.0:
        message += "。实体坐标离原点超过 2，草图多半仍停在图纸坐标上。"
    return message


def _measured_dims_mm(
    model, type_library
) -> tuple[list[tuple[float, float, float]], float]:
    """读实体外包。GetBodyBox 与 GetPartBox 的六个数顺序不同，两种都算。"""

    import solidworks_generator as sw

    boxes: list[list[float]] = []
    try:
        part = sw._as_interface(type_library, model, "IPartDoc")
        bodies = part.GetBodies2(0, False) or ()
    except Exception:
        bodies = ()
    for body in bodies:
        try:
            raw = body.GetBodyBox()
        except Exception:
            raw = None
        if not raw:
            continue
        values = [float(value) for value in raw]
        if len(values) == 6:
            boxes.append(values)
    if not boxes:
        try:
            raw = model.GetPartBox(True)
            values = [float(value) for value in raw]
            if len(values) == 6:
                boxes.append(values)
        except Exception:
            return [], 0.0
    if not boxes:
        return [], 0.0
    max_abs = max(abs(value) for box in boxes for value in box)
    return [_union_dims(boxes, "xyz"), _union_dims(boxes, "minmax")], max_abs


def _union_dims(boxes: list[list[float]], order: str) -> tuple[float, float, float]:
    lows = [math.inf, math.inf, math.inf]
    highs = [-math.inf, -math.inf, -math.inf]
    for values in boxes:
        scale = 1000.0 if max(abs(value) for value in values) < 5.0 else 1.0
        if order == "xyz":
            pairs = (
                (values[0], values[3]),
                (values[1], values[4]),
                (values[2], values[5]),
            )
        else:
            pairs = (
                (values[0], values[1]),
                (values[2], values[3]),
                (values[4], values[5]),
            )
        for index, (left, right) in enumerate(pairs):
            low = min(left, right) * scale
            high = max(left, right) * scale
            lows[index] = min(lows[index], low)
            highs[index] = max(highs[index], high)
    return tuple(highs[index] - lows[index] for index in range(3))


def _revolve_named(model, draw, revolve, sketch_data, name: str, angle: float) -> None:
    import solidworks_generator as sw

    before = _model_volume(model)
    sketch = draw(
        sketch_data.contour_mm,
        name,
        (sketch_data.axis_start_mm, sketch_data.axis_end_mm),
        getattr(sketch_data, "segments", ()) or (),
    )
    feature = revolve(sketch, cut=True, angle=angle)
    try:
        model.EditRebuild3()
    except Exception:
        pass
    if feature is None:
        raise sw.SolidWorksGenerationError(f"{name}没有生成，已中止保存。")
    try:
        feature.Name = name
    except Exception:
        pass
    _require_removed(model, before, name, _revolve_cut_floor_mm3(sketch_data))


def _cut_keyway(model, type_library, feature_manager, draw, keyway, index: int) -> None:
    import solidworks_generator as sw

    name = f"键槽{index}"
    before = _model_volume(model)
    sketch = draw(keyway.contour_mm, name, None)
    half_m = (keyway.width_mm / 2.0) / 1000.0
    full_m = keyway.width_mm / 1000.0
    expected = _keyway_expected_mm3(keyway)
    # 先用和钣金孔相同的双向切除，再试中面。深度试半宽和全宽，留下体积最接近槽宽的一次。
    strategies = (
        ("双向各半宽", False, sw.SW_END_CONDITION_BLIND, sw.SW_END_CONDITION_BLIND, half_m, half_m),
        ("中面半宽", True, sw.SW_END_CONDITION_MID_PLANE, 0, half_m, 0.0),
        ("中面全宽", True, sw.SW_END_CONDITION_MID_PLANE, 0, full_m, 0.0),
    )
    notes: list[str] = []
    for label, single, end1, end2, depth1, depth2 in strategies:
        selected = _select_sketch(model, type_library, sketch)
        if selected:
            raise sw.SolidWorksGenerationError(f"无法选择{name}草图，已中止保存。{selected}")
        feature, detail = _feature_cut(
            feature_manager,
            sd=single,
            flip=False,
            reverse=False,
            end1=end1,
            end2=end2,
            d1=depth1,
            d2=depth2,
            t0=sw.SW_START_CONDITION_SKETCH_PLANE,
            offset=0.0,
            flip_start=False,
        )
        model.ClearSelection2(True)
        _rebuild(model)
        if feature is None:
            notes.append(f"{label}：{detail}")
            continue
        removed = _removed_mm3(model, before)
        if removed is None or _close_volume(removed, expected):
            _name_feature(feature, name)
            return
        notes.append(f"{label}：去掉 {removed:.1f} mm³，期望约 {expected:.1f} mm³")
        _delete_feature(model, type_library, feature)
        _rebuild(model)
    raise sw.SolidWorksGenerationError(
        f"{name}没有生成，已中止保存。" + "".join(f" {item}" for item in notes)
    )


def _revolve_cut_floor_mm3(sketch_data) -> float:
    """贴轴的孔或中孔至少要切掉一部分体积。倒角很小，只要求特征存在。"""

    ys = [point[1] for point in sketch_data.contour_mm]
    xs = [point[0] for point in sketch_data.contour_mm]
    if min(ys) > 0.05:
        return 0.0
    return 0.2 * math.pi * max(ys) ** 2 * max(0.0, max(xs) - min(xs))


def _keyway_expected_mm3(keyway) -> float:
    xs = [point[0] for point in keyway.contour_mm]
    ys = [point[1] for point in keyway.contour_mm]
    length = max(xs) - min(xs)
    depth = max(0.2, max(ys) - min(ys) - 0.6)
    return keyway.width_mm * depth * length


def _keyway_floor_mm3(keyway) -> float:
    return 0.2 * _keyway_expected_mm3(keyway)


def _close_volume(removed: float, expected: float) -> bool:
    if expected <= 0:
        return removed > 1.0
    return abs(removed - expected) <= max(20.0, 0.35 * expected)


def _removed_mm3(model, before: float | None) -> float | None:
    from turned_generate import volume_drop_mm3

    if before is None:
        return None
    after = _model_volume(model)
    if after is None:
        return None
    return volume_drop_mm3(before, after)


def _rebuild(model) -> None:
    try:
        model.EditRebuild3()
    except Exception:
        return


def _name_feature(feature, name: str) -> None:
    try:
        feature.Name = name
    except Exception:
        return


def _select_sketch(model, type_library, sketch) -> str:
    """选不中时返回原因。先按钣金孔的 SelectByID2，再退回 Select4。"""

    import solidworks_generator as sw

    model.ClearSelection2(True)
    name = str(getattr(sketch, "Name", "") or "")
    errors: list[str] = []
    if name:
        try:
            if model.Extension.SelectByID2(name, "SKETCH", 0.0, 0.0, 0.0, False, 0, None, 0):
                return ""
            errors.append("SelectByID2 返回空")
        except Exception as exc:
            errors.append(f"SelectByID2: {exc}")
    try:
        selected = bool(sw._as_interface(type_library, sketch, "IEntity").Select4(False, None))
    except Exception as exc:
        errors.append(f"Select4: {exc}")
        selected = False
    if selected:
        return ""
    return "；".join(errors) or "选择失败"


def _cylinder_position(model, type_library, cut) -> str:
    from turned_generate import axial_interval_position

    spans: list[tuple[float, float]] = []
    for face, surface in _cylindrical_faces(model, type_library):
        radius = _cylinder_radius_mm(surface)
        if radius is None or abs(radius - cut.radius_mm) > 0.35:
            continue
        span = _face_spans_mm(face)
        spans.extend(span)
    return axial_interval_position(spans, cut.start_offset_mm, cut.depth_mm)


def _face_spans_mm(face) -> list[tuple[float, float]]:
    try:
        raw = list(face.GetBox())
    except Exception:
        return []
    if len(raw) != 6:
        return []
    scale = 1000.0 if max(abs(value) for value in raw) < 5.0 else 1.0
    spans = []
    for index in range(3):
        start = raw[index] * scale
        end = raw[index + 3] * scale
        spans.append((min(start, end), max(start, end)))
    return spans


def _require_removed(model, before: float | None, name: str, floor_mm3: float) -> None:
    import solidworks_generator as sw

    from turned_generate import volume_drop_mm3

    if floor_mm3 <= 0 or before is None:
        return
    after = _model_volume(model)
    if after is None:
        return
    removed = volume_drop_mm3(before, after)
    if removed < floor_mm3:
        raise sw.SolidWorksGenerationError(
            f"{name}几乎没有切到材料（去掉 {removed:.1f} mm³，至少应去掉 {floor_mm3:.1f} mm³），已中止保存。"
        )


def _cut_axial(model, type_library, sketch_manager, feature_manager, plane, cut, across_flats: float) -> None:
    import solidworks_generator as sw

    from turned_generate import hex_area_mm2, judge_axial_cut

    sketch = _draw_circle(model, type_library, sketch_manager, plane, cut.radius_mm, cut.name)
    hole_mm3 = math.pi * cut.radius_mm * cut.radius_mm * cut.depth_mm
    if cut.outside and across_flats > 0:
        outside_mm3 = (hex_area_mm2(across_flats) - math.pi * cut.radius_mm ** 2) * cut.depth_mm
    else:
        outside_mm3 = hole_mm3
    offset_m = cut.start_offset_mm / 1000.0
    start_code = (
        sw.SW_START_CONDITION_OFFSET
        if cut.start_offset_mm > 0.05
        else sw.SW_START_CONDITION_SKETCH_PLANE
    )
    # 凸台拉伸用 Dir=False 沿基准面法向拉出。车削先沿同一方向，读不到体积时接受这一刀。
    preferred_flip = bool(cut.outside)
    if cut.start_offset_mm > 0.05:
        attempts = (
            (preferred_flip, False, False),
            (preferred_flip, False, True),
            (preferred_flip, True, False),
            (preferred_flip, True, True),
            (not preferred_flip, False, False),
            (not preferred_flip, False, True),
        )
    else:
        attempts = (
            (preferred_flip, False, False),
            (preferred_flip, True, False),
            (not preferred_flip, False, False),
            (not preferred_flip, True, False),
        )
    volume_before = _model_volume(model)
    notes: list[str] = []
    created = False
    for flip, reverse, flip_start in attempts:
        selected = _select_sketch(model, type_library, sketch)
        if selected:
            raise sw.SolidWorksGenerationError(f"无法选择{cut.name}草图，已中止保存。{selected}")
        feature, detail = _feature_cut(
            feature_manager,
            sd=True,
            flip=flip,
            reverse=reverse,
            end1=sw.SW_END_CONDITION_BLIND,
            end2=0,
            d1=cut.depth_mm / 1000.0,
            d2=0.0,
            t0=start_code,
            offset=offset_m,
            flip_start=flip_start,
        )
        model.ClearSelection2(True)
        _rebuild(model)
        label = f"Flip={flip} Dir={reverse} 起点反向={flip_start}"
        if feature is None:
            notes.append(f"{label}：{detail}")
            continue
        created = True
        removed = _removed_mm3(model, volume_before)
        sense = _cylinder_sense(model, type_library, cut.radius_mm)
        position = _cylinder_position(model, type_library, cut)
        verdict = judge_axial_cut(
            outside=cut.outside,
            removed_mm3=removed,
            outside_mm3=outside_mm3,
            hole_mm3=hole_mm3,
            sense=sense,
            position=position,
        )
        preferred = flip is preferred_flip and reverse is False and flip_start is False
        if verdict == "wrong" or (verdict == "unknown" and not preferred):
            notes.append(
                f"{label}：{verdict}，体积 {removed}，圆柱 {sense or '未知'}，位置 {position}"
            )
            _delete_feature(model, type_library, feature)
            _rebuild(model)
            continue
        _name_feature(feature, cut.name)
        return
    if not created:
        raise sw.SolidWorksGenerationError(
            f"{cut.name}的切除没有生成，已中止保存。"
            + "".join(f" {item}" for item in notes)
        )
    side = "圆外" if cut.outside else "圆内"
    raise sw.SolidWorksGenerationError(
        f"{cut.name}没有切在{side}，已中止保存。"
        + "".join(f" {item}" for item in notes)
    )


def sheet_metal_style_cut_args(
    *,
    sd: bool,
    flip: bool,
    reverse: bool,
    end1: int,
    end2: int,
    d1: float,
    d2: float,
    t0: int,
    offset: float,
    flip_start: bool,
) -> tuple:
    """26 个参数，顺序与钣金孔的 FeatureCut3 相同。

    第 18 个（下标 17）是 NormalCut。钣金孔必须 True；旋转轴和凸台拉伸
    这些固体必须 False，否则 SW2025 静默返回空，特征树里没有切除。
    """

    return (
        sd,
        flip,
        reverse,
        end1,
        end2,
        d1,
        d2,
        False,
        False,
        False,
        False,
        0.0,
        0.0,
        False,
        False,
        False,
        False,
        False,
        False,
        True,
        False,
        False,
        False,
        t0,
        offset,
        flip_start,
    )


def _feature_cut(
    feature_manager,
    *,
    sd: bool,
    flip: bool,
    reverse: bool,
    end1: int,
    end2: int,
    d1: float,
    d2: float,
    t0: int,
    offset: float,
    flip_start: bool,
) -> tuple[object | None, str]:
    """先调用钣金那条 FeatureCut3。失败时保留异常文字，再试多一个参数的 FeatureCut4。"""

    args = sheet_metal_style_cut_args(
        sd=sd,
        flip=flip,
        reverse=reverse,
        end1=end1,
        end2=end2,
        d1=d1,
        d2=d2,
        t0=t0,
        offset=offset,
        flip_start=flip_start,
    )
    errors: list[str] = []
    try:
        feature = feature_manager.FeatureCut3(*args)
    except Exception as exc:
        feature = None
        errors.append(f"FeatureCut3: {exc}")
    else:
        if feature is not None:
            return feature, ""
        errors.append("FeatureCut3: 返回空")
    try:
        feature = feature_manager.FeatureCut4(*args, True)
    except Exception as exc:
        errors.append(f"FeatureCut4: {exc}")
        return None, "；".join(errors)
    if feature is None:
        errors.append("FeatureCut4: 返回空")
        return None, "；".join(errors)
    return feature, ""


def _draw_circle(model, type_library, sketch_manager, plane, radius_mm: float, name: str):
    import solidworks_generator as sw

    known = {
        feature.Name
        for feature in sw._features(model, type_library)
        if feature.GetTypeName2() == "ProfileFeature"
    }
    model.ClearSelection2(True)
    if not sw._as_interface(type_library, plane, "IEntity").Select4(False, None):
        raise sw.SolidWorksGenerationError(f"无法选择{name}草图基准面。")
    sketch_manager.InsertSketch(True)
    previous = sketch_manager.AddToDB
    sketch_manager.AddToDB = True
    try:
        radius_m = radius_mm / 1000.0
        if sketch_manager.CreateCircle(0.0, 0.0, 0.0, radius_m, 0.0, 0.0) is None:
            raise sw.SolidWorksGenerationError(f"{name}的圆没有写进草图，已中止。")
    finally:
        sketch_manager.AddToDB = previous
    model.ClearSelection2(True)
    sketch_manager.InsertSketch(True)
    sketch = sw._latest_profile_sketch(model, type_library, known)
    if sketch is None:
        raise sw.SolidWorksGenerationError(f"SolidWorks 未能创建{name}草图。")
    _require_closed_contour(type_library, sketch, name)
    try:
        sketch.Name = name
    except Exception:
        pass
    return sketch


def _delete_feature(model, type_library, feature) -> None:
    import solidworks_generator as sw

    model.ClearSelection2(True)
    selected = False
    try:
        selected = bool(
            sw._as_interface(type_library, feature, "IEntity").Select4(False, None)
        )
    except Exception:
        selected = False
    if not selected:
        try:
            selected = bool(
                model.Extension.SelectByID2(
                    str(feature.Name), "BODYFEATURE", 0.0, 0.0, 0.0, False, 0, None, 0
                )
            )
        except Exception:
            selected = False
    if not selected:
        raise sw.SolidWorksGenerationError("切错的特征删不掉，已中止保存。")
    try:
        deleted = bool(model.Extension.DeleteSelection2(0))
    except Exception:
        deleted = False
    if not deleted:
        raise sw.SolidWorksGenerationError("切错的特征删不掉，已中止保存。")


def _model_volume(model) -> float | None:
    try:
        props = model.Extension.CreateMassProperty()
        if props is None:
            return None
        volume = float(props.Volume)
    except Exception:
        return None
    if volume <= 0:
        return None
    return volume


def _cylinder_sense(model, type_library, radius_mm: float) -> str | None:
    """半径接近 radius_mm 的圆柱面：external 材料在内，internal 是孔。"""

    found = None
    for face, surface in _cylindrical_faces(model, type_library):
        radius = _cylinder_radius_mm(surface)
        if radius is None or abs(radius - radius_mm) > 0.35:
            continue
        external = _face_points_outward(face)
        if external is True:
            return "external"
        if external is False:
            found = "internal"
    return found


def _cylindrical_faces(model, type_library):
    import solidworks_generator as sw

    try:
        part = sw._as_interface(type_library, model, "IPartDoc")
        bodies = part.GetBodies2(0, False) or ()
    except Exception:
        return
    for body in bodies:
        try:
            faces = body.GetFaces() or ()
        except Exception:
            continue
        for face in faces:
            try:
                surface = face.GetSurface()
            except Exception:
                continue
            try:
                if not surface.IsCylinder():
                    continue
            except Exception:
                continue
            yield face, surface


def _cylinder_radius_mm(surface) -> float | None:
    try:
        params = list(surface.CylinderParams)
    except Exception:
        return None
    if len(params) < 7:
        return None
    radius = abs(float(params[6]))
    if radius <= 0:
        return None
    if radius < 1.0:
        return radius * 1000.0
    return radius


def _face_points_outward(face) -> bool | None:
    try:
        sense = face.FaceInSurfaceSense
    except Exception:
        return None
    if isinstance(sense, bool):
        return sense
    try:
        return bool(int(sense))
    except Exception:
        return None


def _try_cosmetic_threads(model, type_library, plan: TurnedPartPlan, build) -> tuple[str, ...]:
    """化妆螺纹失败只记入手修，不丢掉已经合格的实体。"""

    targets: list[tuple[float, float, float, str]] = []
    seen: set[tuple[str, str]] = set()
    for turn in getattr(plan, "end_turns", ()) or ():
        major = _designation_major(turn.thread)
        if major is None:
            continue
        key = ("外", turn.thread)
        if key in seen:
            continue
        seen.add(key)
        targets.append((turn.radius_mm, major, turn.length_mm, turn.thread))
    for hole in plan.holes:
        thread = getattr(hole, "thread", "") or ""
        major = _designation_major(thread)
        if major is None:
            continue
        key = ("内", thread)
        if key in seen:
            continue
        seen.add(key)
        targets.append((hole.diameter_mm / 2.0, major, hole.depth_mm, thread))
    for thread in plan.threads:
        if "外" not in (thread.text or ""):
            continue
        major = _designation_major(thread.designation)
        if major is None:
            continue
        root = thread.designation.split("×")[0]
        if any(item[3].split("×")[0] == root for item in targets):
            continue
        targets.append((major / 2.0, major, 8.0, thread.designation))
    notes: list[str] = []
    for face_radius, major, length, designation in targets:
        try:
            ok = _insert_cosmetic(
                model,
                type_library,
                face_radius,
                major,
                max(length, 1.0),
                designation,
            )
        except Exception:
            ok = False
        if not ok:
            notes.append(f"化妆螺纹未生成：{designation}")
    return tuple(notes)


def _insert_cosmetic(model, type_library, face_radius_mm, major_mm, length_mm, designation) -> bool:
    edge = _find_circular_edge(model, type_library, face_radius_mm)
    if edge is None:
        return False
    model.ClearSelection2(True)
    try:
        selected = bool(edge.Select4(False, None))
    except Exception:
        selected = False
    if not selected:
        return False
    try:
        result = model.InsertCosmeticThread3(
            0,
            major_mm / 1000.0,
            length_mm / 1000.0,
            designation,
            True,
            designation,
        )
    except Exception:
        model.ClearSelection2(True)
        return False
    model.ClearSelection2(True)
    return result is not False


def _find_circular_edge(model, type_library, radius_mm: float):
    for face, surface in _cylindrical_faces(model, type_library):
        radius = _cylinder_radius_mm(surface)
        if radius is None or abs(radius - radius_mm) > 0.35:
            continue
        try:
            edges = face.GetEdges() or ()
        except Exception:
            continue
        for edge in edges:
            try:
                curve = edge.GetCurve()
                if curve is not None and curve.IsCircle():
                    return edge
            except Exception:
                continue
    return None


def _designation_major(designation: str) -> float | None:
    match = re.search(r"M\s*(\d+(?:\.\d+)?)", designation or "", re.IGNORECASE)
    if match is None:
        return None
    return float(match.group(1))


def _thread_property(plan: TurnedPartPlan) -> str:
    hole_threads = {getattr(hole, "thread", "") or "" for hole in plan.holes}
    turn_threads = {
        getattr(turn, "thread", "") or "" for turn in getattr(plan, "end_turns", ()) or ()
    }
    parts: list[str] = []
    for item in plan.threads:
        name = item.designation
        root = name.split("×")[0]
        if any(root == turn.split("×")[0] for turn in turn_threads if turn) or "外" in (
            item.text or ""
        ):
            parts.append(f"{name}外")
        elif name in hole_threads or "内" in (item.text or "") or "深" in (item.text or ""):
            parts.append(f"{name}内")
        else:
            parts.append(name)
    return " / ".join(parts)


def _keyway_property(keyway) -> str:
    place = "中孔" if keyway.on_bore else "外圆"
    return (
        f"{keyway.width_mm:g}×{keyway.depth_mm:g}×{keyway.length_mm:g}"
        f"@{keyway.start_mm:.2f}{place}"
    )


def _write_turned_properties(
    model,
    label: str,
    length_mm: float,
    plan: TurnedPartPlan,
    extra_hand: tuple[str, ...] = (),
) -> None:
    try:
        manager = model.Extension.CustomPropertyManager("")
        manager.Add3("生成", 30, label, 1)
        manager.Add3("轴向长度mm", 30, f"{length_mm:.2f}", 1)
        if plan.threads:
            manager.Add3("螺纹", 30, _thread_property(plan), 1)
        if plan.keyways:
            manager.Add3(
                "键槽",
                30,
                "；".join(_keyway_property(item) for item in plan.keyways),
                1,
            )
        if plan.knurl:
            manager.Add3("外圆滚花", 30, plan.knurl, 1)
        if plan.teeth:
            manager.Add3("齿数", 30, str(int(plan.teeth)), 1)
        if plan.chamfer_mm:
            manager.Add3("倒角", 30, f"C{plan.chamfer_mm:g}", 1)
        hand: list[str] = []
        for item in tuple(getattr(plan, "hand_finish", ()) or ()) + tuple(extra_hand):
            text = str(item).strip()
            if text and text not in hand:
                hand.append(text)
        if hand:
            manager.Add3("需手修", 30, "；".join(hand), 1)
    except Exception:
        return
