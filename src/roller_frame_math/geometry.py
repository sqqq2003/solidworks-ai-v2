"""Pure geometry for the roller-conveyor frame.

W is the clear distance between the inner faces of the side plates, and the
roller face length. L keeps a fixed hole pitch; the leftover length is split
into end margins in the same ratio as the mother. H changes through the legs
unless a side-plate height override is given.

Nothing in this module reads SolidWorks.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from roller_frame_math.errors import GeometryError

PITCH_MM = 88.9
MOTHER_WIDTH_MM = 600.0
MOTHER_LENGTH_MM = 1000.0
MOTHER_HEIGHT_MM = 455.0

# Example figures for the README demo and tests. They are not measurements
# taken from the mother assembly.
EXAMPLE_MARGIN_START_MM = 55.5
EXAMPLE_MARGIN_END_MM = 55.5
EXAMPLE_SIDE_PLATE_HEIGHT_MM = 200.0
EXAMPLE_SIDE_PLATE_THICKNESS_MM = 4.0
EXAMPLE_SHAFT_STICKOUT_MM = 15.0

# Mother span must land on the nominal pitch within this tolerance before L
# is allowed to move the holes. 1 mm is measurement slack, not a feature id.
MOTHER_PITCH_TOLERANCE_MM = 1.0

_UM = 1000


def to_um(mm: float) -> int:
    return int(round(float(mm) * _UM))


def to_mm(um: int) -> float:
    return um / _UM


def format_size_name(width_mm: float, length_mm: float, height_mm: float) -> str:
    return f"{_fmt_size_token(width_mm)}x{_fmt_size_token(length_mm)}x{_fmt_size_token(height_mm)}"


def fmt_mm(value: float) -> str:
    text = f"{value:.3f}".rstrip("0").rstrip(".")
    return text if text else "0"


def _fmt_size_token(value: float) -> str:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        raise GeometryError(
            f"尺寸必须是有限数值，收到 {value!r}",
            stage="preflight",
            mate_class="geometry",
        )
    um = to_um(value)
    if um % _UM == 0:
        return str(um // _UM)
    return fmt_mm(to_mm(um))


def _positive(name: str, value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise GeometryError(
            f"{name} 必须是正数，收到 {value!r}",
            stage="preflight",
            mate_class="geometry",
        )
    return float(value)


def _non_negative(name: str, value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise GeometryError(
            f"{name} 不能为负，收到 {value!r}",
            stage="preflight",
            mate_class="geometry",
        )
    return float(value)


@dataclass(frozen=True)
class WidthLayout:
    """Inner span and roller face equal W. Stick-out length does not scale."""

    width_mm: float
    inner_span_mm: float
    roller_face_length_mm: float
    side_plate_thickness_mm: float | None
    shaft_stickout_each_side_mm: float | None
    overall_outer_width_mm: float | None


@dataclass(frozen=True)
class HoleLayout:
    length_mm: float
    pitch_mm: float
    nominal_pitch_mm: float
    count: int
    margin_start_mm: float
    margin_end_mm: float
    centers_mm: tuple[float, ...]
    pitch_is_nominal: bool
    mother_count: int


@dataclass(frozen=True)
class HeightLayout:
    height_mm: float
    mother_height_mm: float
    side_plate_height_mm: float | None
    leg_length_mm: float | None
    leg_delta_mm: float | None
    side_plate_fixed: bool


@dataclass(frozen=True)
class ResizePlan:
    width: WidthLayout
    holes: HoleLayout | None
    height: HeightLayout
    size_name: str
    width_changed: bool
    length_changed: bool
    height_changed: bool
    mother_width_mm: float
    mother_length_mm: float
    mother_height_mm: float


def layout_width(
    width_mm: float,
    *,
    side_plate_thickness_mm: float | None = None,
    shaft_stickout_each_side_mm: float | None = None,
) -> WidthLayout:
    width = _positive("W", width_mm)
    thickness: float | None = None
    stickout: float | None = None
    overall: float | None = None
    if side_plate_thickness_mm is not None:
        thickness = _non_negative("侧板厚度", side_plate_thickness_mm)
    if shaft_stickout_each_side_mm is not None:
        stickout = _non_negative("轴端伸出", shaft_stickout_each_side_mm)
    if thickness is not None and stickout is not None:
        overall = width + 2 * thickness + 2 * stickout
    return WidthLayout(
        width_mm=width,
        inner_span_mm=width,
        roller_face_length_mm=width,
        side_plate_thickness_mm=thickness,
        shaft_stickout_each_side_mm=stickout,
        overall_outer_width_mm=overall,
    )


def layout_height(
    height_mm: float,
    *,
    mother_height_mm: float,
    mother_side_plate_height_mm: float | None,
    side_plate_height_mm: float | None = None,
) -> HeightLayout:
    height = _positive("H", height_mm)
    mother_h = _positive("母体 H", mother_height_mm)
    plate_known = mother_side_plate_height_mm is not None
    mother_plate: float | None = None
    if plate_known:
        mother_plate = _positive("母体侧板高度", mother_side_plate_height_mm)  # type: ignore[arg-type]
        if to_um(mother_plate) >= to_um(mother_h):
            raise GeometryError(
                "母体侧板高度必须小于母体 H。H = 侧板高度 + 腿高。",
                stage="preflight",
                mate_class="geometry",
            )

    if side_plate_height_mm is None:
        if not plate_known:
            if to_um(height) != to_um(mother_h):
                raise GeometryError(
                    "H 与母体不同，但 mother_side_plate_height_mm 还没填。"
                    "默认侧板高度不动，只改腿高，所以必须知道母体侧板高度。",
                    stage="preflight",
                    mate_class="geometry",
                )
            return HeightLayout(
                height_mm=height,
                mother_height_mm=mother_h,
                side_plate_height_mm=None,
                leg_length_mm=None,
                leg_delta_mm=0.0,
                side_plate_fixed=True,
            )
        plate = mother_plate
        fixed = True
    else:
        plate = _positive("侧板高度", side_plate_height_mm)
        fixed = False

    assert plate is not None
    if to_um(plate) >= to_um(height):
        raise GeometryError(
            f"侧板高度 {fmt_mm(plate)} mm 必须小于 H {fmt_mm(height)} mm。",
            stage="preflight",
            mate_class="geometry",
        )
    legs = to_mm(to_um(height) - to_um(plate))
    if mother_plate is None:
        delta = None
    else:
        mother_legs = to_um(mother_h) - to_um(mother_plate)
        delta = to_mm(to_um(legs) - mother_legs)
    return HeightLayout(
        height_mm=height,
        mother_height_mm=mother_h,
        side_plate_height_mm=plate,
        leg_length_mm=legs,
        leg_delta_mm=delta,
        side_plate_fixed=fixed,
    )


def _split_leftover(leftover_um: int, start_um: int, end_um: int) -> tuple[int, int]:
    total = start_um + end_um
    start = (leftover_um * start_um + total // 2) // total
    if start <= 0 or start >= leftover_um:
        raise GeometryError(
            "两端余量按母体比例分配后有一端不是正数。请核对母体边距。",
            stage="preflight",
            mate_class="geometry",
        )
    return start, leftover_um - start


def _nearest_intervals(span_um: int, pitch_um: int) -> int:
    if span_um <= 0:
        raise GeometryError(
            "母体两端边距之和必须小于母体长度。",
            stage="preflight",
            mate_class="geometry",
        )
    return (span_um + pitch_um // 2) // pitch_um


def layout_roller_holes(
    length_mm: float,
    *,
    pitch_mm: float,
    mother_length_mm: float,
    mother_margin_start_mm: float,
    mother_margin_end_mm: float,
) -> HoleLayout:
    """Place roller-hole centers along L.

    When L equals the mother length, centers stay on the measured margins.
    When L changes, pitch is exactly ``pitch_mm`` and the leftover is split
    in the mother start:end ratio. The hole count is the one whose margins
    sit closest to the mother margins scaled by L / mother_L.
    """

    length = _positive("L", length_mm)
    pitch = _positive("孔距", pitch_mm)
    mother_l = _positive("母体 L", mother_length_mm)
    margin_start = _positive("母体起始边距", mother_margin_start_mm)
    margin_end = _positive("母体末端边距", mother_margin_end_mm)

    length_um = to_um(length)
    pitch_um = to_um(pitch)
    mother_l_um = to_um(mother_l)
    start_um = to_um(margin_start)
    end_um = to_um(margin_end)
    if start_um + end_um >= mother_l_um:
        raise GeometryError(
            "母体两端边距之和必须小于母体长度。",
            stage="preflight",
            mate_class="geometry",
        )

    mother_span_um = mother_l_um - start_um - end_um
    mother_intervals = _nearest_intervals(mother_span_um, pitch_um)
    if mother_intervals < 1:
        raise GeometryError(
            "母体跨距放不下至少两个滚筒孔。",
            stage="preflight",
            mate_class="geometry",
        )
    residual_um = mother_span_um - mother_intervals * pitch_um
    tolerance_um = to_um(MOTHER_PITCH_TOLERANCE_MM)
    pitch_matches = abs(residual_um) <= tolerance_um
    mother_count = mother_intervals + 1

    if length_um == mother_l_um:
        centers = _measured_centers(start_um, mother_span_um, mother_intervals)
        if residual_um == 0:
            actual_pitch = to_mm(pitch_um)
        else:
            actual_pitch = to_mm(int(round(mother_span_um / mother_intervals)))
        return HoleLayout(
            length_mm=to_mm(length_um),
            pitch_mm=actual_pitch,
            nominal_pitch_mm=to_mm(pitch_um),
            count=mother_count,
            margin_start_mm=to_mm(start_um),
            margin_end_mm=to_mm(end_um),
            centers_mm=tuple(to_mm(c) for c in centers),
            pitch_is_nominal=residual_um == 0,
            mother_count=mother_count,
        )

    if not pitch_matches:
        raise GeometryError(
            "母体孔跨距与节距不一致，拒绝改 L。"
            f" 跨距 {fmt_mm(to_mm(mother_span_um))} mm，"
            f"最近的 {mother_intervals} 档 × {fmt_mm(to_mm(pitch_um))} mm "
            f"还差 {fmt_mm(to_mm(residual_um))} mm"
            f"（允许 {fmt_mm(MOTHER_PITCH_TOLERANCE_MM)} mm）。"
            "请核对 mother_margin_start_mm 和 mother_margin_end_mm，它们必须是实测值，不能猜。",
            stage="preflight",
            mate_class="geometry",
        )

    target_start = to_um(margin_start * length / mother_l)
    target_end = to_um(margin_end * length / mother_l)
    ideal_span = length_um - target_start - target_end
    ideal_n = ideal_span / pitch_um
    max_n = (length_um - 1) // pitch_um
    if max_n < 1:
        raise GeometryError(
            f"L={fmt_mm(length)} mm 太短，按节距 {fmt_mm(pitch)} mm 放不下两个孔。",
            stage="preflight",
            mate_class="geometry",
        )

    best: tuple[tuple[float, float, int], int, int, int] | None = None
    for n_intervals in range(1, max_n + 1):
        leftover = length_um - n_intervals * pitch_um
        if leftover <= 1:
            continue
        try:
            start, end = _split_leftover(leftover, start_um, end_um)
        except GeometryError:
            continue
        score = (start - target_start) ** 2 + (end - target_end) ** 2
        key = (float(score), abs(n_intervals - ideal_n), n_intervals)
        if best is None or key < best[0]:
            best = (key, n_intervals, start, end)

    if best is None:
        raise GeometryError(
            f"L={fmt_mm(length)} mm 无法在节距 {fmt_mm(pitch)} mm 下得到正的两端余量。",
            stage="preflight",
            mate_class="geometry",
        )

    _, n_intervals, start, end = best
    centers_um = tuple(start + i * pitch_um for i in range(n_intervals + 1))
    if centers_um[-1] + end != length_um:
        raise GeometryError(
            "孔位计算没有闭合到机架末端。这是程序错误，已停止。",
            stage="preflight",
            mate_class="geometry",
        )
    return HoleLayout(
        length_mm=to_mm(length_um),
        pitch_mm=to_mm(pitch_um),
        nominal_pitch_mm=to_mm(pitch_um),
        count=n_intervals + 1,
        margin_start_mm=to_mm(start),
        margin_end_mm=to_mm(end),
        centers_mm=tuple(to_mm(c) for c in centers_um),
        pitch_is_nominal=True,
        mother_count=mother_count,
    )


def _measured_centers(start_um: int, span_um: int, intervals: int) -> tuple[int, ...]:
    if intervals <= 0:
        return (start_um,)
    centers = [start_um + int(round(span_um * i / intervals)) for i in range(intervals + 1)]
    centers[0] = start_um
    centers[-1] = start_um + span_um
    return tuple(centers)


def build_plan(
    *,
    width_mm: float,
    length_mm: float,
    height_mm: float,
    pitch_mm: float,
    mother_width_mm: float,
    mother_length_mm: float,
    mother_height_mm: float,
    mother_margin_start_mm: float | None,
    mother_margin_end_mm: float | None,
    mother_side_plate_height_mm: float | None,
    side_plate_height_mm: float | None = None,
    mother_side_plate_thickness_mm: float | None = None,
    mother_shaft_stickout_mm: float | None = None,
) -> ResizePlan:
    mother_w = _positive("母体 W", mother_width_mm)
    mother_l = _positive("母体 L", mother_length_mm)
    width = layout_width(
        width_mm,
        side_plate_thickness_mm=mother_side_plate_thickness_mm,
        shaft_stickout_each_side_mm=mother_shaft_stickout_mm,
    )
    height = layout_height(
        height_mm,
        mother_height_mm=mother_height_mm,
        mother_side_plate_height_mm=mother_side_plate_height_mm,
        side_plate_height_mm=side_plate_height_mm,
    )
    length_changed = to_um(length_mm) != to_um(mother_l)
    if mother_margin_start_mm is None or mother_margin_end_mm is None:
        if length_changed:
            raise GeometryError(
                "L 与母体不同，但 mother_margin_start_mm / mother_margin_end_mm 还没填。"
                "在机架长度方向实测：起点端面到第一个滚筒孔中心，以及最后一个孔中心到终点端面。"
                "两边分别填进这两个字段。README 算例里的 55.5 mm 不是这台机器的测量值。"
                "L 与母体相同时可以留空。",
                stage="preflight",
                mate_class="geometry",
            )
        holes = None
    else:
        holes = layout_roller_holes(
            length_mm,
            pitch_mm=pitch_mm,
            mother_length_mm=mother_l,
            mother_margin_start_mm=mother_margin_start_mm,
            mother_margin_end_mm=mother_margin_end_mm,
        )
    return ResizePlan(
        width=width,
        holes=holes,
        height=height,
        size_name=format_size_name(width.width_mm, length_mm, height.height_mm),
        width_changed=to_um(width.width_mm) != to_um(mother_w),
        length_changed=length_changed,
        height_changed=to_um(height.height_mm) != to_um(height.mother_height_mm) or not height.side_plate_fixed,
        mother_width_mm=mother_w,
        mother_length_mm=mother_l,
        mother_height_mm=height.mother_height_mm,
    )


def example_plans() -> tuple[ResizePlan, ResizePlan, ResizePlan]:
    """Three acceptance sizes under the documented example assumptions."""

    common = dict(
        pitch_mm=PITCH_MM,
        mother_width_mm=MOTHER_WIDTH_MM,
        mother_length_mm=MOTHER_LENGTH_MM,
        mother_height_mm=MOTHER_HEIGHT_MM,
        mother_margin_start_mm=EXAMPLE_MARGIN_START_MM,
        mother_margin_end_mm=EXAMPLE_MARGIN_END_MM,
        mother_side_plate_height_mm=EXAMPLE_SIDE_PLATE_HEIGHT_MM,
        mother_side_plate_thickness_mm=EXAMPLE_SIDE_PLATE_THICKNESS_MM,
        mother_shaft_stickout_mm=EXAMPLE_SHAFT_STICKOUT_MM,
    )
    mother = build_plan(width_mm=600, length_mm=1000, height_mm=455, **common)
    wider = build_plan(width_mm=800, length_mm=1500, height_mm=455, **common)
    taller = build_plan(width_mm=600, length_mm=1000, height_mm=500, **common)
    return mother, wider, taller
