from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


_UNICODE_ESCAPE = re.compile(r"\\U\+([0-9A-Fa-f]{4})")
_WALL_THICKNESS = re.compile(r"(?:壁厚|臂厚)\s*([0-9]+(?:\.[0-9]+)?)\s*mm", re.I)
_SPROCKET_TEETH = re.compile(r"([0-9]+)\s*齿")
_CHAIN_FEN = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*分")
_QUANTITY = re.compile(r"[Xx×x]\s*([0-9]+)\s*支")
_SHAFT_THREAD = re.compile(r"(?:[0-9]+\s*-\s*)?M\s*([0-9]+)", re.I)
# SolidWorks 尺寸里螺纹号常被替换成 ``M<>``，真实数字在 DIMENSION 测量值里。
_SHAFT_THREAD_PLACEHOLDER = re.compile(
    r"(?:[0-9]+\s*-\s*)?M\s*(?:<>|ø|Ø|%%[cC])",
    re.I,
)
# 图名 / 注记里的「1.3米」「1300mm」「Φ50×280」一类总长。
_LENGTH_METERS = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*米")
_LENGTH_MM = re.compile(
    r"(?:总长|长度|L)\s*[=:]?\s*([0-9]+(?:\.[0-9]+)?)\s*mm",
    re.I,
)
_PHI_TIMES_LENGTH = re.compile(
    r"[ΦφØø∅]\s*([0-9]+(?:\.[0-9]+)?)\s*[xX×*]\s*([0-9]+(?:\.[0-9]+)?)",
)
# 简略草图常把正确数值写在尺寸覆盖文字里（如 ``700``、``%%C12``），
# 而 actual_measurement 仍是错误投影值（655、15）。
_DIM_OVERRIDE_VALUE = re.compile(
    r"^(?:%%[cC]|[ΦφØø∅])?\s*([0-9]+(?:[.,][0-9]+)?)\s*$",
)
_SHAFT_EXPOSED_NOTE = re.compile(
    r"(?:轴外漏|外露|外漏)\s*([0-9]+(?:\.[0-9]+)?)\s*mm",
    re.I,
)
# 「滚筒架 / 组织滚筒架 / 滚筒支架钣金」是钣金结构，不是滚筒零件尺寸图。
_ROLLER_FRAME_OR_SHEET = re.compile(
    r"(?:"
    r"滚筒\s*(?:线\s*)?(?:支\s*)?架|"
    r"组织\s*滚筒|"
    r"钣金|展开|焊板|落料|折弯图|"
    r"(?:固定|侧|底|盖|护|安装|连接|支承|支撑)\s*板|"
    r"机架|支架"
    r")"
)
_ROLLER_PART_CALLOUT = re.compile(
    r"(?:"
    r"动力\s*滚筒|无动力\s*滚筒|斜\s*滚|"
    r"臂厚|壁厚|链轮|"
    r"滚筒\s*尺寸|尺寸\s*图|"
    r"[Xx×x]\s*[0-9]+\s*支"
    r")"
)


@dataclass(frozen=True)
class RollerDrawingVariant:
    roller_type: str
    quantity: int
    overall_length_mm: float | None
    outer_diameter_mm: float | None
    wall_thickness_mm: float | None
    shaft_diameter_mm: float | None
    shaft_projection_mm: float | None
    shaft_exposed_mm: float | None
    sprocket_teeth: int | None
    chain_pitch_mm: float | None
    note: str
    inferred_fields: frozenset[str] = field(default_factory=frozenset)
    shaft_thread_designation: str | None = None
    # 无动力轴端中间台阶直径（图上若标了 Φ12/Φ15/Φ50 中的 15）。
    shaft_step_diameter_mm: float | None = None
    geometry_inferred: bool = False

    @property
    def is_powered(self) -> bool:
        return self.roller_type == "动力滚筒"

    @property
    def display_name(self) -> str:
        length = (
            f"{self.overall_length_mm:g} mm"
            if self.overall_length_mm is not None
            else "长度待确认"
        )
        return f"{self.roller_type} {length} × {self.quantity} 支"

    @property
    def sprocket_summary(self) -> str:
        if not self.is_powered:
            return "无"
        teeth = f"{self.sprocket_teeth} 齿" if self.sprocket_teeth else "齿数待确认"
        pitch = (
            f"{self.chain_pitch_mm:g} mm"
            if self.chain_pitch_mm is not None
            else "节距待确认"
        )
        return f"{teeth} / {pitch}"


@dataclass(frozen=True)
class _TextRecord:
    text: str
    x: float
    y: float


@dataclass(frozen=True)
class _DimensionRecord:
    text: str
    value: float
    x: float
    y: float
    # True when ``value`` comes from dimension override text (e.g. ``700``),
    # not the rough sketch measurement (e.g. 655).
    from_override: bool = False
    measured_value: float | None = None

    @property
    def is_diameter(self) -> bool:
        normalized = self.text.replace("Ø", "%%c").replace("Φ", "%%c")
        return "%%C" in normalized.upper()

    @property
    def is_thread(self) -> bool:
        # Hole callouts such as ``2-M<>-20深`` carry a numeric measurement
        # (usually the thread size), but they are not roller axial lengths.
        return "M" in self.text.upper()


# 滚筒总长候选下限：小于此值的是轴头伸出 / 外露等小尺寸。
_MIN_OVERALL_LENGTH_MM = 50.0
_PLAIN_LENGTH_TEXT = re.compile(
    r"^\s*([0-9]+(?:[.,][0-9]+)?)\s*$",
)


def decode_solidworks_text(text: str) -> str:
    r"""Decode the ``\U+XXXX`` escapes emitted by SolidWorks text entities."""

    if not text:
        return ""
    return _UNICODE_ESCAPE.sub(
        lambda match: chr(int(match.group(1), 16)),
        text,
    )


def _plain_text(entity: Any) -> str:
    plain = getattr(entity, "plain_text", None)
    if callable(plain):
        return str(plain())
    dxf = getattr(entity, "dxf", None)
    if dxf is None:
        return ""
    return str(getattr(dxf, "text", "") or "")


def _entity_text(entity: Any) -> str:
    kind = entity.dxftype()
    if kind == "MTEXT":
        return decode_solidworks_text(_plain_text(entity))
    if kind == "TEXT":
        dxf = entity.dxf
        return decode_solidworks_text(str(dxf.text or ""))
    if kind == "DIMENSION":
        dxf = entity.dxf
        return decode_solidworks_text(str(dxf.text or ""))
    return ""


def _insert_point(entity: Any) -> tuple[float, float] | None:
    dxf = getattr(entity, "dxf", None)
    if dxf is None:
        return None
    point = getattr(dxf, "insert", None)
    if point is None:
        return None
    return float(point.x), float(point.y)


def _dimension_point(entity: Any) -> tuple[float, float] | None:
    dxf = getattr(entity, "dxf", None)
    if dxf is None:
        return None
    point = getattr(dxf, "text_midpoint", None)
    if point is None:
        point = getattr(dxf, "defpoint", None)
    if point is None:
        return None
    return float(point.x), float(point.y)


def _override_dimension_value(text: str) -> float | None:
    """从图面数字解析数值（覆盖字 / *D 块标注）。"""

    if not text:
        return None
    decoded = decode_solidworks_text(text).strip()
    if not decoded or decoded in {"<>", "()", "(<>)"}:
        return None
    # 欧洲小数逗号：块里常见 ``18,5``。
    decoded = decoded.replace(",", ".")
    normalized = (
        decoded.replace("Ø", "%%c")
        .replace("Φ", "%%c")
        .replace("∅", "%%c")
        .replace("ø", "%%c")
    )
    match = _DIM_OVERRIDE_VALUE.match(normalized)
    if match is None:
        return None
    try:
        value = float(match.group(1).replace(",", "."))
    except ValueError:
        return None
    if not math.isfinite(value) or value <= 0:
        return None
    return value


def _measured_dimension_value(entity: Any) -> float | None:
    """尺寸几何测量值；图面数字优先，测量仅作兜底。"""

    measurement = getattr(entity, "get_measurement", None)
    if callable(measurement):
        try:
            value = float(measurement())
        except (TypeError, ValueError):
            return None
    else:
        dxf = getattr(entity, "dxf", None)
        raw = getattr(dxf, "actual_measurement", None) if dxf is not None else None
        if raw is None:
            return None
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return None
    if not math.isfinite(value) or value <= 0:
        return None
    return value


def _dimension_geometry_label(document: Any, entity: Any) -> str:
    """读取 DIMENSION 匿名块（``*D``）里画在图上的尺寸字。

    快改图纸时常只改这个数字、不改草图几何（图面 ``700``，测量仍 ``655``）。
    """

    if document is None:
        return ""
    dxf = getattr(entity, "dxf", None)
    if dxf is None:
        return ""
    geometry_name = getattr(dxf, "geometry", None) or dxf.get("geometry")
    if not geometry_name:
        return ""
    blocks = getattr(document, "blocks", None)
    if blocks is None:
        return ""
    try:
        block = blocks.get(str(geometry_name))
    except Exception:
        return ""
    if block is None:
        return ""
    labels: list[str] = []
    for child in block:
        kind = child.dxftype()
        if kind not in ("TEXT", "MTEXT", "ATTRIB", "ATTDEF"):
            continue
        label = _entity_text(child).strip()
        if not label and kind in ("ATTRIB", "ATTDEF"):
            child_dxf = getattr(child, "dxf", None)
            label = str(getattr(child_dxf, "text", "") or "").strip()
        if label:
            labels.append(decode_solidworks_text(label).strip())
    if not labels:
        return ""
    for label in labels:
        if _override_dimension_value(label) is not None:
            return label
    return labels[0]


def _dimension_value(entity: Any, document: Any = None) -> float | None:
    override = _override_dimension_value(_entity_text(entity))
    if override is not None:
        return override
    labeled = _override_dimension_value(_dimension_geometry_label(document, entity))
    measured = _measured_dimension_value(entity)
    # 图面数字优先：块字与测量不同时跟块字（700 vs 655）。
    if labeled is not None and (
        measured is None or abs(labeled - measured) > 0.05
    ):
        return labeled
    if measured is not None:
        return measured
    return labeled


def _dimension_record(
    entity: Any,
    *,
    scale: float,
    point: tuple[float, float],
    document: Any = None,
) -> _DimensionRecord | None:
    entity_text = _entity_text(entity)
    geometry_label = _dimension_geometry_label(document, entity)
    display_text = entity_text.strip() if entity_text.strip() else geometry_label
    measured = _measured_dimension_value(entity)
    override = _override_dimension_value(entity_text)
    if override is None:
        labeled = _override_dimension_value(geometry_label)
        # 块字与测量明显不同 → 图面设计数字（只改字不改几何）。
        # 块字只是回显测量时不抬成覆盖，便于附近文字等其它参考补救。
        if labeled is not None and (
            measured is None or abs(labeled - measured) > 0.05
        ):
            override = labeled
    if override is not None:
        value = override
        from_override = True
    elif measured is not None:
        value = measured
        from_override = False
    else:
        return None
    return _DimensionRecord(
        display_text,
        value * scale,
        point[0],
        point[1],
        from_override,
        None if measured is None else measured * scale,
    )


def _iter_drawable_entities(
    entities: Iterable[Any],
    *,
    _depth: int = 0,
) -> Iterable[Any]:
    """展开布局实体；块参照（INSERT）内的注记/尺寸也要参与识别。"""

    if _depth > 8:
        return
    for entity in entities:
        kind = entity.dxftype()
        if kind == "INSERT":
            virtual = getattr(entity, "virtual_entities", None)
            if callable(virtual):
                try:
                    yield from _iter_drawable_entities(
                        virtual(),
                        _depth=_depth + 1,
                    )
                    continue
                except Exception:
                    pass
        yield entity


def _iter_block_definition_entities(document: Any) -> Iterable[Any]:
    """简略草图有时只把滚筒注记放在块定义里，布局上仅有一层 INSERT。

    INSERT.virtual_entities 失败时，仍从含「滚筒」注记的块定义里收集。
    """

    blocks = getattr(document, "blocks", None)
    if blocks is None:
        return
    for block in blocks:
        name = str(getattr(block, "name", "") or "")
        if not name or name.startswith("*"):
            continue
        has_roller_note = False
        for entity in block:
            kind = entity.dxftype()
            if kind not in ("TEXT", "MTEXT", "ATTRIB", "ATTDEF"):
                continue
            text = _entity_text(entity)
            if "滚筒" in text or "斜滚" in text:
                has_roller_note = True
                break
        if not has_roller_note:
            continue
        yield from block


def _texts_and_dimensions(
    entities: Iterable[Any],
    scale: float,
    document: Any = None,
) -> tuple[tuple[_TextRecord, ...], tuple[_DimensionRecord, ...]]:
    """收集文字与尺寸。

    坐标保持图纸原始单位，便于按视图邻域分组；尺寸数值优先参考图面标注字，
    再回退到测量值，并换算到毫米。
    """

    texts: list[_TextRecord] = []
    dimensions: list[_DimensionRecord] = []
    for entity in _iter_drawable_entities(entities):
        kind = entity.dxftype()
        if kind in ("TEXT", "MTEXT", "ATTRIB", "ATTDEF"):
            point = _insert_point(entity)
            if point is None and kind in ("ATTRIB", "ATTDEF"):
                dxf = getattr(entity, "dxf", None)
                raw = getattr(dxf, "insert", None) if dxf is not None else None
                if raw is not None:
                    point = (float(raw.x), float(raw.y))
            text = _entity_text(entity).strip()
            if not text and kind in ("ATTRIB", "ATTDEF"):
                dxf = getattr(entity, "dxf", None)
                text = str(getattr(dxf, "text", "") or "").strip()
            if point is not None and text:
                texts.append(_TextRecord(decode_solidworks_text(text), point[0], point[1]))
            continue
        if kind != "DIMENSION":
            continue
        point = _dimension_point(entity)
        if point is None:
            continue
        record = _dimension_record(
            entity,
            scale=scale,
            point=point,
            document=document,
        )
        if record is not None:
            dimensions.append(record)
    return tuple(texts), tuple(dimensions)


def _plain_length_number(text: str) -> float | None:
    """孤立数字文字（如尺寸旁残留的 ``700``），用作覆盖字丢失时的回退。"""

    match = _PLAIN_LENGTH_TEXT.match(decode_solidworks_text(text or ""))
    if match is None:
        return None
    try:
        value = float(match.group(1).replace(",", "."))
    except ValueError:
        return None
    if not math.isfinite(value) or value < _MIN_OVERALL_LENGTH_MM:
        return None
    return value


def _is_overall_length_candidate(
    dimension: _DimensionRecord,
    *,
    diameter_values: Iterable[float],
) -> bool:
    if dimension.is_diameter or dimension.is_thread:
        return False
    if dimension.value < _MIN_OVERALL_LENGTH_MM:
        return False
    for diameter in diameter_values:
        if abs(dimension.value - diameter) < 0.05:
            return False
    return True


def _rescue_length_from_nearby_text(
    dimension: _DimensionRecord,
    texts: Iterable[_TextRecord],
    *,
    max_distance: float = 40.0,
) -> float | None:
    """SolidWorks 导出 DXF 时常丢掉覆盖字，只剩错误测量（655）；附近若有 ``700`` 则取回。"""

    if dimension.from_override:
        return None
    measured = (
        dimension.measured_value
        if dimension.measured_value is not None
        else dimension.value
    )
    best: tuple[float, float] | None = None
    for text in texts:
        number = _plain_length_number(text.text)
        if number is None:
            continue
        distance = math.hypot(text.x - dimension.x, text.y - dimension.y)
        if distance > max_distance:
            continue
        # 覆盖字通常是更「整齐」的设计值，且与草图测量接近但不相同。
        if abs(number - measured) < 0.05:
            continue
        if measured > 0 and abs(number - measured) / measured > 0.25:
            continue
        if best is None or distance < best[0]:
            best = (distance, number)
    return None if best is None else best[1]


def _resolve_length_value(
    dimension: _DimensionRecord,
    texts: Iterable[_TextRecord],
) -> float:
    rescued = _rescue_length_from_nearby_text(dimension, texts)
    if rescued is not None:
        return rescued
    return dimension.value


def _assign_overall_lengths(
    notes: list[_TextRecord],
    texts: tuple[_TextRecord, ...],
    dimensions: tuple[_DimensionRecord, ...],
) -> dict[int, float]:
    """每个注记独占最近的大长度尺寸，避免 700/280/330 串台。"""

    diameter_values = tuple(
        dimension.value for dimension in dimensions if dimension.is_diameter
    )
    candidates: list[tuple[int, _DimensionRecord, float]] = []
    for index, dimension in enumerate(dimensions):
        if not _is_overall_length_candidate(
            dimension, diameter_values=diameter_values
        ):
            continue
        value = _resolve_length_value(dimension, texts)
        candidates.append((index, dimension, value))

    assigned: dict[int, float] = {}
    used_dims: set[int] = set()
    for note_index, note in sorted(
        enumerate(notes),
        key=lambda item: -item[1].y,
    ):
        best: tuple[float, int, float] | None = None
        for dim_index, dimension, value in candidates:
            if dim_index in used_dims:
                continue
            dx = dimension.x - note.x
            dy = dimension.y - note.y
            # 尺寸多在注记上方；放宽窗口但仍按距离选最近。
            if not (-250.0 <= dx <= 1100.0 and -80.0 <= dy <= 480.0):
                continue
            distance = math.hypot(dx, dy)
            score = distance
            if dimension.from_override or abs(value - dimension.value) > 0.05:
                score -= 400.0
            if best is None or score < best[0]:
                best = (score, dim_index, value)
        if best is not None:
            used_dims.add(best[1])
            assigned[note_index] = best[2]
    return assigned


def _length_from_text(text: str) -> float | None:
    meter = _LENGTH_METERS.search(text)
    if meter is not None:
        return float(meter.group(1)) * 1000.0
    mm = _LENGTH_MM.search(text)
    if mm is not None:
        return float(mm.group(1))
    phi = _PHI_TIMES_LENGTH.search(text)
    if phi is not None:
        return float(phi.group(2))
    return None


def _is_roller_frame_or_sheet_context(text: str) -> bool:
    """图名/注记像滚筒架、支架钣金，而不是滚筒零件本身。"""

    if not text:
        return False
    return _ROLLER_FRAME_OR_SHEET.search(text) is not None


def _has_roller_part_callout(text: str) -> bool:
    """是否具备滚筒零件尺寸图特征（动力/无动力/臂厚/链轮/尺寸图等）。"""

    if not text:
        return False
    if _ROLLER_PART_CALLOUT.search(text) is not None:
        return True
    if _PHI_TIMES_LENGTH.search(text) is not None and "滚筒" in text:
        return True
    return False


def _parse_note(note: str) -> tuple[str | None, float | None, int | None, float | None]:
    """从图纸注记判断滚筒类型。斜滚筒线专用图常只写「斜滚筒」。"""

    # 滚筒架 / 钣金展开等：名字里有「滚筒」也不当滚筒零件。
    if _is_roller_frame_or_sheet_context(note) and not _has_roller_part_callout(note):
        return None, None, None, None

    if "无动力" in note:
        roller_type = "无动力滚筒"
    elif "斜滚" in note or "倾斜滚" in note:
        # 斜滚筒线多数为无动力托辊；若同条注记带链轮齿数再升为动力。
        roller_type = "无动力滚筒"
    elif "动力" in note and "滚筒" in note:
        roller_type = "动力滚筒"
    elif _WALL_THICKNESS.search(note) and "滚筒" in note:
        # 「201不锈钢滚筒-臂厚1.2mm」一类零件注记。
        roller_type = "无动力滚筒"
    else:
        # 仅有「滚筒」二字不够：组织滚筒架等钣金图也会出现该词。
        roller_type = None

    wall_match = _WALL_THICKNESS.search(note)
    wall = float(wall_match.group(1)) if wall_match else None

    teeth_match = _SPROCKET_TEETH.search(note)
    teeth = int(teeth_match.group(1)) if teeth_match else None

    pitch_match = _CHAIN_FEN.search(note)
    pitch = (
        float(pitch_match.group(1)) * 3.175
        if pitch_match is not None
        else None
    )
    if teeth is not None and roller_type == "无动力滚筒" and "无动力" not in note:
        # 「斜滚筒…14齿」仍按动力滚筒生成链轮。
        roller_type = "动力滚筒"
    return roller_type, wall, teeth, pitch


def _quantity_from_texts(
    texts: Iterable[_TextRecord],
) -> int | None:
    for text in texts:
        match = _QUANTITY.search(text.text)
        if match is not None:
            return max(1, int(match.group(1)))
    return None


def _thread_from_records(
    texts: Iterable[_TextRecord],
    dimensions: Iterable[_DimensionRecord],
) -> str | None:
    """从图纸 ``2-M8-20深`` / ``2-M<>-20深`` 一类标注提取轴端螺纹规格。"""

    for record in (*texts, *dimensions):
        match = _SHAFT_THREAD.search(record.text)
        if match is None:
            continue
        size = int(match.group(1))
        if size in (8, 10):
            return f"M{size}"

    for dimension in dimensions:
        if not _SHAFT_THREAD_PLACEHOLDER.search(dimension.text):
            continue
        size = int(round(dimension.value))
        if size in (8, 10):
            return f"M{size}"
    return None


def _group_in_window(
    note: _TextRecord,
    texts: Iterable[_TextRecord],
    dimensions: Iterable[_DimensionRecord],
    *,
    x_min: float,
    x_max: float,
    y_min: float,
    y_max: float,
) -> tuple[tuple[_TextRecord, ...], tuple[_DimensionRecord, ...]]:
    group_texts = tuple(
        item
        for item in texts
        if x_min <= item.x - note.x <= x_max and y_min <= item.y - note.y <= y_max
    )
    group_dimensions = tuple(
        item
        for item in dimensions
        if x_min <= item.x - note.x <= x_max and y_min <= item.y - note.y <= y_max
    )
    return group_texts, group_dimensions


def _nearest_group_values(
    note: _TextRecord,
    texts: Iterable[_TextRecord],
    dimensions: Iterable[_DimensionRecord],
) -> tuple[
    tuple[_TextRecord, ...],
    tuple[_DimensionRecord, ...],
]:
    # 先用常规邻域（尺寸多在注记上方）；为空再放宽，兼容斜滚筒线散落标注。
    group_texts, group_dimensions = _group_in_window(
        note,
        texts,
        dimensions,
        x_min=-100.0,
        x_max=900.0,
        y_min=-20.0,
        y_max=360.0,
    )
    if group_dimensions:
        return group_texts, group_dimensions
    return _group_in_window(
        note,
        texts,
        dimensions,
        x_min=-400.0,
        x_max=1200.0,
        y_min=-400.0,
        y_max=500.0,
    )


def _iter_insert_entities(entities: Iterable[Any]) -> Iterable[Any]:
    """布局上的块参照（不展开）。Drawing1 一类图把每个滚筒侧视放在独立 INSERT 里。"""

    for entity in entities:
        if entity.dxftype() == "INSERT":
            yield entity


def _entity_xy_points(entity: Any) -> list[tuple[float, float]]:
    kind = entity.dxftype()
    points: list[tuple[float, float]] = []
    try:
        if kind == "LINE":
            start = entity.dxf.start
            end = entity.dxf.end
            points.append((float(start.x), float(start.y)))
            points.append((float(end.x), float(end.y)))
        elif kind == "CIRCLE":
            center = entity.dxf.center
            radius = float(entity.dxf.radius)
            points.extend(
                (
                    (center.x - radius, center.y - radius),
                    (center.x + radius, center.y + radius),
                )
            )
        elif kind == "ARC":
            center = entity.dxf.center
            radius = float(entity.dxf.radius)
            points.extend(
                (
                    (center.x - radius, center.y - radius),
                    (center.x + radius, center.y + radius),
                )
            )
        elif kind == "LWPOLYLINE":
            points.extend(
                (float(point[0]), float(point[1])) for point in entity.get_points("xy")
            )
        elif kind == "SPLINE":
            control = getattr(entity, "control_points", None)
            if control is not None:
                points.extend((float(point[0]), float(point[1])) for point in control)
    except Exception:
        return []
    return points


def _vertical_segment_heights(entity: Any) -> list[tuple[float, float]]:
    """竖直短线 (x, height)，侧视图里常表示轴径 / 外径。"""

    if entity.dxftype() != "LINE":
        return []
    try:
        start = entity.dxf.start
        end = entity.dxf.end
    except Exception:
        return []
    x1, y1, x2, y2 = float(start.x), float(start.y), float(end.x), float(end.y)
    if abs(x2 - x1) > 1e-4:
        return []
    height = abs(y2 - y1)
    if height <= 1.0:
        return []
    return [(x1, height)]


def _infer_side_view_from_entities(
    entities: Iterable[Any],
    *,
    scale: float,
) -> dict[str, Any] | None:
    """从单个滚筒侧视块推断：总长、外径、轴径、是否动力。"""

    xs: list[float] = []
    ys: list[float] = []
    verticals: list[tuple[float, float]] = []
    spline_count = 0
    line_count = 0
    for entity in entities:
        kind = entity.dxftype()
        if kind == "SPLINE":
            spline_count += 1
        if kind == "LINE":
            line_count += 1
        for point in _entity_xy_points(entity):
            xs.append(point[0])
            ys.append(point[1])
        verticals.extend(_vertical_segment_heights(entity))
    if len(xs) < 4 or line_count < 8:
        return None
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    length = (max_x - min_x) * scale
    height = (max_y - min_y) * scale
    # 侧视总长一般 > 80；高度约为外径/链轮外径。
    if length < _MIN_OVERALL_LENGTH_MM or height < 8.0 or height > 200.0:
        return None
    if length / max(height, 1e-6) < 2.0:
        # 太“方”，更像端盖或其它零件，不是滚筒侧视。
        return None

    height_values = sorted(
        {
            round(height_mm * scale, 3)
            for _x, height_mm in verticals
            if 3.0 <= height_mm * scale <= max(height, 3.0) + 1.0
        }
    )
    outer_diameter = None
    shaft_diameter = None
    step_diameter = None
    if height_values:
        # 竖直高度里：最小常见轴径，最大常见筒径；中间为台阶。
        shaft_candidates = [value for value in height_values if value <= 30.0]
        barrel_candidates = [value for value in height_values if value >= 20.0]
        if shaft_candidates:
            shaft_diameter = min(shaft_candidates)
        if barrel_candidates:
            # 动力侧视 bbox 高度可能是链轮外径，筒身竖直段仍是 Φ50。
            preferred_barrel = [
                value
                for value in barrel_candidates
                if shaft_diameter is None or value >= shaft_diameter + 5.0
            ]
            if preferred_barrel:
                # 取众数倾向的筒径：优先接近 50 的值，否则取最大竖直段。
                round_fifties = [
                    value for value in preferred_barrel if abs(value - 50.0) <= 2.0
                ]
                outer_diameter = (
                    min(round_fifties, key=lambda value: abs(value - 50.0))
                    if round_fifties
                    else max(preferred_barrel)
                )
        if shaft_diameter is not None and outer_diameter is not None:
            middles = [
                value
                for value in height_values
                if shaft_diameter + 0.5 < value < outer_diameter - 0.5
            ]
            if middles:
                step_diameter = min(middles)

    if outer_diameter is None:
        # 无动力侧视高度≈外径；动力侧视高度≈链轮外径时仍可回退。
        outer_diameter = height if height <= 55.0 else 50.0
    if shaft_diameter is None:
        shaft_diameter = 12.0

    powered = spline_count >= 8 or (height >= outer_diameter + 8.0 and line_count >= 200)
    # 轴头伸出：最外端竖直轴径线到筒径竖直段的距离。
    shaft_projection = None
    if verticals:
        scaled_verticals = [
            (x * scale, height_mm * scale) for x, height_mm in verticals
        ]
        left_x = min(x for x, _h in scaled_verticals)
        right_x = max(x for x, _h in scaled_verticals)
        barrel_xs = sorted(
            x
            for x, height_mm in scaled_verticals
            if abs(height_mm - outer_diameter) <= 2.0
        )
        if barrel_xs:
            left_proj = barrel_xs[0] - (min_x * scale)
            right_proj = (max_x * scale) - barrel_xs[-1]
            positive = [value for value in (left_proj, right_proj) if 1.0 <= value <= 40.0]
            if positive:
                shaft_projection = min(positive)

    return {
        "length": round(length, 3),
        "outer_diameter": round(outer_diameter, 3),
        "shaft_diameter": round(shaft_diameter, 3),
        "step_diameter": (
            None if step_diameter is None else round(step_diameter, 3)
        ),
        "shaft_projection": (
            None if shaft_projection is None else round(shaft_projection, 3)
        ),
        "powered": powered,
        "center_y": ((min_y + max_y) / 2.0) * scale,
        "center_x": ((min_x + max_x) / 2.0) * scale,
        "spline_count": spline_count,
        "line_count": line_count,
    }


def extract_roller_variants_from_geometry(
    document: Any,
    entities: Iterable[Any],
    *,
    scale: float = 1.0,
) -> tuple[RollerDrawingVariant, ...]:
    """无「动力滚筒」文字时，从侧视块几何识别规格（如 Drawing1.dwg）。

    每个 INSERT 块若呈细长侧视，则读水平跨度=总长、竖直筒径段=外径、
    端头短竖线=轴径；含较多 SPLINE（齿形）判为动力滚筒。
    """

    if not math.isfinite(scale) or scale <= 0:
        raise ValueError("图纸单位换算比例必须是大于 0 的有限数值。")

    entity_list = list(entities)
    views: list[dict[str, Any]] = []

    # 1) 优先：每个 INSERT 当作一个侧视。
    for insert in _iter_insert_entities(entity_list):
        virtual = getattr(insert, "virtual_entities", None)
        children: list[Any] = []
        if callable(virtual):
            try:
                children = list(virtual())
            except Exception:
                children = []
        if not children and document is not None:
            name = str(getattr(insert.dxf, "name", "") or "")
            blocks = getattr(document, "blocks", None)
            if blocks is not None and name:
                try:
                    children = list(blocks.get(name))
                except Exception:
                    children = []
        inferred = _infer_side_view_from_entities(children, scale=scale)
        if inferred is not None:
            views.append(inferred)

    # 2) 若没有 INSERT，尝试把可绘制几何按 Y 分带（少见）。
    if not views:
        drawable = list(_iter_drawable_entities(entity_list))
        inferred = _infer_side_view_from_entities(drawable, scale=scale)
        if inferred is not None:
            views.append(inferred)

    if not views:
        return ()

    # 按 (类型, 总长) 去重；同位置重复 INSERT 只留一条。
    seen: set[tuple[object, ...]] = set()
    variants: list[RollerDrawingVariant] = []
    for view in sorted(views, key=lambda item: (-item["center_y"], item["length"])):
        roller_type = "动力滚筒" if view["powered"] else "无动力滚筒"
        length = float(view["length"])
        key = (roller_type, round(length, 1), round(view["outer_diameter"], 1))
        if key in seen:
            continue
        seen.add(key)
        inferred_fields = {"overall_length_mm", "outer_diameter_mm", "shaft_diameter_mm",
                           "shaft_projection_mm", "shaft_exposed_mm", "wall_thickness_mm",
                           "shaft_thread_designation"}
        projection = view["shaft_projection"]
        if projection is None:
            projection = 13.5 if view["powered"] else 5.0
            inferred_fields.add("shaft_projection_mm")
        exposed = min(5.0, projection)
        note = (
            f"侧视几何识别：{roller_type} "
            f"Φ{view['outer_diameter']:g}×{length:g}"
        )
        variants.append(
            RollerDrawingVariant(
                roller_type,
                1,
                length,
                float(view["outer_diameter"]),
                1.2,
                float(view["shaft_diameter"]),
                float(projection),
                exposed,
                14 if view["powered"] else None,
                12.7 if view["powered"] else None,
                note,
                frozenset(inferred_fields),
                "M10",
                (
                    float(view["step_diameter"])
                    if (not view["powered"] and view["step_diameter"] is not None)
                    else None
                ),
                geometry_inferred=True,
            )
        )
    return tuple(variants)


def extract_roller_variants(
    document: Any,
    entities: Iterable[Any],
    *,
    scale: float = 1.0,
) -> tuple[RollerDrawingVariant, ...]:
    """Extract roller variants from a SW_Model-like DXF layout.

    The parser deliberately follows the dimensions that surround a roller note
    instead of trying to reconstruct the roller body from every line. SolidWorks
    drawing views frequently keep the useful data in MTEXT and DIMENSION
    entities, while the body can be fragmented or hidden in blocks.

    若完全没有滚筒文字注记（例如 Drawing1.dwg 只有侧视块+尺寸），则回退到
    几何识别。
    """

    if not math.isfinite(scale) or scale <= 0:
        raise ValueError("图纸单位换算比例必须是大于 0 的有限数值。")

    entity_list = list(entities)
    texts, dimensions = _texts_and_dimensions(
        entity_list,
        scale,
        document=document,
    )
    note_records = [
        text
        for text in texts
        if ("滚筒" in text.text or "斜滚" in text.text)
        and "图框" not in text.text
        and len(text.text) >= 2
    ]
    # 简略草图：注记全在块定义里，布局 INSERT 展开失败时从块定义回退。
    if not note_records and document is not None:
        texts, dimensions = _texts_and_dimensions(
            _iter_block_definition_entities(document),
            scale,
            document=document,
        )
        note_records = [
            text
            for text in texts
            if ("滚筒" in text.text or "斜滚" in text.text)
            and "图框" not in text.text
            and len(text.text) >= 2
        ]
    if not note_records:
        return extract_roller_variants_from_geometry(
            document, entity_list, scale=scale
        )

    all_diameters = [
        dimension.value
        for dimension in dimensions
        if dimension.is_diameter and dimension.value > 0
    ]
    fallback_outer = max(all_diameters) if all_diameters else None
    fallback_shaft_candidates = [
        value
        for value in all_diameters
        if fallback_outer is None or value < fallback_outer
    ]
    fallback_shaft = min(fallback_shaft_candidates) if fallback_shaft_candidates else None
    global_linear = [
        dimension.value
        for dimension in dimensions
        if not dimension.is_diameter
        and not dimension.is_thread
        and dimension.value > 0
    ]
    global_small_linear = [value for value in global_linear if value <= 30.0]
    fallback_projection = max(global_small_linear) if global_small_linear else None
    fallback_exposed = (
        min(global_small_linear) if len(global_small_linear) > 1 else None
    )

    # 先筛出可解析注记，再独占分配大长度，避免动力 700/280 与无动力 330 串台。
    parsed_notes: list[tuple[_TextRecord, str, float | None, int | None, float | None]] = []
    for note in note_records:
        roller_type, wall, teeth, pitch = _parse_note(note.text)
        if roller_type is None:
            continue
        parsed_notes.append((note, roller_type, wall, teeth, pitch))
    length_by_note = _assign_overall_lengths(
        [item[0] for item in parsed_notes],
        texts,
        dimensions,
    )

    variants: list[RollerDrawingVariant] = []
    seen: set[tuple[object, ...]] = set()
    for note_index in sorted(
        range(len(parsed_notes)),
        key=lambda index: -parsed_notes[index][0].y,
    ):
        note, roller_type, wall, teeth, pitch = parsed_notes[note_index]
        group_texts, group_dimensions = _nearest_group_values(
            note,
            texts,
            dimensions,
        )
        # 斜滚筒专用图尺寸可能离注记很远：邻域为空时回退到全图尺寸。
        if not group_dimensions and dimensions:
            group_dimensions = dimensions
            group_texts = texts if not group_texts else group_texts

        diameter_values = [
            dimension.value
            for dimension in group_dimensions
            if dimension.is_diameter and dimension.value > 0
        ]
        # 直径标注常画在注记下方，邻域窗口可能裁掉；不足时用全图直径，保证每张图都能吃到。
        diameter_pool = (
            diameter_values
            if len(diameter_values) >= 2
            else list(all_diameters) or diameter_values
        )
        linear_values = [
            _resolve_length_value(dimension, group_texts)
            if dimension.value >= _MIN_OVERALL_LENGTH_MM
            else dimension.value
            for dimension in group_dimensions
            if not dimension.is_diameter
            and not dimension.is_thread
            and dimension.value > 0
        ]

        shaft_step_diameter: float | None = None
        if len(diameter_pool) >= 2:
            outer_diameter = max(diameter_pool)
            shaft_diameter = min(diameter_pool)
            # 任意图纸若标了中间直径（如 Φ12 / Φ15 / Φ50），台阶用该图自己的值。
            middles = sorted(
                {
                    value
                    for value in diameter_pool
                    if shaft_diameter + 0.05 < value < outer_diameter - 0.05
                }
            )
            if middles:
                shaft_step_diameter = middles[0]
        elif diameter_values:
            only_diameter = diameter_values[0]
            outer_reference = fallback_outer or only_diameter
            if only_diameter >= outer_reference * 0.75:
                outer_diameter = only_diameter
                shaft_diameter = fallback_shaft
            else:
                outer_diameter = fallback_outer
                shaft_diameter = only_diameter
        else:
            outer_diameter = fallback_outer
            shaft_diameter = fallback_shaft

        note_length = _length_from_text(note.text)
        overall_length = length_by_note.get(note_index)
        if overall_length is None:
            # 不再用全图 max(linear)——那会把别的视图的 700 派给 280/330。
            local_lengths = [
                value for value in linear_values if value >= _MIN_OVERALL_LENGTH_MM
            ]
            if local_lengths:
                overall_length = max(local_lengths)
            else:
                overall_length = note_length
        small_linear = sorted(
            value for value in linear_values if 0.0 < value <= 30.0
        )
        shaft_projection = max(small_linear) if small_linear else fallback_projection
        shaft_exposed = (
            min(small_linear) if len(small_linear) > 1 else fallback_exposed
        )
        for record in (*group_texts, note):
            exposed_match = _SHAFT_EXPOSED_NOTE.search(record.text)
            if exposed_match is not None:
                shaft_exposed = float(exposed_match.group(1))
                break

        inferred: set[str] = set()
        if not diameter_pool and outer_diameter is not None:
            inferred.add("outer_diameter_mm")
        if not diameter_pool and shaft_diameter is not None:
            inferred.add("shaft_diameter_mm")
        if len(diameter_pool) == 1 and outer_diameter == fallback_outer:
            inferred.add("outer_diameter_mm")
        if len(diameter_pool) == 1 and shaft_diameter == fallback_shaft:
            inferred.add("shaft_diameter_mm")
        # 一张滚筒图通常只标一个外径，其余件借用是正常行为；但本注记邻域里
        # 没读到外径、只能取整张图的共享直径时，如实标记，提示该值是借来的。
        if outer_diameter is not None and not any(
            abs(value - outer_diameter) <= 0.05 for value in diameter_values
        ):
            inferred.add("outer_diameter_mm")
        if wall is None:
            wall = 1.2
            inferred.add("wall_thickness_mm")
        if outer_diameter is None:
            outer_diameter = 50.0
            inferred.add("outer_diameter_mm")
        if shaft_diameter is None:
            shaft_diameter = 12.0
            inferred.add("shaft_diameter_mm")
        if overall_length is not None and note_length is not None and (
            note_index not in length_by_note
            and (
                not linear_values
                or max(linear_values) < _MIN_OVERALL_LENGTH_MM
            )
        ):
            inferred.add("overall_length_mm")
        if overall_length is None:
            # 注记能识别但尺寸缺失时仍给出条目，总长留空由对话框确认。
            inferred.add("overall_length_mm")
        if not small_linear and shaft_projection is not None:
            inferred.add("shaft_projection_mm")
        if not small_linear and shaft_exposed is not None:
            inferred.add("shaft_exposed_mm")

        shaft_thread = _thread_from_records(group_texts, group_dimensions)
        if shaft_thread is None:
            shaft_thread = _thread_from_records(texts, dimensions)
        if shaft_thread is None:
            # 完整参考件为 M10；图纸若写 M8 会在上文解析出来。
            shaft_thread = "M10"
            inferred.add("shaft_thread_designation")

        quantity = _quantity_from_texts(group_texts)
        if quantity is None:
            quantity = _quantity_from_texts(texts) or 1

        key = (
            roller_type,
            overall_length,
            round(outer_diameter, 6),
            round(shaft_diameter, 6),
            note.text,
        )
        if key in seen:
            continue
        seen.add(key)

        variants.append(
            RollerDrawingVariant(
                roller_type,
                quantity,
                overall_length,
                outer_diameter,
                wall,
                shaft_diameter,
                shaft_projection,
                shaft_exposed,
                teeth if roller_type == "动力滚筒" else None,
                pitch if roller_type == "动力滚筒" else None,
                note.text,
                frozenset(inferred),
                shaft_thread,
                shaft_step_diameter if roller_type == "无动力滚筒" else None,
            )
        )

    return tuple(variants)


def _filename_looks_like_roller_drawing(stem: str) -> bool:
    """文件名是否像滚筒零件尺寸图（而非滚筒架钣金）。"""

    if not stem:
        return False
    if _is_roller_frame_or_sheet_context(stem) and not _has_roller_part_callout(stem):
        return False
    if _has_roller_part_callout(stem):
        return True
    # 「1.3米…滚筒…」且无架/钣金字样时，仍允许图名回退。
    if _length_from_text(stem) is not None and (
        "滚筒" in stem or "斜滚" in stem or "roller" in stem.casefold()
    ):
        return not _is_roller_frame_or_sheet_context(stem)
    return False


def extract_roller_variants_from_filename(
    path_name: str,
) -> tuple[RollerDrawingVariant, ...]:
    """从图名回退识别，例如「1.3米斜滚筒线滚筒尺寸图（斜滚筒线专用）」。

    斜滚筒专用图导出后有时注记全在块里或转换丢失，至少保证能进滚筒流程。
    名称仅含「滚筒」但实为滚筒架/钣金时不回退。
    """

    stem = Path(path_name).stem if path_name else ""
    if not stem or not _filename_looks_like_roller_drawing(stem):
        return ()

    roller_type, wall, teeth, pitch = _parse_note(stem)
    if roller_type is None:
        # 图名像尺寸图但未写动力/无动力时，默认无动力托辊规格。
        if not _filename_looks_like_roller_drawing(stem):
            return ()
        roller_type = "无动力滚筒"

    overall_length = _length_from_text(stem)
    inferred: set[str] = {
        "outer_diameter_mm",
        "shaft_diameter_mm",
        "wall_thickness_mm",
        "shaft_thread_designation",
    }
    if overall_length is None:
        inferred.add("overall_length_mm")
    else:
        inferred.add("overall_length_mm")

    return (
        RollerDrawingVariant(
            roller_type,
            1,
            overall_length,
            50.0,
            wall if wall is not None else 1.2,
            12.0,
            13.5,
            5.0,
            teeth if roller_type == "动力滚筒" else None,
            pitch if roller_type == "动力滚筒" else None,
            stem,
            frozenset(inferred),
            "M10",
        ),
    )


def _variant_is_roller_part(variant: RollerDrawingVariant) -> bool:
    note = variant.note or ""
    if _is_roller_frame_or_sheet_context(note) and not _has_roller_part_callout(note):
        return False
    if _has_roller_part_callout(note):
        return True
    if variant.sprocket_teeth is not None or variant.chain_pitch_mm is not None:
        return True
    if variant.overall_length_mm is not None and (
        "滚筒" in note or "斜滚" in note or "roller" in note.casefold()
    ):
        return not _is_roller_frame_or_sheet_context(note)
    return False


def looks_like_roller_drawing(
    variants: tuple[RollerDrawingVariant, ...],
    *,
    bend_count: int = 0,
    path_name: str = "",
) -> bool:
    """判断图纸应优先按滚筒尺寸图处理，而不是钣金展开图。

    名字里有「滚筒」但属于滚筒架/组织架钣金时，仍走钣金流程。
    """

    # 图名写明是钣金/展开图时，整张图是「多件展开」而不是「一根滚筒」：
    # 图里顺带画的滚筒零件不该把整张图拽进滚筒流程。
    # 这里必须只看图名本身——「无动力滚筒」这类词既出现在滚筒零件图上，
    # 也出现在钣金图所属的产品名里，不能拿它当豁免的反证。
    if _is_roller_frame_or_sheet_context(path_name):
        return False

    strong = tuple(variant for variant in variants if _variant_is_roller_part(variant))
    if not strong:
        return False

    if bend_count > 0:
        # 有折弯线时更偏钣金；除非注记明确是滚筒零件（臂厚/链轮/动力等）。
        return any(
            _has_roller_part_callout(variant.note or "")
            or variant.sprocket_teeth is not None
            for variant in strong
        )

    return True
