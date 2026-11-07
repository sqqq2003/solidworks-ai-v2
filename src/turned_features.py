# -*- coding: utf-8 -*-
"""从图纸文字和尺寸得到键槽、孔、螺纹、倒角和端部车削。

这里只算几何，不连接 SolidWorks。轴向 0 与旋转草图一致，是外形最小轴向坐标。
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from roller_drawing import decode_solidworks_text

Point = tuple[float, float]

_KEY_3 = re.compile(
    r"(\d+(?:\.\d+)?)\s*[xX×*]\s*(\d+(?:\.\d+)?)\s*[xX×*]\s*(\d+(?:\.\d+)?)"
    r"\s*(?:mm)?\s*键[槽糟]"
)
_KEY_2 = re.compile(
    r"(\d+(?:\.\d+)?)\s*[xX×*]\s*(\d+(?:\.\d+)?)\s*(?:mm)?\s*键[槽糟]"
)
_KEY_DASH = re.compile(
    r"(\d+(?:\.\d+)?)\s*[-－]\s*(\d+(?:\.\d+)?)\s*深\s*键[槽糟]"
)
_EXTERNAL = re.compile(
    r"外(?:牙|螺纹)\s*M\s*(\d+(?:\.\d+)?)(?:\s*[xX×*]\s*(\d+(?:\.\d+)?))?",
    re.IGNORECASE,
)
_INTERNAL = re.compile(
    r"(?:内\s*)?M\s*(\d+(?:\.\d+)?)\s*[xX×*\-－]\s*(\d+(?:\.\d+)?)\s*深",
    re.IGNORECASE,
)
_PLAIN_THREAD = re.compile(
    r"M\s*(\d+(?:\.\d+)?)(?:\s*[xX×*]\s*(\d+(?:\.\d+)?))?",
    re.IGNORECASE,
)
_DRILL = re.compile(
    r"(?:Φ|φ|⌀|Ø|∅)\s*(\d+(?:\.\d+)?)\s*(?:深|[xX×*])\s*(\d+(?:\.\d+)?)"
)
_CHAMFER = re.compile(r"倒角\s*C\s*(\d+(?:\.\d+)?)", re.IGNORECASE)
_TEETH = re.compile(r"(\d+)\s*齿")
_MTEXT_GROUP = re.compile(r"\{[^;]*;([^}]*)\}")
_DIAMETER_TEXT = re.compile(r"(?:%%[cC]|Φ|φ|⌀|Ø|∅)\s*(\d+(?:\.\d+)?)")

# 粗牙底孔。没有的规格用公称直径减螺距。
_TAP_DRILL = {3: 2.5, 4: 3.3, 5: 4.2, 6: 5.0, 8: 6.8, 10: 8.5, 12: 10.2, 16: 14.0, 20: 17.5}
_COARSE_PITCH = {3: 0.5, 4: 0.7, 5: 0.8, 6: 1.0, 8: 1.25, 10: 1.5, 12: 1.75, 16: 2.0, 20: 2.5}


@dataclass(frozen=True)
class NoteRecord:
    text: str
    x: float | None = None
    y: float | None = None
    measurement: float | None = None


@dataclass(frozen=True)
class KeywaySpec:
    width_mm: float
    depth_mm: float
    length_mm: float
    start_mm: float
    surface_radius_mm: float
    on_bore: bool = False
    from_drawing: bool = False

    @property
    def end_mm(self) -> float:
        return self.start_mm + self.length_mm


@dataclass(frozen=True)
class EndTurnSpec:
    """六角或方钢端部车到给定半径。start 从轴向 0 起。"""

    start_mm: float
    length_mm: float
    radius_mm: float
    thread: str = ""


@dataclass(frozen=True)
class BoreSpec:
    start_mm: float
    length_mm: float
    radius_mm: float


def plain_note(text: str) -> str:
    """去掉 SolidWorks 的 \\U+ 和 MTEXT 字体包装。"""

    decoded = decode_solidworks_text(text or "")
    decoded = decoded.replace("%%C", "Ø").replace("%%c", "Ø")
    pieces = _MTEXT_GROUP.findall(decoded)
    if pieces:
        decoded = "".join(pieces)
    decoded = re.sub(r"\\[A-Za-z][^;]*;", "", decoded)
    return decoded.replace("{", "").replace("}", "").strip()


def tap_drill_mm(major_mm: float) -> float:
    size = int(round(major_mm))
    if size in _TAP_DRILL and abs(size - major_mm) < 0.2:
        return _TAP_DRILL[size]
    pitch = _COARSE_PITCH.get(size, 1.0)
    return max(0.5, major_mm - pitch)


def coarse_pitch_mm(major_mm: float, given: float | None = None) -> float:
    if given is not None and given > 0:
        return given
    return _COARSE_PITCH.get(int(round(major_mm)), 1.0)


def parse_keyways(text: str) -> list[tuple[float, float, float | None]]:
    """返回 (宽, 深, 长或 None)。长在三连尺寸里，两连或「宽-深深」可以没有长。"""

    found: list[tuple[float, float, float | None]] = []
    used: list[tuple[int, int]] = []
    for match in _KEY_3.finditer(text):
        found.append((float(match.group(1)), float(match.group(2)), float(match.group(3))))
        used.append(match.span())
    for match in _KEY_2.finditer(text):
        if any(start <= match.start() < end for start, end in used):
            continue
        found.append((float(match.group(1)), float(match.group(2)), None))
    for match in _KEY_DASH.finditer(text):
        found.append((float(match.group(1)), float(match.group(2)), None))
    return found


def parse_chamfer_mm(text: str) -> float | None:
    match = _CHAMFER.search(text)
    if match is None:
        return None
    size = float(match.group(1))
    if size <= 0 or size > 5:
        return None
    return size


def collect_records(analysis) -> list[NoteRecord]:
    """文字实体，再加上 DXF 里 DIMENSION 的覆盖文字。"""

    records: list[NoteRecord] = []
    for note in getattr(analysis, "text_entities", ()) or ():
        text = plain_note(getattr(note, "text", "") or "")
        if text:
            records.append(NoteRecord(text, getattr(note, "x", None), getattr(note, "y", None)))
    if not records:
        for text in getattr(analysis, "texts", ()) or ():
            cleaned = plain_note(text)
            if cleaned:
                records.append(NoteRecord(cleaned))
    # DIMENSION 要用 ezdxf 读，DWG 读不了；优先用 DWG 转换出的那份 DXF。
    path = getattr(analysis, "dxf_path", None)
    if path is None or not getattr(path, "is_file", lambda: False)():
        path = getattr(analysis, "path", None)
    if path is not None and getattr(path, "is_file", lambda: False)():
        records.extend(_dimension_records(path))
    return records


_FEATURE_HINT = re.compile(
    r"键[槽糟]|螺纹|外牙|滚花|链轮|焊接|倒角|M\s*\d",
    re.IGNORECASE,
)


def features_near(records: list[NoteRecord], bounds: tuple[float, float, float, float] | None, analysis=None):
    """零件附近的文字。端面详图可以离主视图一段距离，但不能算到旁边另一根轴上。"""

    if bounds is None:
        return records
    min_x, min_y, max_x, max_y = bounds
    span = max(max_x - min_x, max_y - min_y, 1.0)
    margin = max(40.0, 0.8 * span)
    detail = max(180.0, margin)
    others = _other_part_bounds(analysis, bounds)
    kept = []
    for record in records:
        if record.x is None or record.y is None:
            kept.append(record)
            continue
        hinted = bool(_FEATURE_HINT.search(record.text or ""))
        near = (
            min_x - margin <= record.x <= max_x + margin
            and min_y - margin <= record.y <= max_y + margin
        )
        if not near and not hinted and not _span_hits_part(record, bounds):
            continue
        if hinted or _span_hits_part(record, bounds):
            dist = _distance_to_bounds(record.x, record.y, bounds)
            if dist > detail and not _span_hits_part(record, bounds):
                continue
            if others:
                nearest = min(_distance_to_bounds(record.x, record.y, other) for other in others)
                # 文字落在旁边另一根轴上时不要算进来。端面详图不算另一根轴。
                if nearest + 15.0 < dist:
                    continue
        kept.append(record)
    return kept


# 标题栏、明细表行、注释框在 DXF 里同样是「闭合矩形」，但它们只有 4~6 个点、
# 且短边只有 10~20mm；真正另一件车件的轮廓是曲线 tessellate 出来的，点数远多于此。
_OTHER_PART_MIN_POINTS = 8
_OTHER_PART_MIN_SIDE_MM = 8.0


def _other_part_bounds(analysis, bounds) -> list[tuple[float, float, float, float]]:
    """旁边另一件的外形。图框、端面圆、贴在本件上的小环、标题栏和注释框都不算。"""

    if analysis is None:
        return []
    try:
        from turned_outline import is_round_profile, is_sheet_frame
    except Exception:
        return []
    found = []
    for profile in getattr(analysis, "profiles", ()) or ():
        if not getattr(profile, "closed", False) or len(getattr(profile, "points", ())) < 4:
            continue
        try:
            if is_round_profile(profile) or is_sheet_frame(profile, analysis):
                continue
        except Exception:
            continue
        points = profile.points
        box = (
            min(point[0] for point in points),
            min(point[1] for point in points),
            max(point[0] for point in points),
            max(point[1] for point in points),
        )
        if _boxes_same(box, bounds) or _contains(box, bounds) or _contains(bounds, box):
            continue
        if _overlaps(box, bounds):
            continue
        width = box[2] - box[0]
        height = box[3] - box[1]
        if max(width, height) < 30.0:
            continue
        # 光靠「够大」还不够：标题栏格子能有好几十毫米宽。零件轮廓是曲线拆出来的，
        # 点数远多于一个方框，短边也不会只有十几毫米。
        if len(points) < _OTHER_PART_MIN_POINTS or min(width, height) < _OTHER_PART_MIN_SIDE_MM:
            continue
        found.append(box)
    return found


def _contains(outer, inner) -> bool:
    return (
        outer[0] <= inner[0] + 1.0
        and outer[1] <= inner[1] + 1.0
        and outer[2] >= inner[2] - 1.0
        and outer[3] >= inner[3] - 1.0
    )


def _overlaps(left, right) -> bool:
    return not (
        left[2] < right[0] - 1.0
        or right[2] < left[0] - 1.0
        or left[3] < right[1] - 1.0
        or right[3] < left[1] - 1.0
    )


def _boxes_same(left, right) -> bool:
    return all(abs(a - b) < 0.5 for a, b in zip(left, right))


def _distance_to_bounds(x: float, y: float, bounds) -> float:
    min_x, min_y, max_x, max_y = bounds
    dx = 0.0 if min_x <= x <= max_x else min(abs(x - min_x), abs(x - max_x))
    dy = 0.0 if min_y <= y <= max_y else min(abs(y - min_y), abs(y - max_y))
    return math.hypot(dx, dy)


def _span_hits_part(record: NoteRecord, bounds: tuple[float, float, float, float]) -> bool:
    span = getattr(record, "span", None)
    if not span:
        return False
    min_x, min_y, max_x, max_y = bounds
    overlaps_x = not (span[1] < min_x - 5.0 or span[0] > max_x + 5.0)
    overlaps_y = not (span[3] < min_y - 30.0 or span[2] > max_y + 30.0)
    return overlaps_x and overlaps_y


def attach_feature_fields(plan, analysis):
    """返回 replace() 用的字段。不改轮廓。"""

    from dataclasses import replace as _replace

    records = features_near(collect_records(analysis), getattr(plan, "bounds", None), analysis)
    blob = "\n".join(record.text for record in records)
    shift = min(point[0] for point in plan.profile)
    length = float(plan.length_mm)
    horizontal = getattr(plan, "axis", "horizontal") == "horizontal"
    path = getattr(analysis, "path", None)

    keyways = _place_keyways(plan, records, shift, length, horizontal, path)
    bores = _place_bores(plan, records, shift, length, path, keyways)
    keyways, pending_keyways = _keyways_on_bores(keyways, bores, length, float(plan.max_radius_mm))
    holes, threads = _place_holes_and_threads(plan, records, shift, length, horizontal)
    end_turns = ()
    if getattr(plan, "stock", "") == "hex" and plan.stock_size_mm:
        end_turns = tuple(
            _label_end_threads(turn, threads, length)
            for turn in _hex_end_turns(plan.profile, plan.stock_size_mm[0], shift)
        )
        holes = _drop_holes_covered_by_turns(holes, end_turns)
    chamfer = 0.0
    for record in records:
        size = parse_chamfer_mm(record.text)
        if size is not None:
            chamfer = size
            break
    knurl = "外圆滚花" if "滚花" in blob else ""
    teeth_match = _TEETH.search(blob)
    teeth = int(teeth_match.group(1)) if teeth_match and "链轮" in blob else 0
    hand: list[str] = list(pending_keyways)
    if "焊接" in blob:
        hand.append("焊接件，当前只回转外轮廓，焊缝需手修")
    if knurl:
        hand.append("外圆滚花只写入属性，未建纹理")
    if teeth or "链轮" in blob:
        hand.append("链轮只建轮毂圆柱，齿形未做")
    return _replace(
        plan,
        threads=threads,
        holes=holes,
        keyways=tuple(keyways),
        bores=tuple(bores),
        end_turns=tuple(end_turns),
        chamfer_mm=chamfer,
        knurl=knurl,
        teeth=teeth,
        hand_finish=tuple(hand),
    )


def keyway_rectangle(keyway: KeywaySpec) -> tuple[tuple[Point, ...], float]:
    """前视草图上的切除矩形（轴向, 半径）和槽宽。矩形穿过表面，拉伸对称于该面。"""

    if keyway.length_mm <= 0 or keyway.width_mm <= 0 or keyway.depth_mm <= 0:
        raise ValueError("键槽尺寸无效，已中止。")
    if keyway.on_bore:
        inner = max(0.2, keyway.surface_radius_mm - 0.4)
        outer = keyway.surface_radius_mm + keyway.depth_mm
    else:
        if keyway.depth_mm >= keyway.surface_radius_mm:
            raise ValueError(
                f"键槽深 {keyway.depth_mm:g} mm 不小于当地半径 "
                f"{keyway.surface_radius_mm:g} mm，已中止。"
            )
        inner = keyway.surface_radius_mm - keyway.depth_mm
        outer = keyway.surface_radius_mm + 0.6
    x0 = keyway.start_mm
    x1 = keyway.end_mm
    rectangle = (
        (x0, inner),
        (x1, inner),
        (x1, outer),
        (x0, outer),
        (x0, inner),
    )
    return rectangle, keyway.width_mm


def chamfer_triangles(
    profile: tuple[Point, ...] | list[Point],
    chamfer_mm: float,
) -> tuple[tuple[Point, ...], ...]:
    """两端外圆角上的 45° 三角形，绕轴线切除。半径已经让过倒角的一端不再切。"""

    if chamfer_mm <= 0.05:
        return ()
    shift = min(point[0] for point in profile)
    upper = [(point[0] - shift, point[1]) for point in profile if point[1] > 0.2]
    if len(upper) < 2:
        return ()
    length = max(point[0] for point in profile) - shift
    cuts: list[tuple[Point, ...]] = []
    for at_end in (False, True):
        if at_end:
            end_x = length
            radius = _radius_near(upper, end_x)
            if _already_relieved(upper, end_x, chamfer_mm, from_end=True):
                continue
            if radius <= chamfer_mm + 0.2:
                continue
            cuts.append(
                (
                    (end_x - chamfer_mm, radius),
                    (end_x, radius),
                    (end_x, radius - chamfer_mm),
                    (end_x - chamfer_mm, radius),
                )
            )
        else:
            radius = _radius_near(upper, 0.0)
            if _already_relieved(upper, 0.0, chamfer_mm, from_end=False):
                continue
            if radius <= chamfer_mm + 0.2:
                continue
            cuts.append(
                (
                    (0.0, radius - chamfer_mm),
                    (0.0, radius),
                    (chamfer_mm, radius),
                    (0.0, radius - chamfer_mm),
                )
            )
    return tuple(cuts)


def _place_keyways(plan, records, shift: float, length: float, horizontal: bool, path) -> list[KeywaySpec]:
    parsed: list[tuple[float, float, float | None, NoteRecord]] = []
    for record in records:
        for width, depth, key_length in parse_keyways(record.text):
            parsed.append((width, depth, key_length, record))
    if not parsed:
        return []
    # 同一宽深，有长度的那条覆盖断面里没写长度的重复标注。
    ranked = sorted(parsed, key=lambda item: (item[2] is None, item[0], item[1]))
    chosen: list[tuple[float, float, float | None, NoteRecord]] = []
    for item in ranked:
        width, depth, key_length, _record = item
        if any(
            abs(width - other[0]) < 0.15 and abs(depth - other[1]) < 0.15
            for other in chosen
        ):
            continue
        chosen.append(item)
    slots = _drawn_slots(plan, path)
    specs: list[KeywaySpec] = []
    for width, depth, key_length, record in chosen:
        slot = _matching_slot(slots, width, shift, length)
        drawn = slot is not None
        if key_length is None and slot is not None:
            key_length = slot[1] - slot[0]
        if slot is not None:
            start = slot[0] - shift
        elif key_length is None:
            start = 0.0
        else:
            start = _default_keyway_start(plan, record, shift, length, horizontal, key_length)
        start = max(0.0, start)
        if key_length is None:
            specs.append(KeywaySpec(width, depth, 0.0, start, 0.0, False, False))
            continue
        if start + key_length > length + 0.3:
            raise ValueError(
                f"键槽长 {key_length:g} mm 从 {start:.2f} mm 起超出零件 {length:.2f} mm，已中止。"
            )
        key_length = min(key_length, length - start)
        surface = _radius_near(
            [(point[0] - shift, point[1]) for point in plan.profile if point[1] > 0.2],
            start + key_length / 2.0,
        )
        specs.append(KeywaySpec(width, depth, key_length, start, surface, False, drawn))
    return specs


def _keyways_on_bores(
    keyways: list[KeywaySpec],
    bores: list[BoreSpec],
    length: float,
    max_radius: float,
) -> tuple[list[KeywaySpec], tuple[str, ...]]:
    """侧视没有槽线、只在端面详图里标注的键槽，挂到最长的中孔上。

    返回（能建的槽, 待手修说明）。图上只写了宽深没写槽长、又找不到中孔可挂时，
    记一条待手修并跳过这条槽——一处漏标不该让整件都出不来。
    """

    bore = max(bores, key=lambda item: item.length_mm) if bores else None
    moved: list[KeywaySpec] = []
    pending: list[str] = []
    for keyway in keyways:
        if keyway.on_bore:
            moved.append(keyway)
            continue
        unresolved = keyway.length_mm <= 0.0
        on_outer = keyway.surface_radius_mm >= max_radius - 1.5
        move = bore is not None and (
            unresolved or (not keyway.from_drawing and on_outer and keyway.start_mm > 2.0)
        )
        if move and bore is not None:
            span = bore.length_mm if unresolved else min(keyway.length_mm, bore.length_mm)
            if span <= 0 or span > length + 0.3:
                pending.append(f"中孔键槽 {keyway.width_mm:g}×{keyway.depth_mm:g} 比零件还长，未建槽")
                continue
            moved.append(
                KeywaySpec(
                    keyway.width_mm,
                    keyway.depth_mm,
                    span,
                    bore.start_mm,
                    bore.radius_mm,
                    True,
                    False,
                )
            )
            continue
        if unresolved:
            pending.append(
                f"键槽 {keyway.width_mm:g}×{keyway.depth_mm:g} 未标槽长，也没画出槽长，未建槽"
            )
            continue
        moved.append(keyway)
    return moved, tuple(pending)


def _place_bores(plan, records, shift, length, path, keyways) -> list[BoreSpec]:
    diameters = []
    for record in records:
        cleaned = record.text.replace("%%C", "Ø").replace("%%c", "Ø")
        for match in _DIAMETER_TEXT.finditer(cleaned):
            diameters.append(float(match.group(1)))
        if record.measurement and record.text and _DIAMETER_TEXT.search(cleaned):
            diameters.append(float(record.measurement))
        elif record.measurement and re.match(r"^\s*[ØΦφ⌀∅]", cleaned):
            # SolidWorks 导出的直径尺寸覆盖文字常是「Ø<>」占位，数值只在
            # measurement 里；带直径符号就算直径，用实测值。
            diameters.append(float(record.measurement))
    key_widths = {round(item.width_mm, 1) for item in keyways}
    upper = [(point[0] - shift, point[1]) for point in plan.profile if point[1] > 0.2]
    bores: list[BoreSpec] = []
    for start, end, radius in _symmetric_pairs(plan, path):
        diameter = 2.0 * radius
        if any(abs(diameter - width) <= 0.25 for width in key_widths):
            continue
        if not any(abs(diameter - listed) <= 0.4 for listed in diameters):
            continue
        local_outer = _min_radius_along(upper, start - shift, end - shift)
        # 和外形重合的是台阶外圆，不是中孔。
        if radius > local_outer - 2.0:
            continue
        axial_start = max(0.0, start - shift)
        axial_end = min(length, end - shift)
        if axial_end - axial_start < 3.0:
            continue
        bores.append(BoreSpec(axial_start, axial_end - axial_start, radius))
    # 同一半径留最长的一段。
    bores.sort(key=lambda item: item.length_mm, reverse=True)
    kept: list[BoreSpec] = []
    for bore in bores:
        if any(abs(bore.radius_mm - other.radius_mm) < 0.3 for other in kept):
            continue
        kept.append(bore)
    return kept


def _place_holes_and_threads(plan, records, shift, length, horizontal):
    from turned_part import TurnedHole, TurnedThread

    holes: list[TurnedHole] = []
    threads: list[TurnedThread] = []
    seen_holes: dict[tuple[float, str], bool] = {}
    seen_threads: set[str] = set()

    def add_thread(size: float, pitch: float | None, text: str, record: NoteRecord, internal: bool):
        pitch_mm = coarse_pitch_mm(size, pitch)
        designation = f"M{size:g}" if pitch is None else f"M{size:g}×{pitch_mm:g}"
        key = designation + ("内" if internal else "外")
        if key in seen_threads:
            return designation
        seen_threads.add(key)
        threads.append(
            TurnedThread(designation, None if pitch is None else pitch_mm, text, record.x, record.y)
        )
        return designation

    def add_hole(diameter: float, depth: float, text: str, record: NoteRecord, thread: str):
        # 同径同螺纹视为同一个孔（同一孔常被标两次：裸 M12 + 内M12-25深）。
        key = (round(diameter, 3), thread)
        explicit = "深" in (text or "")
        if key in seen_holes:
            if explicit and not seen_holes[key]:
                for index, existing in enumerate(holes):
                    if (round(existing.diameter_mm, 3), existing.thread) == key:
                        holes[index] = TurnedHole(
                            diameter, depth, text, record.x, record.y, thread, bool(thread)
                        )
                        seen_holes[key] = True
                        break
            return
        if depth <= 0 or diameter <= 0:
            return
        seen_holes[key] = explicit
        holes.append(
            TurnedHole(diameter, depth, text, record.x, record.y, thread, bool(thread))
        )

    for record in records:
        text = record.text
        for match in _EXTERNAL.finditer(text):
            size = float(match.group(1))
            pitch = float(match.group(2)) if match.group(2) else None
            add_thread(size, pitch, text, record, False)
        for match in _INTERNAL.finditer(text):
            size = float(match.group(1))
            depth = float(match.group(2))
            designation = add_thread(size, None, text, record, True)
            add_hole(tap_drill_mm(size), depth, text, record, designation)
        if _EXTERNAL.search(text) or _INTERNAL.search(text):
            pass
        else:
            for match in _PLAIN_THREAD.finditer(text):
                size = float(match.group(1))
                pitch = float(match.group(2)) if match.group(2) else None
                # 「M6」单独出现、没有深，先记螺纹。深度能对上邻近轴向尺寸时再钻孔。
                designation = add_thread(size, pitch, text, record, False)
                depth = _depth_beside(records, record, plan, shift, length, horizontal, size)
                if depth is not None and "外" not in text:
                    add_hole(tap_drill_mm(size), depth, text, record, designation)
        drill = _DRILL.search(text)
        if drill is not None and not _PLAIN_THREAD.search(text):
            add_hole(float(drill.group(1)), float(drill.group(2)), text, record, "")
    return tuple(holes), tuple(threads)


def _depth_beside(records, record, plan, shift, length, horizontal, major: float) -> float | None:
    """裸 M 尺寸旁边、从同一端量起的轴向长度，当作螺纹孔深。"""

    if record.x is None:
        return None
    axial = record.x if horizontal else record.y
    if axial is None:
        return None
    part_axial = axial - shift
    at_start = part_axial <= length / 2.0
    # 同一端上可能既有孔深，也有六角段的长度。取最短的那一段。
    candidates: list[float] = []
    for other in records:
        if other.measurement is None or other.measurement <= 0:
            continue
        if other.text and (_DIAMETER_TEXT.search(other.text) or "键" in other.text or "M" in other.text.upper()):
            continue
        depth = float(other.measurement)
        if depth < max(6.0, major) or depth > min(length * 0.8, 80.0):
            continue
        if abs(depth - length) / max(length, 1) < 0.02:
            continue
        span = _dimension_span(other, horizontal)
        if span is None:
            continue
        span_start, span_end = span
        local_start = span_start - shift
        local_end = span_end - shift
        if at_start and local_start <= 2.0 and abs((local_end - local_start) - depth) < 1.0:
            candidates.append(depth)
        elif not at_start and abs(local_end - length) <= 2.0 and abs((local_end - local_start) - depth) < 1.0:
            candidates.append(depth)
    if not candidates:
        return None
    return min(candidates)


def _hex_end_turns(profile, across_flats: float, shift: float) -> list[EndTurnSpec]:
    circum = across_flats / math.sqrt(3.0)
    upper = sorted(
        ((point[0] - shift, point[1]) for point in profile if point[1] > 0.2),
        key=lambda point: point[0],
    )
    if len(upper) < 2:
        return []
    reduced = [point for point in upper if point[1] < circum - 0.4]
    if not reduced:
        return []
    # 把相邻的降低段收成一段。倒角只有零点几毫米，并进相邻的车削段。
    low_at = [index for index, point in enumerate(upper) if point[1] < circum - 0.4]
    groups: list[list[int]] = [[low_at[0]]]
    for previous, index in zip(low_at, low_at[1:]):
        recovered = any(point[1] >= circum - 0.4 for point in upper[previous + 1 : index])
        if recovered:
            groups.append([index])
        else:
            groups[-1].append(index)
    spans = [[upper[index] for index in group] for group in groups]
    turns: list[EndTurnSpec] = []
    for span in spans:
        start = span[0][0]
        end = span[-1][0]
        # 把段首尾的短倒角算进长度：向两侧吃到半径回到外接圆之前。
        start, end = _expand_to_shoulder(upper, start, end, circum)
        if end - start < 3.0:
            continue
        radius = _plateau_radius(span)
        if radius <= 0.5:
            continue
        turns.append(EndTurnSpec(start, end - start, radius, ""))
    return turns


def _expand_to_shoulder(upper, start, end, circum) -> tuple[float, float]:
    xs = [point[0] for point in upper]
    left = start
    right = end
    for point in upper:
        if start - 2.0 <= point[0] < start and point[1] < circum - 0.15:
            left = min(left, point[0])
        if end < point[0] <= end + 2.0 and point[1] < circum - 0.15:
            right = max(right, point[0])
    if xs:
        left = max(min(xs), left)
        right = min(max(xs), right)
    return left, right


def _plateau_radius(span: list[Point]) -> float:
    best_radius = span[0][1]
    best_cover = -1.0
    radii = sorted({round(point[1], 1) for point in span})
    for radius in radii:
        cover = 0.0
        for start, end in zip(span, span[1:]):
            if abs(start[1] - radius) <= 0.15 and abs(end[1] - radius) <= 0.15:
                cover += abs(end[0] - start[0])
        if cover > best_cover:
            best_cover = cover
            best_radius = radius
    return best_radius


def _label_end_threads(turn: EndTurnSpec, threads, length: float) -> EndTurnSpec:
    from turned_part import TurnedThread

    best = ""
    best_distance = 1e9
    for thread in threads:
        if not isinstance(thread, TurnedThread):
            continue
        if "外" not in thread.text and "牙" not in thread.text:
            continue
        size = _thread_major(thread.designation)
        if size is None or abs(size / 2.0 - turn.radius_mm) > 1.2:
            continue
        if thread.x is None:
            distance = 0.0
        else:
            distance = abs(thread.x)
        if distance < best_distance:
            best_distance = distance
            best = thread.designation.split("×")[0]
    if not best:
        return turn
    return EndTurnSpec(turn.start_mm, turn.length_mm, turn.radius_mm, best)


def _drop_holes_covered_by_turns(holes, turns):
    """外螺纹车削段上不要再钻一个同规格的孔。"""

    kept = []
    for hole in holes:
        major = _thread_major(hole.thread) if hole.thread else None
        covered = False
        if major is not None:
            for turn in turns:
                if turn.thread and abs(major / 2.0 - turn.radius_mm) < 1.0:
                    if hole.x is not None and abs((turn.start_mm + turn.length_mm) - 0) >= 0:
                        # 孔的图面坐标靠近车削段外端时，这是外螺纹不是孔。
                        covered = "外" in hole.text or "牙" in hole.text
        if not covered:
            kept.append(hole)
    return tuple(kept)


def _thread_major(designation: str) -> float | None:
    match = re.search(r"M\s*(\d+(?:\.\d+)?)", designation or "", re.IGNORECASE)
    if match is None:
        return None
    return float(match.group(1))


def _default_keyway_start(plan, record, shift, length, horizontal, key_length) -> float:
    axial = None
    if horizontal and record.x is not None:
        axial = record.x - shift
    elif not horizontal and record.y is not None:
        axial = record.y - shift
    if axial is None or axial < -20 or axial > length + 20:
        return max(0.0, (length - key_length) / 2.0)
    return max(0.0, axial - key_length / 2.0)


def _radius_near(upper: list[Point], axial: float) -> float:
    if not upper:
        return 0.0
    upper = sorted(upper, key=lambda point: point[0])
    if axial <= upper[0][0]:
        return upper[0][1]
    if axial >= upper[-1][0]:
        return upper[-1][1]
    for start, end in zip(upper, upper[1:]):
        if start[0] <= axial <= end[0] and end[0] > start[0]:
            factor = (axial - start[0]) / (end[0] - start[0])
            return start[1] + factor * (end[1] - start[1])
    return max(point[1] for point in upper)


def _already_relieved(upper, end_x, chamfer, *, from_end: bool) -> bool:
    if from_end:
        inner = [point for point in upper if end_x - chamfer - 0.3 <= point[0] <= end_x - 0.05]
        edge = _radius_near(upper, end_x)
    else:
        inner = [point for point in upper if 0.05 <= point[0] <= chamfer + 0.3]
        edge = _radius_near(upper, 0.0)
    if not inner:
        return False
    return max(point[1] for point in inner) >= edge + 0.25


def _matching_slot(
    slots: list[tuple[float, float, float]],
    width: float,
    shift: float,
    length: float,
):
    ranked: list[tuple[float, float, float, float]] = []
    for start, end, slot_width in slots:
        if abs(slot_width - width) > 0.3 or end - start < 5.0:
            continue
        local_start = start - shift
        local_end = end - shift
        overlap = min(local_end, length) - max(local_start, 0.0)
        if overlap < 5.0:
            continue
        ranked.append((overlap, start, end, slot_width))
    if not ranked:
        return None
    ranked.sort(reverse=True)
    _overlap, start, end, slot_width = ranked[0]
    return (start, end, slot_width)


def _drawn_slots(plan, path) -> list[tuple[float, float, float]]:
    """关于轴线对称、间距等于槽宽的两条轴向直线。返回图面坐标。"""

    if path is None or not getattr(path, "is_file", lambda: False)():
        return []
    axis_pos = float(plan.axis_position)
    horizontal = plan.axis == "horizontal"
    lines = _axis_parallel_lines(path, horizontal)
    slots = []
    for index, first in enumerate(lines):
        for second in lines[index + 1 :]:
            gap = abs(first[0] - second[0])
            if gap < 2.0 or gap > 30.0:
                continue
            mid = (first[0] + second[0]) / 2.0
            if abs(mid - axis_pos) > 0.8:
                continue
            start = max(min(first[1], first[2]), min(second[1], second[2]))
            end = min(max(first[1], first[2]), max(second[1], second[2]))
            if end - start < 5.0:
                continue
            slots.append((start, end, gap))
    return slots


def _symmetric_pairs(plan, path) -> list[tuple[float, float, float]]:
    if path is None or not getattr(path, "is_file", lambda: False)():
        return []
    axis_pos = float(plan.axis_position)
    horizontal = plan.axis == "horizontal"
    lines = _axis_parallel_lines(path, horizontal)
    pairs = []
    for index, first in enumerate(lines):
        for second in lines[index + 1 :]:
            if abs((first[0] + second[0]) / 2.0 - axis_pos) > 0.6:
                continue
            radius = abs(first[0] - axis_pos)
            if abs(abs(second[0] - axis_pos) - radius) > 0.4:
                continue
            if radius < 1.0:
                continue
            start = max(min(first[1], first[2]), min(second[1], second[2]))
            end = min(max(first[1], first[2]), max(second[1], second[2]))
            if end - start < 5.0:
                continue
            pairs.append((start, end, radius))
    return pairs


_SKIP_LAYERS = {"标注线", "中心线", "尺寸", "defpoints", "尺寸线"}


def _min_radius_along(upper: list[Point], start: float, end: float) -> float:
    if not upper:
        return 0.0
    if end < start:
        start, end = end, start
    samples = [start, end, (start + end) / 2.0]
    return min(_radius_near(upper, axial) for axial in samples)


def _axis_parallel_lines(path, horizontal: bool) -> list[tuple[float, float, float]]:
    """返回 (横向坐标, 轴向起点, 轴向终点)。"""

    try:
        import ezdxf
    except ImportError:
        return []
    try:
        document = ezdxf.readfile(path)
    except Exception:
        return []
    found: list[tuple[float, float, float]] = []
    for entity in document.modelspace():
        layer = str(getattr(entity.dxf, "layer", "") or "")
        if layer.casefold() in _SKIP_LAYERS or layer in _SKIP_LAYERS:
            continue
        segments = []
        if entity.dxftype() == "LINE":
            segments.append(
                ((entity.dxf.start.x, entity.dxf.start.y), (entity.dxf.end.x, entity.dxf.end.y))
            )
        elif entity.dxftype() == "LWPOLYLINE":
            points = [(point[0], point[1]) for point in entity.get_points("xy")]
            segments.extend(zip(points, points[1:]))
        for start, end in segments:
            if horizontal:
                if abs(start[1] - end[1]) > 0.25:
                    continue
                if abs(start[0] - end[0]) < 5.0:
                    continue
                found.append((start[1], min(start[0], end[0]), max(start[0], end[0])))
            else:
                if abs(start[0] - end[0]) > 0.25:
                    continue
                if abs(start[1] - end[1]) < 5.0:
                    continue
                found.append((start[0], min(start[1], end[1]), max(start[1], end[1])))
    return found


def _dimension_records(path) -> list[NoteRecord]:
    try:
        import ezdxf
    except ImportError:
        return []
    try:
        document = ezdxf.readfile(path)
    except Exception:
        return []
    # 尺寸可能在任一布局（SolidWorks 导出常放在 SW_Model_1 图纸布局）。
    seen: set[tuple] = set()
    records: list[NoteRecord] = []
    for layout in document.layouts:
        for entity in layout:
            if entity.dxftype() != "DIMENSION":
                continue
            for record in _dimension_record(entity):
                key = (record.text, None if record.x is None else round(record.x, 3), None if record.y is None else round(record.y, 3))
                if key in seen:
                    continue
                seen.add(key)
                records.append(record)
    return records


def _dimension_record(entity) -> list[NoteRecord]:
    text = plain_note(str(entity.dxf.text or ""))
    try:
        measurement = float(entity.get_measurement())
    except Exception:
        measurement = None
    point = None
    if entity.dxf.hasattr("text_midpoint"):
        mid = entity.dxf.text_midpoint
        point = (float(mid.x), float(mid.y))
    elif entity.dxf.hasattr("defpoint"):
        mid = entity.dxf.defpoint
        point = (float(mid.x), float(mid.y))
    span = None
    if entity.dxf.hasattr("defpoint2") and entity.dxf.hasattr("defpoint3"):
        start = entity.dxf.defpoint2
        end = entity.dxf.defpoint3
        span = (min(start.x, end.x), max(start.x, end.x), min(start.y, end.y), max(start.y, end.y))
    found: list[NoteRecord] = []
    if text or (measurement is not None and measurement > 0):
        record = NoteRecord(
            text or "",
            None if point is None else point[0],
            None if point is None else point[1],
            measurement,
        )
        if span is not None:
            record = _NoteWithSpan(record.text, record.x, record.y, record.measurement, span)
        found.append(record)
    # SolidWorks 导出把真正的标注文字（如「内M12-25深」「M12」）放进
    # DIMENSION 的几何块里，覆盖文字只剩「%%c<>」这种占位。块内文字
    # 才是螺纹/孔规格的来源，逐条补成记录。
    found.extend(_dimension_block_records(entity, point))
    return found


def _dimension_block_records(entity, point) -> list[NoteRecord]:
    """读取 DIMENSION 几何块里的 TEXT/MTEXT，位置挂在尺寸文字中点上。"""

    found: list[NoteRecord] = []
    try:
        block_name = str(entity.dxf.get("geometry", "") or "")
    except Exception:
        block_name = ""
    if not block_name:
        return found
    try:
        block = entity.doc.blocks.get(block_name)
    except Exception:
        return found
    if block is None:
        return found
    for inner in block:
        kind = inner.dxftype()
        if kind not in ("TEXT", "MTEXT", "ATTRIB"):
            continue
        if kind == "MTEXT":
            raw = str(inner.text or "")
        else:
            raw = str(inner.dxf.get("text", "") or "")
        cleaned = plain_note(raw)
        # 块里同时有「%%c」这种直径符号碎片，属于尺寸线本身，跳过；
        # 只有带实质内容（数字/M/牙/深）的文字才算标注。
        if not cleaned or not re.search(r"\d|[Mm牙牙深]", cleaned):
            continue
        if cleaned in ("Ø", "Φ", "φ"):
            continue
        if re.fullmatch(r"[ØΦφ⌀∅<>±\s.\-]*", cleaned):
            continue
        found.append(
            NoteRecord(
                cleaned,
                None if point is None else point[0],
                None if point is None else point[1],
            )
        )
    return found


@dataclass(frozen=True)
class _NoteWithSpan(NoteRecord):
    span: tuple[float, float, float, float] | None = None

    def _axis_span(self, horizontal: bool) -> tuple[float, float] | None:
        if self.span is None:
            return None
        if horizontal:
            return self.span[0], self.span[1]
        return self.span[2], self.span[3]


def _dimension_span(record: NoteRecord, horizontal: bool) -> tuple[float, float] | None:
    method = getattr(record, "_axis_span", None)
    if callable(method):
        return method(horizontal)
    return None
