# -*- coding: utf-8 -*-
"""把车件计划收成可写入 SolidWorks 的草图。

半边轮廓的轴向坐标来自图纸，主动轴一类图会落在 X≈10000 mm。
若直接除以 1000 写进草图，轮廓停在大约 10 m 处；旋转时若没单独选中
中心线，SolidWorks 会绕原点把这段轮廓扫成十几米直径、厚度只有一个
半径的扁片。这里先把轴向平移到 0，中心线只比零件略长，并按件类
决定旋转还是凸台拉伸。
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass

logger = logging.getLogger("cad2sw.turned")

Point = tuple[float, float]

# FeatureRevolve2 的旋转轴选择标记。录制宏里选中心线用的就是 16。
REVOLVE_AXIS_MARK = 16
# 草图 API 用米。零件平移到原点后，坐标不应再出现图纸上的十几米。
MAX_SKETCH_METERS = 5.0
_AXIS_EXTENSION_MM = 0.5

_HEX = re.compile(r"(?:六角(?:钢|棒|柱)?|对边)\s*(\d+(?:\.\d+)?)?")
_RECT = re.compile(
    r"(?:方钢|扁钢)\s*(\d+(?:\.\d+)?)\s*[×xX*]\s*(\d+(?:\.\d+)?)"
    r"|(\d+(?:\.\d+)?)\s*[×xX*]\s*(\d+(?:\.\d+)?)\s*(?:mm)?\s*(?:方钢|扁钢)"
)
_TUBE_MARKED = re.compile(
    r"[ØΦφ⌀∅]\s*(\d+(?:\.\d+)?)\s*[×xX*]\s*(\d+(?:\.\d+)?)"
)
_WALL = re.compile(
    r"壁厚\s*(\d+(?:\.\d+)?)"
    r"|(\d+(?:\.\d+)?)\s*mm\s*厚"
    r"|[ØΦφ⌀∅]\s*\d+(?:\.\d+)?\s*圆管\s*[-\s]\s*(\d+(?:\.\d+)?)\s*mm"
)

_STOCK_LABELS = {
    "revolve": "旋转",
    "hex": "六角棒凸台拉伸",
    "rect": "方钢凸台拉伸",
    "tube": "薄壁管旋转",
    "sprocket": "链轮轮毂旋转",
}


@dataclass(frozen=True)
class StockChoice:
    kind: str
    size_mm: tuple[float, ...] = ()

    @property
    def label(self) -> str:
        return _STOCK_LABELS.get(self.kind, self.kind)


@dataclass(frozen=True)
class SketchPathSegment:
    """草图路径段：直线或三点弧。via 是弧上的中间点。"""

    kind: str  # "line" | "arc"
    start: Point
    end: Point
    via: Point | None = None


@dataclass(frozen=True)
class RevolveSketch:
    """闭合半边（或管壁）轮廓，轴向从 0 起，单位毫米。另给一条更长的中心线。"""

    contour_mm: tuple[Point, ...]
    axis_start_mm: Point
    axis_end_mm: Point
    length_mm: float
    max_radius_mm: float
    segments: tuple[SketchPathSegment, ...] = ()


@dataclass(frozen=True)
class ExtrudeSketch:
    """垂直于轴线的截面，中心在原点，沿轴向拉伸 depth_mm。"""

    contour_mm: tuple[Point, ...]
    depth_mm: float


@dataclass(frozen=True)
class KeywayCut:
    """前视草图上的矩形（轴向, 半径），沿厚度方向对称切除 width_mm。"""

    contour_mm: tuple[Point, ...]
    width_mm: float
    on_bore: bool = False


@dataclass(frozen=True)
class AxialCut:
    """截面草图上的圆。六角和方钢的孔、端部车削都沿拉伸方向切。"""

    radius_mm: float
    depth_mm: float
    start_offset_mm: float
    outside: bool
    name: str
    thread: str = ""


@dataclass(frozen=True)
class TurnedBuild:
    kind: str
    label: str
    length_mm: float
    expected_dims_mm: tuple[float, float, float]
    revolve: RevolveSketch | None = None
    extrude: ExtrudeSketch | None = None
    hole_cuts: tuple[RevolveSketch, ...] = ()
    bore_cuts: tuple[RevolveSketch, ...] = ()
    chamfer_cuts: tuple[RevolveSketch, ...] = ()
    keyway_cuts: tuple[KeywayCut, ...] = ()
    axial_cuts: tuple[AxialCut, ...] = ()
    warnings: tuple[str, ...] = ()


def hex_area_mm2(across_flats: float) -> float:
    return (math.sqrt(3.0) / 2.0) * across_flats * across_flats


def volume_drop_mm3(before: float, after: float) -> float:
    """体积差，单位立方毫米。小于 0.05 的读数按立方米换算。"""

    drop = float(before) - float(after)
    if max(abs(before), abs(after)) < 0.05:
        return drop * 1e9
    return drop


def removal_is_outside_cut(removed_mm3: float, outside_mm3: float, hole_mm3: float) -> bool:
    if outside_mm3 <= 0 or removed_mm3 < 0.55 * outside_mm3:
        return False
    return abs(removed_mm3 - outside_mm3) <= abs(removed_mm3 - hole_mm3)


def removal_is_hole(removed_mm3: float, hole_mm3: float) -> bool:
    if hole_mm3 <= 0:
        return False
    return removed_mm3 > 0.55 * hole_mm3 and abs(removed_mm3 - hole_mm3) / hole_mm3 < 0.45


def axial_interval_position(
    spans: tuple[tuple[float, float], ...] | list[tuple[float, float]],
    offset_mm: float,
    depth_mm: float,
) -> str:
    """圆柱面落在偏移段上、落在起点，还是看不出来。"""

    if depth_mm <= 0 or not spans:
        return "unknown"
    expected = (offset_mm, offset_mm + depth_mm)
    near = (0.0, depth_mm)

    def overlap(span: tuple[float, float], window: tuple[float, float]) -> float:
        return max(0.0, min(span[1], window[1]) - max(span[0], window[0]))

    best_expected = max(overlap(span, expected) for span in spans)
    best_near = max(overlap(span, near) for span in spans)
    if best_expected >= 0.6 * depth_mm and best_expected >= best_near:
        return "at_expected"
    if offset_mm > 5.0 and best_near >= 0.6 * depth_mm and best_near > best_expected + 1.0:
        return "at_start"
    return "unknown"


def judge_axial_cut(
    *,
    outside: bool,
    removed_mm3: float | None,
    outside_mm3: float,
    hole_mm3: float,
    sense: str | None,
    position: str | None,
) -> str:
    """ok、wrong 或 unknown。

    体积和轴向位置可以否定一次切除。圆柱面方向只在别的都读不到时当作参考，
    单独读反了不会把已经切对的一刀判失败。
    """

    target = outside_mm3 if outside else hole_mm3
    if removed_mm3 is not None and target > 0:
        if removed_mm3 < 0.2 * target:
            return "wrong"
        matched = (
            outside and removal_is_outside_cut(removed_mm3, outside_mm3, hole_mm3)
        ) or ((not outside) and removal_is_hole(removed_mm3, hole_mm3))
        opposite = (
            outside and removal_is_hole(removed_mm3, hole_mm3)
        ) or ((not outside) and removal_is_outside_cut(removed_mm3, outside_mm3, hole_mm3))
        if opposite and not matched:
            return "wrong"
        if matched and position != "at_start":
            return "ok"
        if matched and position == "at_start":
            return "wrong"
    if position == "at_start":
        return "wrong"
    if position == "at_expected":
        return "ok"
    if sense == "external" and outside:
        return "ok"
    if sense == "internal" and not outside:
        return "ok"
    return "unknown"


def stock_label(kind: str) -> str:
    return _STOCK_LABELS.get(kind, kind)


def mm_point_to_m(point: Point) -> tuple[float, float, float]:
    """毫米草图点 → SolidWorks 草图 API 的米。离原点过远则拒绝。"""

    x = point[0] / 1000.0
    y = point[1] / 1000.0
    if abs(x) > MAX_SKETCH_METERS or abs(y) > MAX_SKETCH_METERS:
        raise ValueError(
            f"草图点 ({point[0]:.1f}, {point[1]:.1f}) mm 换成米后仍离原点超过 "
            f"{MAX_SKETCH_METERS:g} m。轮廓还停在图纸坐标上，绕错轴就会扫成十几米的扁片。"
        )
    return (x, y, 0.0)


# 链轮图纸习惯把规格写在标题栏里，例如「3分12齿链轮RS30X12T」：
#   「3分」= 节距 3/8"，「12齿」/「12T」= 齿数，RS30 也是 3/8" 的链号。
# 轮廓只能读到轮毂（Ø15 那类内孔），照它旋转出来就是一根光轴，
# 齿顶圆必须按链轮公式算：da = p · (0.54 + cot(180°/z))。
_PITCH_BY_FEN_MM = {
    2: 6.35,    # 1/4"
    3: 9.525,   # 3/8"
    4: 12.7,    # 1/2"
    5: 15.875,  # 5/8"
    6: 19.05,   # 3/4"
    8: 25.4,    # 1"
}
_PITCH_BY_RS_MM = {
    25: 6.35,
    30: 9.525,
    35: 9.525,
    40: 12.7,
    50: 15.875,
    60: 19.05,
    80: 25.4,
}
_SPROCKET_FEN = re.compile(r"(\d+(?:\.\d+)?)\s*分")
_SPROCKET_RS = re.compile(r"RS\s*(\d+)", re.IGNORECASE)
_SPROCKET_TEETH_CN = re.compile(r"(\d+)\s*齿")
_SPROCKET_TEETH_T = re.compile(r"(\d+)\s*[Tt]\b")


def sprocket_outer_diameter_mm(pitch_mm: float, teeth: int) -> float:
    """链轮齿顶圆：da = p · (0.54 + cot(180°/z))。"""

    if teeth < 6 or pitch_mm <= 0:
        return 0.0
    return pitch_mm * (0.54 + 1.0 / math.tan(math.pi / teeth))


def _sprocket_spec(blob: str) -> tuple[float, int]:
    """从图纸文字里读链轮规格，返回 (节距 mm, 齿数)；读不到返回 (0.0, 0)。"""

    pitch = 0.0
    fen = _SPROCKET_FEN.search(blob)
    if fen is not None:
        pitch = _PITCH_BY_FEN_MM.get(int(float(fen.group(1))), 0.0)
    if pitch <= 0:
        rs = _SPROCKET_RS.search(blob)
        if rs is not None:
            pitch = _PITCH_BY_RS_MM.get(int(rs.group(1)), 0.0)
    teeth = 0
    for pattern in (_SPROCKET_TEETH_CN, _SPROCKET_TEETH_T):
        match = pattern.search(blob)
        if match is not None:
            value = int(match.group(1))
            # 齿数太小不像齿数，也别吃到「2-M6」这类螺纹标注。
            if 6 <= value <= 200:
                teeth = value
                break
    return pitch, teeth


def classify_stock(notes: list[str] | tuple[str, ...], *, max_radius_mm: float) -> StockChoice:
    """六角/方钢走拉伸，带壁厚的圆管走薄壁旋转，其余台阶轴旋转。"""

    blob = "\n".join(note for note in notes if note)
    if "六角" in blob or "对边" in blob:
        match = _HEX.search(blob)
        number = float(match.group(1)) if match and match.group(1) else 0.0
        if number <= 0:
            if max_radius_mm <= 0:
                raise ValueError("六角棒没有对边尺寸，无法拉伸。")
            number = max_radius_mm * math.sqrt(3.0)
        if number < 1.0 or number > 500.0:
            raise ValueError(f"六角对边 {number:g} mm 不合理，已中止。")
        return StockChoice("hex", (number,))

    rect = _RECT.search(blob)
    if rect is not None:
        numbers = [float(group) for group in rect.groups() if group]
        if len(numbers) != 2 or min(numbers) <= 0:
            raise ValueError("方钢截面尺寸没有读全，无法拉伸。")
        if max(numbers) > 500.0:
            raise ValueError(f"方钢截面 {numbers[0]:g}×{numbers[1]:g} mm 不合理，已中止。")
        return StockChoice("rect", (numbers[0], numbers[1]))

    wall_note = _WALL.search(blob)
    marked = _TUBE_MARKED.search(blob)
    if "圆管" in blob or "钢管" in blob or wall_note is not None or _is_thin_wall(marked):
        if marked is not None and _is_thin_wall(marked):
            outer = float(marked.group(1))
            wall = float(marked.group(2))
        elif wall_note is not None:
            outer = 2.0 * max_radius_mm
            # 三种写法都会出现：「壁厚 0.7」「0.7mm厚」「Ø32圆管-0.7mm」，
            # 命中的是哪个分组就取哪个。
            wall = next(float(group) for group in wall_note.groups() if group)
        else:
            outer = 2.0 * max_radius_mm
            wall = 0.0
        if outer <= 0 or wall <= 0 or wall >= outer / 2.0:
            raise ValueError(
                f"薄壁管外径 {outer:g} mm、壁厚 {wall:g} mm 不成立，已中止。"
            )
        return StockChoice("tube", (outer, wall))
    if "链轮" in blob:
        pitch, teeth = _sprocket_spec(blob)
        outer = sprocket_outer_diameter_mm(pitch, teeth)
        if outer <= 0:
            return StockChoice("sprocket", ())
        # 轮廓给的半径是轮毂（往往就是内孔），齿顶圆比它大得多。
        # 只在算出来更大时才顶掉，免得规格读错反而把件做小。
        if outer <= 2.0 * max_radius_mm:
            return StockChoice("sprocket", ())
        return StockChoice("sprocket", (outer, float(teeth)))
    return StockChoice("revolve", ())


def expected_dims_mm(
    kind: str,
    length_mm: float,
    size_mm: tuple[float, ...],
    max_radius_mm: float,
) -> tuple[float, float, float]:
    """实体外包的三个跨度（毫米），从大到小。"""

    if kind == "hex":
        across_flats = size_mm[0]
        across_points = 2.0 * across_flats / math.sqrt(3.0)
        dims = (length_mm, across_flats, across_points)
    elif kind == "rect":
        dims = (length_mm, size_mm[0], size_mm[1])
    elif kind == "tube":
        outer = size_mm[0] if size_mm else 2.0 * max_radius_mm
        dims = (length_mm, outer, outer)
    elif kind == "sprocket":
        # 有规格时 size_mm[0] 是算出来的齿顶圆，否则退回轮廓半径。
        diameter = size_mm[0] if size_mm else 2.0 * max_radius_mm
        dims = (length_mm, diameter, diameter)
    else:
        diameter = 2.0 * max_radius_mm
        dims = (length_mm, diameter, diameter)
    return tuple(sorted(dims, reverse=True))


def dims_mismatch(
    actual_mm: tuple[float, float, float],
    expected_mm: tuple[float, float, float],
) -> str | None:
    """外包与计划不一致时返回原因。允许 2% 或 1 mm。"""

    got = tuple(sorted((float(value) for value in actual_mm), reverse=True))
    want = tuple(sorted((float(value) for value in expected_mm), reverse=True))
    if len(got) != 3 or len(want) != 3:
        return "外包尺寸不完整。"
    details: list[str] = []
    for measured, target in zip(got, want):
        tolerance = max(1.0, 0.02 * abs(target))
        if abs(measured - target) > tolerance:
            details.append(f"{measured:.2f}≠{target:.2f}（允许±{tolerance:.2f}）")
    if not details:
        return None
    message = (
        "外包 "
        + " × ".join(f"{value:.2f}" for value in got)
        + " mm，期望 "
        + " × ".join(f"{value:.2f}" for value in want)
        + " mm（"
        + "；".join(details)
        + "）"
    )
    if got[0] > 1000.0:
        message += "。尺寸到了米级，多半是草图仍停在图纸坐标上并绕错了轴。"
    return message


def prepare_profile_sketch(
    profile: tuple[Point, ...] | list[Point],
    *,
    length_mm: float,
    max_radius_mm: float,
) -> RevolveSketch:
    """实心旋转：平移到轴向 0，闭合，并落到轴线上。"""

    return _revolve_sketch(
        profile,
        shift=None,
        length_mm=length_mm,
        max_radius_mm=max_radius_mm,
        touch_axis=True,
        require_full_length=True,
    )


def build_turned(plan) -> TurnedBuild:
    """由计划得到草图和期望外包。不连接 SolidWorks。"""

    kind = getattr(plan, "stock", None) or "revolve"
    size = tuple(getattr(plan, "stock_size_mm", ()) or ())
    length = float(plan.length_mm)
    radius = float(plan.max_radius_mm)
    if length <= 0.5 or radius <= 0.05:
        raise ValueError(
            f"零件长度 {length:.2f} mm 或半径 {radius:.2f} mm 无效，已中止生成。"
        )
    expected = expected_dims_mm(kind, length, size, radius)
    if kind == "sprocket" and (length > 800.0 or radius > 400.0):
        message = "链轮外形像图框，已跳过，不旋转乱轮廓。"
        logger.warning(message)
        raise ValueError(message)
    bores, chamfers, keyways, warnings = _secondary_cuts(plan, kind)
    if kind == "hex":
        if len(size) != 1:
            raise ValueError("六角棒缺少对边尺寸，已中止生成。")
        return TurnedBuild(
            kind,
            stock_label(kind),
            length,
            expected,
            extrude=ExtrudeSketch(_hexagon(size[0]), length),
            axial_cuts=_axial_cuts(plan, length),
            warnings=warnings,
        )
    if kind == "rect":
        if len(size) != 2:
            raise ValueError("方钢缺少截面尺寸，已中止生成。")
        return TurnedBuild(
            kind,
            stock_label(kind),
            length,
            expected,
            extrude=ExtrudeSketch(_rectangle(size[0], size[1]), length),
            axial_cuts=_axial_cuts(plan, length),
            warnings=warnings,
        )
    if kind == "tube":
        if len(size) != 2:
            raise ValueError("薄壁管缺少外径和壁厚，已中止生成。")
        outer, wall = size
        sketch = _revolve_sketch(
            _tube_wall(length, outer / 2.0, outer / 2.0 - wall),
            shift=0.0,
            length_mm=length,
            max_radius_mm=outer / 2.0,
            touch_axis=False,
            require_full_length=True,
        )
        return TurnedBuild(
            kind,
            stock_label(kind),
            length,
            expected,
            revolve=sketch,
            keyway_cuts=keyways,
            warnings=warnings,
        )
    if kind == "sprocket":
        # 按齿顶圆旋转：轮廓半径只是轮毂，照它转出来比成品小一大截。
        hub_radius = radius
        if size and size[0] > 0:
            hub_radius = size[0] / 2.0
        sketch = _revolve_sketch(
            _hub_rectangle(length, hub_radius),
            shift=0.0,
            length_mm=length,
            max_radius_mm=hub_radius,
            touch_axis=True,
            require_full_length=True,
        )
        teeth_note = f"，{int(size[1])} 齿" if len(size) > 1 and size[1] else ""
        logger.info(
            "链轮 %s 按齿顶圆 Ø%.2f 建圆柱%s，齿形未做",
            getattr(plan, "label", ""),
            2.0 * hub_radius,
            teeth_note,
        )
        return TurnedBuild(
            kind,
            stock_label(kind),
            length,
            expected,
            revolve=sketch,
            bore_cuts=bores,
            keyway_cuts=keyways,
            warnings=warnings
            + (f"链轮按齿顶圆 Ø{2 * hub_radius:.1f} 建圆柱，齿形未做",),
        )
    sketch = prepare_profile_sketch(
        plan.profile,
        length_mm=length,
        max_radius_mm=radius,
    )
    return TurnedBuild(
        "revolve",
        stock_label("revolve"),
        length,
        expected,
        revolve=sketch,
        hole_cuts=_hole_sketches(plan),
        bore_cuts=bores,
        chamfer_cuts=chamfers,
        keyway_cuts=keyways,
        warnings=warnings,
    )


def _is_thin_wall(match: re.Match[str] | None) -> bool:
    if match is None:
        return False
    outer = float(match.group(1))
    wall = float(match.group(2))
    return outer > 1.0 and 0.05 < wall < outer / 2.0 and wall < outer * 0.25


def _hexagon(across_flats: float) -> tuple[Point, ...]:
    """正六边形，对边为 across_flats。顶点在水平方向，截面中心在原点。"""

    radius = across_flats / math.sqrt(3.0)
    points = [
        (radius * math.cos(math.radians(60.0 * index)), radius * math.sin(math.radians(60.0 * index)))
        for index in range(6)
    ]
    points.append(points[0])
    return tuple(points)


def _rectangle(width: float, height: float) -> tuple[Point, ...]:
    half_w = width / 2.0
    half_h = height / 2.0
    return (
        (-half_w, -half_h),
        (half_w, -half_h),
        (half_w, half_h),
        (-half_w, half_h),
        (-half_w, -half_h),
    )


def _hub_rectangle(length: float, radius: float) -> tuple[Point, ...]:
    """链轮不转齿形，只转一根和包络等长、等半径的圆柱。"""

    return (
        (0.0, 0.0),
        (0.0, radius),
        (length, radius),
        (length, 0.0),
        (0.0, 0.0),
    )


def _secondary_cuts(plan, kind: str):
    from turned_features import chamfer_triangles, keyway_rectangle

    warnings: list[str] = []
    keyways: list[KeywayCut] = []
    specs = tuple(getattr(plan, "keyways", ()) or ())
    if specs and kind in ("hex", "rect"):
        warnings.append("六角或方钢上的键槽未切除，需手修")
    elif specs and kind in ("revolve", "tube", "sprocket"):
        for spec in specs:
            rectangle, width = keyway_rectangle(spec)
            keyways.append(KeywayCut(rectangle, width, bool(spec.on_bore)))
    bores: list[RevolveSketch] = []
    chamfers: list[RevolveSketch] = []
    if kind in ("revolve", "sprocket"):
        for bore in tuple(getattr(plan, "bores", ()) or ()):
            if bore.radius_mm <= 0.05 or bore.length_mm <= 0.05:
                raise ValueError("中孔尺寸无效，已中止。")
            raw = (
                (bore.start_mm, 0.0),
                (bore.start_mm + bore.length_mm, 0.0),
                (bore.start_mm + bore.length_mm, bore.radius_mm),
                (bore.start_mm, bore.radius_mm),
            )
            bores.append(
                _revolve_sketch(
                    raw,
                    shift=0.0,
                    length_mm=bore.length_mm,
                    max_radius_mm=bore.radius_mm,
                    touch_axis=True,
                    require_full_length=False,
                )
            )
    if kind == "revolve" and float(getattr(plan, "chamfer_mm", 0.0) or 0.0) > 0:
        for triangle in chamfer_triangles(plan.profile, float(plan.chamfer_mm)):
            ys = [point[1] for point in triangle]
            xs = [point[0] for point in triangle]
            chamfers.append(
                _revolve_sketch(
                    triangle,
                    shift=0.0,
                    length_mm=max(xs) - min(xs),
                    max_radius_mm=max(ys),
                    touch_axis=False,
                    require_full_length=False,
                )
            )
    return tuple(bores), tuple(chamfers), tuple(keyways), tuple(warnings)


def _axial_cuts(plan, length: float) -> tuple[AxialCut, ...]:
    cuts: list[AxialCut] = []
    for index, turn in enumerate(getattr(plan, "end_turns", ()) or (), start=1):
        if turn.radius_mm <= 0.05 or turn.length_mm <= 0.5:
            raise ValueError("端部车削尺寸无效，已中止。")
        if turn.start_mm < -0.2 or turn.start_mm + turn.length_mm > length + 0.3:
            raise ValueError(
                f"端部车削从 {turn.start_mm:.2f} mm 起、长 {turn.length_mm:.2f} mm，"
                f"超出零件 {length:.2f} mm，已中止。"
            )
        cuts.append(
            AxialCut(
                turn.radius_mm,
                min(turn.length_mm, length - turn.start_mm),
                max(0.0, turn.start_mm),
                True,
                f"端部车削{index}",
                turn.thread,
            )
        )
    profile = list(plan.profile)
    min_axial = min(point[0] for point in profile)
    max_axial = max(point[0] for point in profile)
    for index, hole in enumerate(plan.holes, start=1):
        if hole.diameter_mm <= 0 or hole.depth_mm <= 0:
            continue
        origin = hole.x if plan.axis == "horizontal" else hole.y
        from_start = True
        if origin is not None:
            from_start = abs(origin - min_axial) <= abs(origin - max_axial)
        depth = min(float(hole.depth_mm), length)
        offset = 0.0 if from_start else max(0.0, length - depth)
        cuts.append(
            AxialCut(
                float(hole.diameter_mm) / 2.0,
                depth,
                offset,
                False,
                f"轴向孔{index}",
                getattr(hole, "thread", "") or "",
            )
        )
    return tuple(cuts)


def _tube_wall(length: float, outer_radius: float, inner_radius: float) -> tuple[Point, ...]:
    if not 0.05 < inner_radius < outer_radius - 0.05:
        raise ValueError(
            f"薄壁截面内半径 {inner_radius:.2f} mm、外半径 {outer_radius:.2f} mm 不成立。"
        )
    return (
        (0.0, inner_radius),
        (length, inner_radius),
        (length, outer_radius),
        (0.0, outer_radius),
        (0.0, inner_radius),
    )


def _hole_sketches(plan) -> tuple[RevolveSketch, ...]:
    profile = list(plan.profile)
    if len(profile) < 2:
        return ()
    min_axial = min(point[0] for point in profile)
    max_axial = max(point[0] for point in profile)
    length = max_axial - min_axial
    sketches: list[RevolveSketch] = []
    for hole in plan.holes:
        if hole.diameter_mm <= 0 or hole.depth_mm <= 0:
            continue
        origin = hole.x if plan.axis == "horizontal" else hole.y
        from_start = True
        if origin is not None:
            from_start = abs(origin - min_axial) <= abs(origin - max_axial)
        depth = min(float(hole.depth_mm), length)
        radius = float(hole.diameter_mm) / 2.0
        if depth <= 0.05 or radius <= 0.05:
            continue
        if from_start:
            raw = (
                (min_axial, 0.0),
                (min_axial + depth, 0.0),
                (min_axial + depth, radius),
                (min_axial, radius),
            )
        else:
            raw = (
                (max_axial - depth, 0.0),
                (max_axial, 0.0),
                (max_axial, radius),
                (max_axial - depth, radius),
            )
        sketches.append(
            _revolve_sketch(
                raw,
                shift=min_axial,
                length_mm=depth,
                max_radius_mm=radius,
                touch_axis=True,
                require_full_length=False,
            )
        )
    return tuple(sketches)


def _revolve_sketch(
    profile: tuple[Point, ...] | list[Point],
    *,
    shift: float | None,
    length_mm: float,
    max_radius_mm: float,
    touch_axis: bool,
    require_full_length: bool,
) -> RevolveSketch:
    cleaned = _clean_open(profile)
    if shift is None:
        shift = min(point[0] for point in cleaned)
    shifted = [(point[0] - shift, point[1]) for point in cleaned]
    if _signed_area(shifted) < 0:
        shifted.reverse()
    if math.dist(shifted[0], shifted[-1]) > 1e-4:
        shifted.append(shifted[0])
    _reject_self_intersection(shifted)
    xs = [point[0] for point in shifted]
    ys = [point[1] for point in shifted]
    span = max(xs) - min(xs)
    if require_full_length and abs(span - length_mm) > max(0.05, 0.002 * length_mm):
        raise ValueError(
            f"草图轴向跨度 {span:.2f} mm 与计划长度 {length_mm:.2f} mm 不一致，已中止。"
        )
    if abs(max(ys) - max_radius_mm) > max(0.05, 0.02 * max(max_radius_mm, 0.1)):
        raise ValueError(
            f"草图半径 {max(ys):.2f} mm 与计划半径 {max_radius_mm:.2f} mm 不一致，已中止。"
        )
    if touch_axis:
        if min(ys) > 0.05:
            raise ValueError("半边轮廓没有落到轴线上，旋转得不到实心轴。")
        on_axis = [point[0] for point in shifted if point[1] <= 1e-3]
        if not on_axis or max(on_axis) - min(on_axis) < span - 0.2:
            raise ValueError("半边轮廓没有沿轴线闭合，已中止。")
    elif min(ys) <= 0.05:
        raise ValueError("薄壁截面贴到了轴线上，会转成实心，已中止。")
    for point in shifted:
        mm_point_to_m(point)
    extension = _AXIS_EXTENSION_MM
    axis_start = (min(xs) - extension, 0.0)
    axis_end = (max(xs) + extension, 0.0)
    mm_point_to_m(axis_start)
    mm_point_to_m(axis_end)
    # DWG→DXF 会把圆弧拆成细碎点，旋转后倒角/圆角变成一圈碎面。
    # 这里把近似直线的点链并成一条线，真圆弧拟合成三点弧，草图干净了再写 SW。
    segments = _fit_path_segments(shifted)
    return RevolveSketch(
        tuple(shifted),
        axis_start,
        axis_end,
        span,
        max(ys),
        segments,
    )


# 与弦的偏差小于该值（毫米）的点链按直线合并。
# 不能放大：支撑柱端面拐点离近似弦只有 0.14，放太宽会把端面吃成斜线。
_LINE_TOLERANCE_MM = 0.05
# 圆弧拟合残差上限（毫米）。
_ARC_TOLERANCE_MM = 0.05
# 链内相邻段的折角超过该度数就不是圆弧（矩形拐角 90°， tessellation 只有几度）。
_MAX_TURN_DEGREES = 30.0


def _point_line_distance(point: Point, start: Point, end: Point) -> float:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length = math.hypot(dx, dy)
    if length <= 1e-12:
        return math.dist(point, start)
    return abs((point[0] - start[0]) * dy - (point[1] - start[1]) * dx) / length


def _circle_through(a: Point, b: Point, c: Point) -> tuple[Point, float] | None:
    """三点定圆。共线或圆不合理返回 None。"""

    d = 2.0 * (a[0] * (b[1] - c[1]) + b[0] * (c[1] - a[1]) + c[0] * (a[1] - b[1]))
    if abs(d) < 1e-9:
        return None
    ux = (
        (a[0] ** 2 + a[1] ** 2) * (b[1] - c[1])
        + (b[0] ** 2 + b[1] ** 2) * (c[1] - a[1])
        + (c[0] ** 2 + c[1] ** 2) * (a[1] - b[1])
    ) / d
    uy = (
        (a[0] ** 2 + a[1] ** 2) * (c[0] - b[0])
        + (b[0] ** 2 + b[1] ** 2) * (a[0] - c[0])
        + (c[0] ** 2 + c[1] ** 2) * (b[0] - a[0])
    ) / d
    radius = math.dist((ux, uy), a)
    if not math.isfinite(radius) or radius <= 1e-6 or radius > 1e6:
        return None
    return ((ux, uy), radius)


def _max_turn_degrees(points: list[Point]) -> float:
    """点链里相邻段的最大折角（度）。共线为 0，直角拐弯为 90。"""

    worst = 0.0
    previous: tuple[float, float] | None = None
    for start, end in zip(points, points[1:]):
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        length = math.hypot(dx, dy)
        if length <= 1e-9:
            continue
        current = (dx / length, dy / length)
        if previous is not None:
            dot = max(-1.0, min(1.0, previous[0] * current[0] + previous[1] * current[1]))
            worst = max(worst, math.degrees(math.acos(dot)))
        previous = current
    return worst


def _fit_chain(points: list[Point]) -> SketchPathSegment | None:
    """一条原始点链拟合直线或三点弧，拟合不上返回 None。

    矩形四角也共圆，单靠残差会把直角误拟合成弧；折角约束（圆弧的
    tessellation 每段只折几度）同时挡住直角进直线和进弧。
    """

    if len(points) < 2:
        return None
    start, end = points[0], points[-1]
    if len(points) == 2:
        return SketchPathSegment("line", start, end)
    max_deviation = max(
        _point_line_distance(point, start, end) for point in points[1:-1]
    )
    max_turn = _max_turn_degrees(points)
    if max_deviation <= _LINE_TOLERANCE_MM and max_turn <= _MAX_TURN_DEGREES:
        return SketchPathSegment("line", start, end)
    if len(points) >= 4 and max_turn <= _MAX_TURN_DEGREES:
        fitted = _circle_through(points[0], points[len(points) // 2], points[-1])
        if fitted is not None:
            center, radius = fitted
            residual = max(abs(math.dist(point, center) - radius) for point in points)
            if residual <= _ARC_TOLERANCE_MM and max_deviation > 0.02:
                via = max(points[1:-1], key=lambda point: _point_line_distance(point, start, end))
                if math.dist(via, start) > 1e-6 and math.dist(via, end) > 1e-6:
                    return SketchPathSegment("arc", start, end, via)
    return None


def _fit_path_segments(closed_ring: list[Point]) -> tuple[SketchPathSegment, ...]:
    """闭合点环 → 线/弧段序列。闭合边单独成段，拟合不跨越闭合点。"""

    ring = list(closed_ring)
    if len(ring) > 1 and math.dist(ring[0], ring[-1]) <= 1e-4:
        ring = ring[:-1]
    if len(ring) < 2:
        return ()
    segments: list[SketchPathSegment] = []
    index = 0
    count = len(ring)
    while index < count - 1:
        fitted = None
        for end_index in range(count - 1, index, -1):
            chain = ring[index : end_index + 1]
            fitted = _fit_chain(chain)
            if fitted is not None:
                segments.append(fitted)
                index = end_index
                break
        if fitted is None:
            segments.append(SketchPathSegment("line", ring[index], ring[index + 1]))
            index += 1
    segments.append(SketchPathSegment("line", ring[-1], ring[0]))
    return tuple(segments)


def _clean_open(profile: tuple[Point, ...] | list[Point]) -> list[Point]:
    cleaned: list[Point] = []
    for raw_x, raw_y in profile:
        if raw_y < -0.05:
            raise ValueError("半边轮廓越过了轴线，已中止生成。")
        point = (float(raw_x), 0.0 if raw_y <= 1e-3 else float(raw_y))
        if not cleaned or math.dist(cleaned[-1], point) > 1e-4:
            cleaned.append(point)
    if len(cleaned) > 1 and math.dist(cleaned[0], cleaned[-1]) <= 1e-4:
        cleaned.pop()
    if len(cleaned) < 3:
        raise ValueError("半边轮廓点数不足，无法生成。")
    return cleaned


def _signed_area(points: list[Point]) -> float:
    area = 0.0
    for start, end in zip(points, points[1:] + points[:1]):
        area += start[0] * end[1] - end[0] * start[1]
    return area / 2.0


def _reject_self_intersection(points: list[Point]) -> None:
    ring = points[:-1] if math.dist(points[0], points[-1]) <= 1e-4 else points
    segments = list(zip(ring, ring[1:] + ring[:1]))
    for index, (start, end) in enumerate(segments):
        for other in range(index + 1, len(segments)):
            if other == index + 1 or (index == 0 and other == len(segments) - 1):
                continue
            if _proper_cross(start, end, segments[other][0], segments[other][1]):
                raise ValueError(
                    "半边轮廓自交，已中止，避免旋成废片。"
                    " 多半是这张图不是单件回转体：焊接组合件、半剖视图，"
                    "或一张图里画了好几件。请单件单独出图再试。"
                )


def _proper_cross(start: Point, end: Point, other_start: Point, other_end: Point) -> bool:
    def side(origin: Point, along: Point, point: Point) -> float:
        return (along[0] - origin[0]) * (point[1] - origin[1]) - (
            along[1] - origin[1]
        ) * (point[0] - origin[0])

    left = side(start, end, other_start)
    right = side(start, end, other_end)
    across = side(other_start, other_end, start)
    back = side(other_start, other_end, end)
    epsilon = 1e-6
    if (
        abs(left) <= epsilon
        or abs(right) <= epsilon
        or abs(across) <= epsilon
        or abs(back) <= epsilon
    ):
        return False
    return (left > 0) != (right > 0) and (across > 0) != (back > 0)
