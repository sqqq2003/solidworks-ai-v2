"""Roller, sprocket and shaft-end geometry for generated roller parts.

Pure geometry; nothing here calls COM or needs a SolidWorks session.
``solidworks_generator`` re-exports every name for existing callers.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


SW_ARC_DIRECTION_CLOCKWISE = -1
SW_ARC_DIRECTION_COUNTERCLOCKWISE = 1
DEFAULT_CHAIN_PITCH_MM = 12.7
# 4 分（12.7 mm）链常用 08B 滚子，滚子直径约为节距的 0.67 倍。
CHAIN_ROLLER_DIAMETER_RATIO = 0.67
# 参考件《201不锈钢滚筒-动力-壁厚1.2mm-双排链轮4分14齿-Φ50x280》草图1 / 草图6 实测。
SPROCKET_SEAT_HALF_ANGLE_DEG = 67.5
SPROCKET_SEAT_RADIUS_FACTOR = 0.529
SPROCKET_SEAT_RADIUS_OFFSET = 0.0
SPROCKET_TIP_EXTRA_RATIO = 0.7423
# 4 分 14 齿参考件：分度圆半径 28.25（非理论 12.7/(2·sin(π/14))）、齿沟 4.5、齿顶 33.25。
SPROCKET_PITCH_RADIUS_REF_MM = 28.25
SPROCKET_SEAT_RADIUS_REF_MM = 4.5
SPROCKET_TIP_RADIUS_REF_MM = 33.25
SPROCKET_ROOT_LAND_RADIUS_REF_MM = 23.75  # φ47.50 齿根辅助圆
# 双排轴向（相对 12.7 mm 节距缩放）：齿顶宽 5、根宽 7、两排根间距 15、轮毂颈 15、R5。
SPROCKET_ROW_WIDTH_REF_MM = 5.0
SPROCKET_TOOTH_BEVEL_REF_MM = 1.0
SPROCKET_ROW_BASE_GAP_REF_MM = 15.0
SPROCKET_HUB_LEAD_REF_MM = 15.0
SPROCKET_HUB_TRANSITION_REF_MM = 5.0
# 仅向轮毂内侧过切；外侧必须与链轮端面齐平，绝不可切入 Ø15 轴头。
SPROCKET_CUT_OVERSHOOT_REF_MM = 1.0
SPROCKET_ROOT_CLEARANCE_MM = 1.0
# 缩径轮毂：参考件 Ø37。
HUB_DIAMETER_RATIO = 0.74
HUB_MIN_RADIAL_WALL_MM = 2.0
HUB_RADIUS_REF_MM = 18.5
# 轴头 Ø15；无链轮端：R5 + Ø18 台阶（长 5.5）+ R0.5 进光轴。
SHAFT_JOURNAL_DIAMETER_EXTRA_MM = 3.0
SHAFT_IDLE_STEP_RADIUS_REF_MM = 9.0
SHAFT_IDLE_STEP_LENGTH_REF_MM = 5.5
SHAFT_IDLE_FILLET_REF_MM = 5.0
SHAFT_IDLE_CORNER_RADIUS_REF_MM = 0.5
SHAFT_IDLE_EXPOSED_REF_MM = 5.0
# 仅用于测试折线展开；生成草图里的圆角必须是单段 CreateArc。
TRANSITION_ARC_SEGMENTS = 12
# 无动力筒身端面外圆角（图纸为真圆弧，不是倒角）。
UNPOWERED_BARREL_FILLET_REF_MM = 2.0
# 无动力批量标准：轴头光轴 → 台阶 → 筒身。台阶外径默认 = 轴径+3（与动力轴颈增量同一规则），
# 随每张图自己的轴径/外径/伸出量变化，不绑死某一张样例图。
UNPOWERED_STEP_DIAMETER_EXTRA_MM = SHAFT_JOURNAL_DIAMETER_EXTRA_MM
DEFAULT_SHAFT_THREAD_DESIGNATION = "M10"
SHAFT_THREAD_DEPTH_MM = 20.0
SHAFT_THREAD_SPECS_MM = {
    "M8": 6.8,
    "M10": 8.5,
}


@dataclass(frozen=True)
class RollerSpec:
    roller_type: str
    overall_length_mm: float
    outer_diameter_mm: float
    wall_thickness_mm: float
    shaft_diameter_mm: float
    shaft_projection_mm: float
    sprocket_teeth: int | None = None
    chain_pitch_mm: float | None = None
    # 图纸上轴端光轴（无台阶）外露长度，用于确定轴端台阶与挡圈槽位置。
    shaft_exposed_mm: float | None = None
    # 轴端螺纹底孔规格，例如 ``M8`` / ``M10``。
    shaft_thread_designation: str = DEFAULT_SHAFT_THREAD_DESIGNATION
    # 无动力轴端台阶外径；图上有中间直径标注时用图纸值，否则按轴径+3。
    shaft_step_diameter_mm: float | None = None


@dataclass(frozen=True)
class RollerLayout:
    """滚筒轴向布局（坐标相对滚筒中心，单位 mm）。

    动力滚筒按参考件建模：筒身为空心筒体，靠链轮一端是缩径轮毂，
    轮毂上排两排真实齿形的链轮；两端是带螺纹底孔和挡圈槽的轴头。
    """

    barrel_length_mm: float
    body_min_mm: float
    body_max_mm: float
    sprocket_outer_diameter_mm: float | None
    sprocket_root_diameter_mm: float | None
    sprocket_row_width_mm: float | None
    sprocket_row_gap_mm: float | None
    sprocket_rows_mm: tuple[tuple[float, float], ...]
    cavity_spans_mm: tuple[tuple[float, float], ...]
    tube_min_mm: float | None = None
    tube_max_mm: float | None = None
    hub_min_mm: float | None = None
    hub_max_mm: float | None = None
    hub_diameter_mm: float | None = None
    sprocket_cut_span_mm: tuple[float, float] | None = None
    sprocket_pitch_radius_mm: float | None = None
    sprocket_seat_radius_mm: float | None = None

    @property
    def tube_length_mm(self) -> float:
        if self.tube_min_mm is None or self.tube_max_mm is None:
            return self.barrel_length_mm
        return self.tube_max_mm - self.tube_min_mm


def _add_point(
    first: tuple[float, float],
    second: tuple[float, float],
) -> tuple[float, float]:
    return (first[0] + second[0], first[1] + second[1])


def _scale_point(
    point: tuple[float, float],
    factor: float,
) -> tuple[float, float]:
    return (point[0] * factor, point[1] * factor)


def _rotate_point(
    point: tuple[float, float],
    angle: float,
) -> tuple[float, float]:
    cos_angle = math.cos(angle)
    sin_angle = math.sin(angle)
    return (
        point[0] * cos_angle - point[1] * sin_angle,
        point[0] * sin_angle + point[1] * cos_angle,
    )


def _mirror_point(
    point: tuple[float, float],
    axis: tuple[float, float],
) -> tuple[float, float]:
    """镜像到过原点、方向为 ``axis`` 的直线上（轴为方向向量）。"""

    projection = point[0] * axis[0] + point[1] * axis[1]
    return (
        2.0 * projection * axis[0] - point[0],
        2.0 * projection * axis[1] - point[1],
    )


def _ray_circle_far_hit(
    origin: tuple[float, float],
    direction: tuple[float, float],
    radius: float,
) -> float:
    """返回从 ``origin`` 沿 ``direction`` 命中 ``radius`` 圆的较远交点距离。"""

    b = 2.0 * (origin[0] * direction[0] + origin[1] * direction[1])
    c = origin[0] ** 2 + origin[1] ** 2 - radius ** 2
    discriminant = b * b - 4.0 * c
    if discriminant < 0.0:
        raise ValueError("链轮齿形参数无法与齿顶圆相交，请检查齿数与节距。")
    return (-b + math.sqrt(discriminant)) / 2.0


def sprocket_geometry(
    teeth: int,
    pitch_mm: float,
) -> tuple[float, float, float]:
    """返回 (分度圆半径, 齿沟圆弧半径, 齿顶圆半径)。

    4 分 14 齿严格对齐参考件草图6：分度圆半径 28.25、齿沟 4.5、齿顶 33.25。
    """

    if (
        teeth == 14
        and math.isclose(pitch_mm, DEFAULT_CHAIN_PITCH_MM, abs_tol=1e-6)
    ):
        return (
            SPROCKET_PITCH_RADIUS_REF_MM,
            SPROCKET_SEAT_RADIUS_REF_MM,
            SPROCKET_TIP_RADIUS_REF_MM,
        )
    half_tooth_angle = math.pi / teeth
    pitch_radius = pitch_mm / (2.0 * math.sin(half_tooth_angle))
    roller_diameter = CHAIN_ROLLER_DIAMETER_RATIO * pitch_mm
    seat_radius = (
        SPROCKET_SEAT_RADIUS_FACTOR * roller_diameter
        + SPROCKET_SEAT_RADIUS_OFFSET * roller_diameter ** (1.0 / 3.0)
    )
    tip_radius = pitch_radius + SPROCKET_TIP_EXTRA_RATIO * pitch_mm / 2.0
    return pitch_radius, seat_radius, tip_radius


def _pitch_scale(pitch_mm: float) -> float:
    return pitch_mm / DEFAULT_CHAIN_PITCH_MM


def sprocket_tooth_pockets(
    teeth: int,
    pitch_radius: float,
    seat_radius: float,
    tip_radius: float,
) -> tuple[tuple[dict[str, object], ...], ...]:
    """返回每个齿槽的闭合轮廓（直线与圆弧），与参考件齿形一致。

    每个齿槽由齿沟圆弧（135°，包住链滚子）、两条与齿沟圆弧相切的齿侧直线
    和齿顶圆上的一小段圆弧组成。切掉这些齿槽即得到 14 齿链轮齿形。
    """

    if teeth < 6:
        raise ValueError("链轮齿数必须是至少 6 的整数。")
    half_span = math.radians(SPROCKET_SEAT_HALF_ANGLE_DEG)
    pockets: list[tuple[dict[str, object], ...]] = []
    for index in range(teeth):
        angle = 2.0 * math.pi * index / teeth
        outward = (math.cos(angle), math.sin(angle))
        inward = (-outward[0], -outward[1])
        seat_center = _scale_point(outward, pitch_radius)
        seat_minus = _add_point(
            seat_center,
            _scale_point(_rotate_point(inward, -half_span), seat_radius),
        )
        seat_plus = _add_point(
            seat_center,
            _scale_point(_rotate_point(inward, half_span), seat_radius),
        )
        flank_direction = _rotate_point(inward, half_span + math.pi / 2.0)
        flank_length = _ray_circle_far_hit(
            seat_plus,
            flank_direction,
            tip_radius,
        )
        tip_plus = _add_point(
            seat_plus,
            _scale_point(flank_direction, flank_length),
        )
        tip_minus = _mirror_point(tip_plus, outward)
        pockets.append(
            (
                {
                    "kind": "arc",
                    "center": seat_center,
                    "radius": seat_radius,
                    "start": seat_minus,
                    "end": seat_plus,
                    "direction": SW_ARC_DIRECTION_COUNTERCLOCKWISE,
                },
                {"kind": "line", "start": seat_plus, "end": tip_plus},
                {
                    "kind": "arc",
                    "center": (0.0, 0.0),
                    "radius": tip_radius,
                    "start": tip_plus,
                    "end": tip_minus,
                    "direction": SW_ARC_DIRECTION_COUNTERCLOCKWISE,
                },
                {"kind": "line", "start": tip_minus, "end": seat_minus},
            )
        )
    return tuple(pockets)


def sprocket_pocket_area(pocket: tuple[dict[str, object], ...]) -> float:
    """单个齿槽的截面积（用于校验切齿后体积减少量）。"""

    area = 0.0
    for curve in pocket:
        start = curve["start"]
        end = curve["end"]
        area += start[0] * end[1] - end[0] * start[1]  # type: ignore[index]
    area = abs(area) / 2.0
    for curve in pocket:
        if curve["kind"] != "arc":
            continue
        radius = float(curve["radius"])  # type: ignore[arg-type]
        start = curve["start"]
        end = curve["end"]
        center = curve["center"]
        start_angle = math.atan2(
            start[1] - center[1],  # type: ignore[index]
            start[0] - center[0],  # type: ignore[index]
        )
        end_angle = math.atan2(
            end[1] - center[1],  # type: ignore[index]
            end[0] - center[0],  # type: ignore[index]
        )
        sweep = end_angle - start_angle
        if curve["direction"] == SW_ARC_DIRECTION_COUNTERCLOCKWISE:
            while sweep <= 0.0:
                sweep += 2.0 * math.pi
        else:
            while sweep >= 0.0:
                sweep -= 2.0 * math.pi
        if abs(sweep) >= 2.0 * math.pi - 1e-9:
            return math.pi * radius * radius
        area += 0.5 * radius * radius * (sweep - math.sin(sweep))
    return area


def _mm(value: float) -> float:
    """草图坐标统一到 1e-6 mm，保证线段/圆弧端点重合。"""

    return round(value, 6)


def _journal_radius(spec: RollerSpec) -> float:
    """轴头最外端外径：动力参考件 Ø15；无动力图纸为 Ø12 光轴头。"""

    if spec.roller_type == "无动力滚筒":
        return min(
            spec.shaft_diameter_mm / 2.0,
            spec.outer_diameter_mm / 2.0 - 1.0,
        )
    return min(
        spec.shaft_diameter_mm / 2.0 + SHAFT_JOURNAL_DIAMETER_EXTRA_MM / 2.0,
        spec.outer_diameter_mm / 2.0 - 1.0,
    )


def unpowered_end_layout(spec: RollerSpec) -> tuple[float, float, float, float]:
    """无动力轴端批量标准：``(光轴长, 台阶长, 台阶半径, 每端总伸出)``。

    对**每张图**都按该图的 ``RollerSpec`` 计算，不绑死某一张样例：
    - 光轴外径 = 图上轴径
    - 台阶外径 = 图上中间直径，否则 轴径+3
    - 光轴长 = 图上外露；若只标了一段伸出，则台阶长默认等于光轴长
    - 总伸出 = max(图上伸出, 光轴长+台阶长)
    """

    tip_radius = _journal_radius(spec)
    if spec.shaft_step_diameter_mm is not None and spec.shaft_step_diameter_mm > 0:
        step_diameter = float(spec.shaft_step_diameter_mm)
    else:
        step_diameter = float(spec.shaft_diameter_mm) + UNPOWERED_STEP_DIAMETER_EXTRA_MM
    step_radius = min(
        step_diameter / 2.0,
        spec.outer_diameter_mm / 2.0 - UNPOWERED_BARREL_FILLET_REF_MM - 0.5,
    )
    step_radius = max(step_radius, tip_radius + 0.5)
    exposed = (
        float(spec.shaft_exposed_mm)
        if spec.shaft_exposed_mm is not None
        else SHAFT_IDLE_EXPOSED_REF_MM
    )
    exposed = min(max(exposed, 2.0), max(2.0, float(spec.shaft_projection_mm)))
    labeled_projection = float(spec.shaft_projection_mm)
    if labeled_projection > exposed + 0.05:
        # 图上「伸出」已大于光轴段 → 余量作为台阶长（该图自己的数）。
        step_length = labeled_projection - exposed
        total = labeled_projection
    else:
        # 常见：只标了光轴段长度。批量标准仍做一级台阶，台阶长取与光轴段相同。
        step_length = exposed
        total = exposed + step_length
    return exposed, step_length, step_radius, total


def roller_axial_extents(spec: RollerSpec) -> tuple[float, float, float, float]:
    """返回 ``(tip_half, body_min, body_max, barrel_length)``，坐标相对中心。

    动力 / 无动力图纸总长均为端到端（含轴头）；筒身 = 总长 − 2×每端伸出。
    """

    tip_half = float(spec.overall_length_mm) / 2.0
    if spec.roller_type == "无动力滚筒":
        _, _, _, stickout = unpowered_end_layout(spec)
    else:
        stickout = float(spec.shaft_projection_mm)
    barrel_length = float(spec.overall_length_mm) - 2.0 * stickout
    body_min = -barrel_length / 2.0
    body_max = barrel_length / 2.0
    return tip_half, body_min, body_max, barrel_length


def roller_revolve_segments(
    spec: RollerSpec,
    layout: RollerLayout,
) -> tuple[dict[str, object], ...]:
    """滚筒回转截面。圆角必须是单段 ``arc``（SolidWorks CreateArc），禁止折线冒充。"""

    tip_half, _, _, _ = roller_axial_extents(spec)
    half = _mm(tip_half)
    barrel_radius = _mm(spec.outer_diameter_mm / 2.0)
    journal_radius = _mm(_journal_radius(spec))
    body_min = _mm(layout.body_min_mm)
    body_max = _mm(layout.body_max_mm)
    pitch = spec.chain_pitch_mm or DEFAULT_CHAIN_PITCH_MM
    scale = _pitch_scale(pitch)

    def line(
        start: tuple[float, float],
        end: tuple[float, float],
    ) -> dict[str, object]:
        return {
            "kind": "line",
            "start": (_mm(start[0]), _mm(start[1])),
            "end": (_mm(end[0]), _mm(end[1])),
        }

    def arc(
        center: tuple[float, float],
        radius: float,
        start: tuple[float, float],
        end: tuple[float, float],
        direction: int,
    ) -> dict[str, object]:
        center_m = (_mm(center[0]), _mm(center[1]))
        start_m = (_mm(start[0]), _mm(start[1]))
        end_m = (_mm(end[0]), _mm(end[1]))
        radius_m = _mm(radius)
        # 强制端点落在圆上，避免闭合轮廓识别失败。
        def _on_circle(point: tuple[float, float]) -> tuple[float, float]:
            dx = point[0] - center_m[0]
            dy = point[1] - center_m[1]
            length = math.hypot(dx, dy)
            if length <= 1e-12:
                return point
            return (
                _mm(center_m[0] + radius_m * dx / length),
                _mm(center_m[1] + radius_m * dy / length),
            )

        return {
            "kind": "arc",
            "center": center_m,
            "radius": radius_m,
            "start": _on_circle(start_m),
            "end": _on_circle(end_m),
            "direction": direction,
        }

    if layout.hub_diameter_mm is None or layout.tube_max_mm is None:
        # 无动力批量标准：光轴头 → 台阶 → 筒身外圆角（参数来自该图 RollerSpec）。
        exposed, step_length, step_radius_mm, _stickout = unpowered_end_layout(spec)
        step_radius = _mm(step_radius_mm)
        fillet = _mm(
            min(
                UNPOWERED_BARREL_FILLET_REF_MM * scale,
                (body_max - body_min) * 0.05,
                barrel_radius - step_radius - 0.2,
            )
        )
        fillet = max(fillet, 0.5)
        x_exposed_left = _mm(-half + exposed)
        x_step_left = _mm(-half + exposed + step_length)
        x_exposed_right = _mm(half - exposed)
        x_step_right = _mm(half - exposed - step_length)
        segments: list[dict[str, object]] = []

        def add_line(
            start: tuple[float, float],
            end: tuple[float, float],
        ) -> tuple[float, float]:
            segment = line(start, end)
            if segments:
                previous_end = segments[-1]["end"]
                assert isinstance(previous_end, tuple)
                segment = {
                    **segment,
                    "start": (_mm(previous_end[0]), _mm(previous_end[1])),
                }
            segments.append(segment)
            end_point = segment["end"]
            assert isinstance(end_point, tuple)
            return end_point  # type: ignore[return-value]

        def add_arc(
            center: tuple[float, float],
            radius: float,
            start: tuple[float, float],
            end: tuple[float, float],
            direction: int,
        ) -> tuple[float, float]:
            segment = arc(center, radius, start, end, direction)
            if segments:
                previous_end = segments[-1]["end"]
                assert isinstance(previous_end, tuple)
                center_m = segment["center"]
                radius_m = float(segment["radius"])  # type: ignore[arg-type]
                assert isinstance(center_m, tuple)
                dx = previous_end[0] - center_m[0]
                dy = previous_end[1] - center_m[1]
                length = math.hypot(dx, dy)
                if length > 1e-12:
                    projected = (
                        _mm(center_m[0] + radius_m * dx / length),
                        _mm(center_m[1] + radius_m * dy / length),
                    )
                    segments[-1] = {**segments[-1], "end": projected}
                    segment = {**segment, "start": projected}
            segments.append(segment)
            end_point = segment["end"]
            assert isinstance(end_point, tuple)
            return end_point  # type: ignore[return-value]

        left_vert = (body_min, barrel_radius - fillet)
        left_od = (body_min + fillet, barrel_radius)
        right_od = (body_max - fillet, barrel_radius)
        right_vert = (body_max, barrel_radius - fillet)
        cursor = add_line((-half, 0.0), (-half, journal_radius))
        cursor = add_line(cursor, (x_exposed_left, journal_radius))
        # Φ12 → Φ15 台阶
        if step_radius > journal_radius + 1e-6:
            cursor = add_line(cursor, (x_exposed_left, step_radius))
        cursor = add_line(cursor, (x_step_left, step_radius))
        if abs(x_step_left - body_min) > 1e-6:
            cursor = add_line(cursor, (body_min, step_radius))
        cursor = add_line(cursor, left_vert)
        cursor = add_arc(
            (body_min + fillet, barrel_radius - fillet),
            fillet,
            cursor,
            left_od,
            SW_ARC_DIRECTION_CLOCKWISE,
        )
        cursor = add_line(cursor, right_od)
        cursor = add_arc(
            (body_max - fillet, barrel_radius - fillet),
            fillet,
            cursor,
            right_vert,
            SW_ARC_DIRECTION_CLOCKWISE,
        )
        cursor = add_line(cursor, (body_max, step_radius))
        if abs(body_max - x_step_right) > 1e-6:
            cursor = add_line(cursor, (x_step_right, step_radius))
        cursor = add_line(cursor, (x_exposed_right, step_radius))
        if step_radius > journal_radius + 1e-6:
            cursor = add_line(cursor, (x_exposed_right, journal_radius))
        cursor = add_line(cursor, (half, journal_radius))
        cursor = add_line(cursor, (half, 0.0))
        add_line(cursor, (-half, 0.0))
        return tuple(segments)

    hub_radius = _mm(layout.hub_diameter_mm / 2.0)
    tip_radius = _mm(
        layout.sprocket_outer_diameter_mm / 2.0
        if layout.sprocket_outer_diameter_mm is not None
        else hub_radius
    )
    root_land = _mm(
        layout.sprocket_root_diameter_mm / 2.0
        if layout.sprocket_root_diameter_mm is not None
        else SPROCKET_ROOT_LAND_RADIUS_REF_MM * scale
    )
    bevel = _mm(SPROCKET_TOOTH_BEVEL_REF_MM * scale)
    drive_fillet = _mm(SPROCKET_HUB_TRANSITION_REF_MM * scale)
    idle_fillet = _mm(SHAFT_IDLE_FILLET_REF_MM * scale)
    corner_r = _mm(SHAFT_IDLE_CORNER_RADIUS_REF_MM * scale)
    step_span = _mm(SHAFT_IDLE_STEP_LENGTH_REF_MM * scale)
    step_radius = _mm(
        min(
            SHAFT_IDLE_STEP_RADIUS_REF_MM * scale,
            barrel_radius - idle_fillet - 0.5,
        )
    )
    step_radius = max(step_radius, journal_radius + corner_r + 0.2)
    exposed = (
        spec.shaft_exposed_mm
        if spec.shaft_exposed_mm is not None
        else SHAFT_IDLE_EXPOSED_REF_MM
    )
    exposed = _mm(min(max(exposed, 2.0), max(2.0, spec.shaft_projection_mm - 1.0)))
    hub_min = _mm(float(layout.hub_min_mm))
    tube_max = _mm(float(layout.tube_max_mm))

    # 无链轮端相对 body_min 布置，避免轴头伸出量变化后 R5 跑到端面外侧。
    # 参考件：body_min=-126.5 时 R5 在 -129.5→-124.5。
    x_r5_barrel = _mm(body_min + 2.0 * scale)
    x_r5_hub = _mm(x_r5_barrel - idle_fillet)
    x_exposed = _mm(-half + exposed)
    x_corner = _mm(x_exposed + corner_r)
    # 竖边落到 R5 内侧；若轴头较短则夹紧，保证顺序 -half ≤ exposed ≤ corner ≤ r5_hub。
    if x_r5_hub < x_corner + 0.2:
        x_r5_hub = _mm(x_corner + 0.2)
        x_r5_barrel = _mm(x_r5_hub + idle_fillet)
    idle_shoulder = _mm(barrel_radius - idle_fillet)

    segments: list[dict[str, object]] = []

    def add_line(start: tuple[float, float], end: tuple[float, float]) -> tuple[float, float]:
        segment = line(start, end)
        segments.append(segment)
        end_point = segment["end"]
        assert isinstance(end_point, tuple)
        return end_point  # type: ignore[return-value]

    def add_arc(
        center: tuple[float, float],
        radius: float,
        start: tuple[float, float],
        end: tuple[float, float],
        direction: int,
    ) -> tuple[float, float]:
        segment = arc(center, radius, start, end, direction)
        if segments:
            previous_end = segments[-1]["end"]
            assert isinstance(previous_end, tuple)
            # 上一段终点投影到本圆弧上，既闭合又满足 CreateArc 半径约束。
            center_m = segment["center"]
            radius_m = float(segment["radius"])  # type: ignore[arg-type]
            assert isinstance(center_m, tuple)
            dx = previous_end[0] - center_m[0]
            dy = previous_end[1] - center_m[1]
            length = math.hypot(dx, dy)
            if length > 1e-12:
                projected = (
                    _mm(center_m[0] + radius_m * dx / length),
                    _mm(center_m[1] + radius_m * dy / length),
                )
                segments[-1] = {**segments[-1], "end": projected}
                segment = {**segment, "start": projected}
        segments.append(segment)
        end_point = segment["end"]
        assert isinstance(end_point, tuple)
        return end_point  # type: ignore[return-value]

    cursor = add_line((-half, 0.0), (-half, journal_radius))
    cursor = add_line(cursor, (x_exposed, journal_radius))
    if corner_r > 0.05 and step_radius >= journal_radius + 2.0 * corner_r - 1e-9:
        r_arc = _mm(step_radius - corner_r)
        cursor = add_line(cursor, (x_exposed, r_arc))
        cursor = add_arc(
            (x_corner, r_arc),
            corner_r,
            cursor,
            (x_corner, step_radius),
            SW_ARC_DIRECTION_CLOCKWISE,
        )
    else:
        cursor = add_line(cursor, (x_corner, step_radius))
    cursor = add_line(cursor, (x_r5_hub, step_radius))
    if abs(step_radius - idle_shoulder) > 1e-9:
        cursor = add_line(cursor, (x_r5_hub, idle_shoulder))
    cursor = add_arc(
        (x_r5_barrel, idle_shoulder),
        idle_fillet,
        cursor,
        (x_r5_barrel, barrel_radius),
        SW_ARC_DIRECTION_CLOCKWISE,
    )
    cursor = add_line(cursor, (tube_max, barrel_radius))

    drive_fillet = min(drive_fillet, abs(hub_min - tube_max), barrel_radius - hub_radius)
    drive_shoulder = _mm(barrel_radius - drive_fillet)
    if drive_fillet > 0.2:
        cursor = add_arc(
            (tube_max, drive_shoulder),
            drive_fillet,
            cursor,
            (hub_min, drive_shoulder),
            SW_ARC_DIRECTION_CLOCKWISE,
        )
        if drive_shoulder - hub_radius > 1e-6:
            cursor = add_line(cursor, (hub_min, hub_radius))
    else:
        cursor = add_line(cursor, (hub_min, hub_radius))

    rows = layout.sprocket_rows_mm
    for index, (row_start, row_end) in enumerate(rows):
        row_start_m = _mm(row_start)
        row_end_m = _mm(row_end)
        base_start = _mm(row_start_m - bevel)
        base_end = _mm(row_end_m + bevel)
        is_last = index == len(rows) - 1
        if is_last:
            base_end = body_max
        if abs(cursor[0] - base_start) > 1e-9 or abs(cursor[1] - hub_radius) > 1e-9:
            cursor = add_line(cursor, (base_start, hub_radius))
        cursor = add_line(cursor, (base_start, root_land))
        cursor = add_line(cursor, (row_start_m, tip_radius))
        cursor = add_line(cursor, (row_end_m, tip_radius))
        cursor = add_line(cursor, (base_end, root_land))
        if is_last:
            cursor = add_line(cursor, (body_max, journal_radius))
            cursor = add_line(cursor, (half, journal_radius))
            cursor = add_line(cursor, (half, 0.0))
            add_line(cursor, (-half, 0.0))
        else:
            cursor = add_line(cursor, (base_end, hub_radius))

    return tuple(segments)


def roller_revolve_profile(
    spec: RollerSpec,
    layout: RollerLayout,
) -> tuple[tuple[float, float], ...]:
    """滚筒回转截面折线顶点（测试与兼容）；圆弧按密化点展开。"""

    points: list[tuple[float, float]] = []
    for segment in roller_revolve_segments(spec, layout):
        start = segment["start"]
        assert isinstance(start, tuple)
        if not points:
            points.append(start)  # type: ignore[arg-type]
        if segment["kind"] == "line":
            end = segment["end"]
            assert isinstance(end, tuple)
            points.append(end)  # type: ignore[arg-type]
            continue
        center = segment["center"]
        radius = float(segment["radius"])  # type: ignore[arg-type]
        end = segment["end"]
        assert isinstance(center, tuple) and isinstance(end, tuple)
        start_angle = math.atan2(start[1] - center[1], start[0] - center[0])
        end_angle = math.atan2(end[1] - center[1], end[0] - center[0])
        sweep = end_angle - start_angle
        if segment["direction"] == SW_ARC_DIRECTION_COUNTERCLOCKWISE:
            while sweep <= 0.0:
                sweep += 2.0 * math.pi
        else:
            while sweep >= 0.0:
                sweep -= 2.0 * math.pi
        for index in range(1, TRANSITION_ARC_SEGMENTS + 1):
            angle = start_angle + sweep * (index / TRANSITION_ARC_SEGMENTS)
            points.append(
                (
                    center[0] + radius * math.cos(angle),
                    center[1] + radius * math.sin(angle),
                )
            )
    # 闭合边上的重复原点去掉，保持旧接口「从轴心起止」。
    if len(points) >= 2 and points[0] == points[-1]:
        points = points[:-1]
    return tuple(points)


def validate_roller_spec(spec: RollerSpec) -> float:
    if spec.roller_type not in ("动力滚筒", "无动力滚筒"):
        raise ValueError("滚筒类型无效。")
    dimensions = (
        ("滚筒总长", spec.overall_length_mm),
        ("滚筒外径", spec.outer_diameter_mm),
        ("筒壁厚", spec.wall_thickness_mm),
        ("轴径", spec.shaft_diameter_mm),
        ("轴头伸出量", spec.shaft_projection_mm),
    )
    for label, value in dimensions:
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"{label}必须是大于 0 的有限数值。")
    if spec.wall_thickness_mm * 2 >= spec.outer_diameter_mm:
        raise ValueError("筒壁厚必须小于滚筒外径的一半。")
    inner_diameter = spec.outer_diameter_mm - 2 * spec.wall_thickness_mm
    if spec.shaft_diameter_mm >= inner_diameter:
        raise ValueError("轴径必须小于筒体内径，才能保留中空筒壁。")

    _, _, _, barrel_length = roller_axial_extents(spec)
    if barrel_length <= 2 * spec.wall_thickness_mm:
        raise ValueError("两端轴头伸出量过大，无法保留有效筒身和端盖。")

    if spec.shaft_exposed_mm is not None:
        if (
            not math.isfinite(spec.shaft_exposed_mm)
            or spec.shaft_exposed_mm <= 0
        ):
            raise ValueError("轴端光轴外露长度必须是大于 0 的有限数值。")
        if spec.shaft_exposed_mm > spec.shaft_projection_mm:
            raise ValueError("轴端光轴外露长度不能大于每端轴头伸出量。")

    thread = (spec.shaft_thread_designation or "").strip().upper()
    if thread not in SHAFT_THREAD_SPECS_MM:
        allowed = "、".join(sorted(SHAFT_THREAD_SPECS_MM))
        raise ValueError(f"轴端螺纹规格仅支持 {allowed}。")

    if spec.roller_type == "动力滚筒":
        if (
            not isinstance(spec.sprocket_teeth, int)
            or isinstance(spec.sprocket_teeth, bool)
            or spec.sprocket_teeth < 6
        ):
            raise ValueError("动力滚筒链轮齿数必须是至少 6 的整数。")
        if spec.chain_pitch_mm is not None and (
            not math.isfinite(spec.chain_pitch_mm) or spec.chain_pitch_mm <= 0
        ):
            raise ValueError("链条节距必须是大于 0 的有限数值。")
    elif spec.sprocket_teeth is not None or spec.chain_pitch_mm is not None:
        raise ValueError("无动力滚筒不应配置链轮齿数或链条节距。")
    return barrel_length


def compute_roller_layout(spec: RollerSpec) -> RollerLayout:
    """返回滚筒的轴向布局（坐标相对滚筒中心）。"""

    validate_roller_spec(spec)
    _, body_min, body_max, barrel_length = roller_axial_extents(spec)
    wall = spec.wall_thickness_mm

    if spec.roller_type == "无动力滚筒":
        cavity_start = body_min + wall
        cavity_end = body_max - wall
        cavity_spans = (
            ((cavity_start, cavity_end),) if cavity_end > cavity_start else ()
        )
        return RollerLayout(
            barrel_length,
            body_min,
            body_max,
            None,
            None,
            None,
            None,
            (),
            cavity_spans,
            tube_min_mm=body_min,
            tube_max_mm=body_max,
        )

    teeth = int(spec.sprocket_teeth)
    pitch = (
        spec.chain_pitch_mm
        if spec.chain_pitch_mm is not None
        else DEFAULT_CHAIN_PITCH_MM
    )
    pitch_radius, seat_radius, tip_radius = sprocket_geometry(teeth, pitch)
    scale = _pitch_scale(pitch)
    # 参考件齿根辅助圆 φ47.5；其它规格按节距比例并保证低于分度圆。
    if teeth == 14 and math.isclose(pitch, DEFAULT_CHAIN_PITCH_MM, abs_tol=1e-6):
        root_radius = SPROCKET_ROOT_LAND_RADIUS_REF_MM
    else:
        root_radius = min(
            SPROCKET_ROOT_LAND_RADIUS_REF_MM * scale,
            pitch_radius - seat_radius,
        )
    sprocket_outer_diameter = 2.0 * tip_radius
    sprocket_root_diameter = 2.0 * root_radius

    barrel_radius = spec.outer_diameter_mm / 2.0
    if teeth == 14 and math.isclose(pitch, DEFAULT_CHAIN_PITCH_MM, abs_tol=1e-6):
        hub_radius = HUB_RADIUS_REF_MM
    else:
        hub_radius = min(
            HUB_DIAMETER_RATIO * barrel_radius,
            root_radius - SPROCKET_ROOT_CLEARANCE_MM,
        )
    hub_radius = max(
        hub_radius,
        spec.shaft_diameter_mm / 2.0 + HUB_MIN_RADIAL_WALL_MM,
    )
    if hub_radius >= barrel_radius:
        raise ValueError("滚筒外径太小，无法生成缩径轮毂。")
    if hub_radius >= root_radius:
        raise ValueError("轮毂直径不能大于齿根辅助圆，否则切齿会伤到轮毂。")

    row_width = SPROCKET_ROW_WIDTH_REF_MM * scale
    bevel = SPROCKET_TOOTH_BEVEL_REF_MM * scale
    base_gap = SPROCKET_ROW_BASE_GAP_REF_MM * scale
    hub_lead = SPROCKET_HUB_LEAD_REF_MM * scale
    transition = SPROCKET_HUB_TRANSITION_REF_MM * scale
    overshoot = SPROCKET_CUT_OVERSHOOT_REF_MM * scale
    # 草图1：末排根宽外端 = body_max；两排根间距 15；轮毂颈 15；R5。
    row2_end = body_max - bevel
    row2_start = row2_end - row_width
    row2_base_start = row2_start - bevel
    row1_base_end = row2_base_start - base_gap
    row1_end = row1_base_end - bevel
    row1_start = row1_end - row_width
    row1_base_start = row1_start - bevel
    hub_min = row1_base_start - hub_lead
    tube_max = hub_min - transition
    hub_max = body_max
    # 与回转轮廓一致：无链轮端 R5 外侧切点相对 body_min 内偏 2 mm。
    tube_min = body_min + 2.0 * scale
    tip_gap = row2_start - row1_end
    if tip_gap <= 0.05:
        raise ValueError("链轮排间距过小，两排齿顶重叠。")
    if tube_max - tube_min <= 2.0 * wall + 2.0:
        raise ValueError("滚筒总长太短，无法同时布置筒身和双排链轮轮毂。")
    if hub_min > row1_base_start + 1e-9:
        raise ValueError("轮毂颈过短，梯形齿坯侵入 R5 过渡区。")

    cavity_spans = ((min(tube_min + wall, tube_max - 0.1), tube_max),)
    cavity_spans = tuple(
        (start, end) for start, end in cavity_spans if end - start > 0.05
    )
    cut_start = row1_base_start - overshoot
    cut_end = body_max
    return RollerLayout(
        barrel_length,
        body_min,
        body_max,
        sprocket_outer_diameter,
        sprocket_root_diameter,
        row_width,
        tip_gap,
        ((row1_start, row1_end), (row2_start, row2_end)),
        cavity_spans,
        tube_min_mm=tube_min,
        tube_max_mm=tube_max,
        hub_min_mm=hub_min,
        hub_max_mm=hub_max,
        hub_diameter_mm=2.0 * hub_radius,
        sprocket_cut_span_mm=(cut_start, cut_end),
        sprocket_pitch_radius_mm=pitch_radius,
        sprocket_seat_radius_mm=seat_radius,
    )
