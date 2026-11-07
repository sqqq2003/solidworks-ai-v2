"""从图纸文字里读取板厚 / 材质提示，省掉每次手填。

只认带明确关键词的写法（板厚 / 厚度 / 料厚 / t=2.5），避免把孔径、圆角之类
的数字误当成板厚——填错板厚比不填更危险。
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path

import ezdxf
from roller_drawing import decode_solidworks_text

# 「板厚 2.5」「厚度1.2mm」「料厚: 3」「材料厚度 1.5」
_THICKNESS_KEYWORD = re.compile(
    r"(?:板厚|厚度|料厚|材料厚度)\s*[:：=]?\s*(\d+(?:\.\d+)?)",
)
# 「碳钢板2.0mm」「不锈钢4mm」「铝板2.5」：材质名后面直接跟数字也是明确的板厚。
_MATERIAL_THICKNESS = re.compile(
    r"(?:碳钢|不锈钢|铝|黄铜|铜|铁|冷轧|热轧|SPCC|Q235)\s*板?\s*(\d+(?:\.\d+)?)\s*(?:mm|MM|毫米)?",
    re.IGNORECASE,
)
# 「t=2.5」「T2.5」「t 1.2」
_THICKNESS_LETTER = re.compile(r"(?<![A-Za-z])[tT]\s*[:：=]?\s*(\d+(?:\.\d+)?)(?![\d.])")
# 滚筒专用：臂厚 / 壁厚（筒身壁厚，不是钣金板厚，分开记）
_WALL_THICKNESS = re.compile(r"(?:臂厚|壁厚)\s*[:：=]?\s*(\d+(?:\.\d+)?)")

# 顺序有讲究：「不锈钢」必须排在「钢」前面。
# 牌号（201/304/316）不单独作为关键词——标题栏里的「201」是图号，不是材质。
_MATERIALS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("不锈钢", ("不锈钢", "SUS")),
    ("铝", ("铝合金", "铝板", "铝型材", "铝")),
    ("黄铜", ("黄铜", "铜板")),
    ("软钢/冷轧", ("冷轧", "冷板", "碳钢", "软钢", "SPCC", "Q235", "铁板")),
)


@dataclass(frozen=True)
class DrawingHints:
    """图纸文字里读到的可填参数。"""

    thickness_mm: float | None = None
    material: str | None = None
    thickness_source: str | None = None
    material_source: str | None = None
    wall_thickness_mm: float | None = None
    wall_thickness_source: str | None = None
    scanned_texts: int = 0
    notes: tuple[str, ...] = field(default_factory=tuple)


def _iter_texts(path: Path) -> list[str]:
    """收集图纸里所有可见文字（含块定义），顺序无关紧要。"""

    document = ezdxf.readfile(str(path))
    texts: list[str] = []
    seen_blocks: set[str] = set()

    def collect(container: object) -> None:
        for entity in container:  # type: ignore[union-attr]
            kind = entity.dxftype()
            if kind == "TEXT":
                texts.append(decode_solidworks_text(str(entity.dxf.text)))
            elif kind == "MTEXT":
                texts.append(decode_solidworks_text(str(entity.text)))
            elif kind == "INSERT":
                name = str(entity.dxf.name)
                if name in seen_blocks:
                    continue
                seen_blocks.add(name)
                try:
                    collect(document.blocks.get(name))
                except Exception:
                    continue

    collect(document.modelspace())
    for layout in document.layouts:
        if layout.name.lower() == "model":
            continue
        try:
            collect(layout)
        except Exception:
            continue
    return texts


def _strip_formatting(text: str) -> str:
    """MTEXT 里带 \\A1; \\P 之类的控制码，去掉再匹配。"""

    # 先处理堆叠分数 \S2.5^ ;：里面的数字是要保留的板厚。
    cleaned = re.sub(r"\\S([^;^]*)\^([^;]*);", r"\1 \2 ", text)
    # 再清掉其余控制码（\A1; \H0.7x; \P ...）。
    cleaned = re.sub(r"\\[A-Za-z][^;\\]*;?", " ", cleaned)
    return cleaned.replace("{", " ").replace("}", " ")


def hints_from_texts(texts: list[str]) -> DrawingHints:
    thickness: float | None = None
    thickness_source: str | None = None
    wall_thickness: float | None = None
    wall_thickness_source: str | None = None
    material: str | None = None
    material_source: str | None = None
    notes: list[str] = []

    for raw in texts:
        # 先解码 \U+XXXX（SolidWorks 导出），再清 MTEXT 控制码。
        text = _strip_formatting(decode_solidworks_text(raw)).strip()
        if not text:
            continue

        if thickness is None:
            match = _THICKNESS_KEYWORD.search(text)
            if match is None:
                match = _THICKNESS_LETTER.search(text)
            if match is not None:
                try:
                    value = float(match.group(1))
                except ValueError:
                    value = 0.0
                # 常见板材 0.3–12 mm；超出范围多半是把别的数字当成了板厚。
                if 0.3 <= value <= 12.0:
                    thickness = value
                    thickness_source = text
                else:
                    notes.append(f"文字「{text}」里的厚度 {value:g} 不像板材，已忽略。")

        if material is None:
            upper = text.upper()
            for name, keywords in _MATERIALS:
                if any(keyword.upper() in upper for keyword in keywords):
                    material = name
                    material_source = text
                    break

        if wall_thickness is None:
            match = _WALL_THICKNESS.search(text)
            if match is not None:
                try:
                    value = float(match.group(1))
                except ValueError:
                    value = 0.0
                if 0.3 <= value <= 12.0:
                    wall_thickness = value
                    wall_thickness_source = text

    return DrawingHints(
        thickness_mm=thickness,
        material=material,
        thickness_source=thickness_source,
        material_source=material_source,
        wall_thickness_mm=wall_thickness,
        wall_thickness_source=wall_thickness_source,
        scanned_texts=len(texts),
        notes=tuple(notes),
    )


# 「2mm」「2.0」「t=2」整段就是厚度。尺寸标注里的裸数字不能走这条。
_BARE_THICKNESS = re.compile(
    r"^\s*(?:[tT]\s*[:：=]?\s*)?(\d+(?:\.\d+)?)\s*(?:mm|MM|毫米)?\s*$"
)
# 「J1 X 2件」「J1×2件」「×2件」
_QUANTITY = re.compile(
    r"(?:(?P<tag>[A-Za-z]+\s*\d+)\s*)?[xX×*]\s*(?P<qty>\d+)\s*件"
)


@dataclass(frozen=True)
class PartAnnotation:
    """一块件从图纸文字读到的件数和分区厚度。"""

    quantity: int = 1
    quantity_source: str = ""
    thickness_mm: float | None = None
    thickness_source: str = ""


def parse_thickness_value(text: str, *, allow_bare: bool) -> tuple[float, str] | None:
    """从一段文字里读板厚。大字才允许裸数字 /「2mm」；「板厚」关键词不论字号。"""

    cleaned = _strip_formatting(decode_solidworks_text(text)).strip()
    if not cleaned:
        return None
    match = _THICKNESS_KEYWORD.search(cleaned)
    if match is None and allow_bare:
        match = _THICKNESS_LETTER.search(cleaned) or _BARE_THICKNESS.search(cleaned)
    if match is None:
        # 「碳钢板2.0mm」这种材质+数字写法，不论字号都明确是板厚。
        match = _MATERIAL_THICKNESS.search(cleaned)
    if match is None:
        return None
    try:
        value = float(match.group(1))
    except ValueError:
        return None
    if not 0.3 <= value <= 12.0:
        return None
    return value, cleaned


def parse_quantity_value(text: str) -> tuple[int, str] | None:
    cleaned = _strip_formatting(decode_solidworks_text(text)).strip()
    if not cleaned:
        return None
    match = _QUANTITY.search(cleaned)
    if match is None:
        return None
    quantity = int(match.group("qty"))
    if quantity <= 0:
        return None
    return quantity, cleaned


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[len(ordered) // 2]


def _is_large_text(height: float, heights: list[float]) -> bool:
    """图上「最上面大字」：明显高于正文尺寸字。

    正文用不超过最高字 60% 的那一档；同一行有多处大字时，不能让大字把中位数抬高。
    """

    if height <= 0:
        return False
    positive = sorted(item for item in heights if item > 0)
    if not positive:
        return height >= 5.0
    tallest = positive[-1]
    body_pool = [item for item in positive if item <= tallest * 0.6]
    if not body_pool:
        body_pool = positive[: max(1, (len(positive) + 1) // 2)]
    body = _median(body_pool)
    if height >= max(4.0, body * 1.6) and height >= tallest * 0.75:
        return True
    return height >= 6.0 and height >= tallest * 0.9


def reading_order(
    items: list[tuple[int, tuple[float, float, float, float]]],
) -> list[int]:
    """按位置从上到下、同一行从左到右。items 是 (编号, bounds)。"""

    if not items:
        return []
    heights = [bounds[3] - bounds[1] for _, bounds in items]
    gap = max(12.0, 0.45 * _median(heights))
    rows: list[list[tuple[int, tuple[float, float, float, float]]]] = []
    for item in sorted(items, key=lambda entry: -entry[1][3]):
        top = item[1][3]
        if not rows:
            rows.append([item])
            continue
        row_top = max(entry[1][3] for entry in rows[-1])
        if top < row_top - gap:
            rows.append([item])
        else:
            rows[-1].append(item)
    ordered: list[int] = []
    for row in rows:
        ordered.extend(entry[0] for entry in sorted(row, key=lambda entry: entry[1][0]))
    return ordered


def _row_bands(
    items: list[tuple[int, tuple[float, float, float, float]]],
) -> list[list[tuple[int, tuple[float, float, float, float]]]]:
    heights = [bounds[3] - bounds[1] for _, bounds in items] or [20.0]
    gap = max(12.0, 0.45 * _median(heights))
    rows: list[list[tuple[int, tuple[float, float, float, float]]]] = []
    for item in sorted(items, key=lambda entry: -entry[1][3]):
        top = item[1][3]
        if not rows:
            rows.append([item])
            continue
        row_top = max(entry[1][3] for entry in rows[-1])
        if top < row_top - gap:
            rows.append([item])
        else:
            rows[-1].append(item)
    return rows


def _row_box(
    row: list[tuple[int, tuple[float, float, float, float]]],
) -> tuple[float, float, float, float]:
    return (
        min(bounds[0] for _, bounds in row),
        min(bounds[1] for _, bounds in row),
        max(bounds[2] for _, bounds in row),
        max(bounds[3] for _, bounds in row),
    )


def _label_columns(
    labels: list[tuple[float, float, float, float, str]],
) -> list[tuple[int, float, float, float]]:
    """把横向排开的大字切成列条带，返回 [(labels 下标, left, right, 字高)]。

    只拿最大字高的那批字切列（图顶的「碳钢板2.0mm」这类），小字（件号、
    「反刀折90度」这类工艺备注）不参与——它们的 x 满图都是，会把列切碎。
    """

    if not labels:
        return []
    tallest = max(label[2] for label in labels)
    banners = [
        (position, label)
        for position, label in enumerate(labels)
        if label[2] >= tallest * 0.75
    ]
    if len(banners) < 2:
        return []
    banners.sort(key=lambda entry: entry[1][0])
    starts = [label[0] for _, label in banners]
    gaps = [b - a for a, b in zip(starts, starts[1:])]
    if not gaps:
        return []
    typical = _median(gaps)
    if typical <= 0:
        return []
    columns: list[tuple[int, float, float, float]] = []
    for position, (label_index, label) in enumerate(banners):
        left = label[0] - typical / 2.0
        if position > 0:
            left = max(left, (banners[position - 1][1][0] + label[0]) / 2.0)
        right = label[0] + typical / 2.0
        if position < len(banners) - 1:
            right = min(right, (label[0] + banners[position + 1][1][0]) / 2.0)
        columns.append((label_index, left, right, label[2]))
    return columns


def _part_stacked_below(
    x: float,
    y: float,
    height: float,
    items: list[tuple[int, tuple[float, float, float, float]]],
) -> bool:
    """大字正下方（同一列、明显低于它）是否已经压着零件。"""

    for _, bounds in items:
        top = bounds[3]
        if top > y:
            continue
        center = (bounds[0] + bounds[2]) / 2.0
        width = bounds[2] - bounds[0]
        if abs(center - x) <= max(width * 0.5, height):
            return True
    return False


def _column_rank(
    label_index: int,
    center_x: float,
    part_top: float,
    column: int | None,
    columns: list[tuple[int, float, float, float]],
) -> tuple[float, float] | None:
    """大字挂到零件的优先级；None 表示不挂。

    第 0 档：零件落在该大字的列条带里（整列共用，纵向不限）。
    第 1 档：不是列大字，且这颗字就在本行头顶上（同列顶部没有压着别的行）。
    第 2 档：都不是时，退回「同列里横向最近的那颗字」，且必须在本行上方。
    """

    if column is not None and columns[column][0] == label_index:
        return (0.0, abs(columns[column][1] + columns[column][2]) / 2.0)
    return None


def annotate_sheet_parts(
    items: list[tuple[int, tuple[float, float, float, float]]],
    texts: list[object],
) -> dict[int, PartAnnotation]:
    """把图纸顶部「分区大字」的板厚挂到该分区内的每块件上，件数取附近的「J1 X 2件」。

    ``texts`` 需要有 text / x / y / height。找不到厚度时 thickness_mm 为 None，
    由导出时改用界面默认并写日志。
    """

    heights = [float(getattr(text, "height", 0) or 0) for text in texts]
    labels: list[tuple[float, float, float, float, str]] = []
    for text, height in zip(texts, heights):
        raw = str(getattr(text, "text", "") or "")
        parsed = parse_thickness_value(raw, allow_bare=_is_large_text(height, heights))
        if parsed is None:
            parsed = parse_thickness_value(raw, allow_bare=False)
        if parsed is None:
            continue
        # 裸数字必须是大字；关键词/材质名写法已经足够明确。
        keyword = _THICKNESS_KEYWORD.search(
            _strip_formatting(decode_solidworks_text(raw))
        )
        material = _MATERIAL_THICKNESS.search(
            _strip_formatting(decode_solidworks_text(raw))
        )
        if keyword is None and material is None and not _is_large_text(height, heights):
            continue
        value, source = parsed
        labels.append(
            (
                float(getattr(text, "x", 0) or 0),
                float(getattr(text, "y", 0) or 0),
                height,
                value,
                source,
            )
        )

    thickness_by_index: dict[int, tuple[float, str]] = {}
    if not labels:
        return _quantity_only(items, texts)

    # 大字横排在图纸顶端（同一高度带）才算分区大字，各自管一整列；
    # 散落在各处的「2mm」「1.5mm」是逐行标注，按行就近挂。
    top_y = max(label[1] for label in labels)
    tallest = max(label[2] for label in labels)
    banners = [
        (position, label)
        for position, label in enumerate(labels)
        if label[2] >= tallest * 0.75 and label[1] >= top_y - max(label[2], 1.0)
    ]
    columns = _label_columns([label for _, label in banners]) if len(banners) >= 2 else []
    # 列条带里的下标换回 labels 的下标。
    columns = [
        (banners[column[0]][0], column[1], column[2], column[3]) for column in columns
    ]
    band_of = {column[0]: position for position, column in enumerate(columns)}

    def band_for(center_x: float) -> int | None:
        for position, column in enumerate(columns):
            if column[1] <= center_x <= column[2]:
                return position
        return None

    # 第一轮：切了列就按列整列共用；没切列就按行取头顶最近的大字。
    claimed: set[int] = set()
    for index, bounds in items:
        center_x = (bounds[0] + bounds[2]) / 2.0
        top = bounds[3]
        band = band_for(center_x)
        best: tuple[float, str] | None = None
        best_rank: tuple[float, float] | None = None
        for position, (x, y, height, value, source) in enumerate(labels):
            if band is not None:
                if band_of.get(position) != band:
                    continue
                rank = (0.0, abs(x - center_x))
            else:
                if y + max(height, 0.0) < top - max(2.0, height * 0.25):
                    continue
                if y - top < -max(height, 2.0):
                    continue
                rank = (max(0.0, y - top) / max(height, 1.0), abs(x - center_x))
            if best_rank is None or rank < best_rank:
                best_rank = rank
                best = (value, source)
                best_position = position
        if best is not None:
            thickness_by_index[index] = best
            claimed.add(best_position)

    # 第二轮：没切出列、又没抢到字的零件（下方那些行），按行自上而下补，
    # 让每颗小字只能被一行认领，避免一整列串成同一个厚度。
    if not columns:
        used: set[int] = set(claimed)
        rows = _row_bands(items)
        for row in rows:
            row_top = _row_box(row)[3]
            for index, bounds in row:
                if index in thickness_by_index:
                    continue
                center_x = (bounds[0] + bounds[2]) / 2.0
                best_rank = None
                best = None
                best_position = None
                for position, (x, y, height, value, source) in enumerate(labels):
                    if position in used:
                        continue
                    if y + max(height, 0.0) < row_top - max(2.0, height * 0.25):
                        continue
                    if y - row_top < -max(height, 2.0):
                        continue
                    rank = (max(0.0, y - row_top) / max(height, 1.0), abs(x - center_x))
                    if best_rank is None or rank < best_rank:
                        best_rank = rank
                        best = (value, source)
                        best_position = position
                if best is None:
                    continue
                thickness_by_index[index] = best
                used.add(best_position)

    return _quantity_only(items, texts, thickness_by_index)


def _quantity_only(
    items: list[tuple[int, tuple[float, float, float, float]]],
    texts: list[object],
    thickness_by_index: dict[int, tuple[float, str]] | None = None,
) -> dict[int, PartAnnotation]:
    """件数取零件附近最近的「J1 X 2件」，厚度取上面算好的那张表。"""

    thickness_by_index = thickness_by_index or {}
    annotations: dict[int, PartAnnotation] = {}
    for index, bounds in items:
        quantity = 1
        quantity_source = ""
        best_distance = None
        min_x, min_y, max_x, max_y = bounds
        margin_x = max(25.0, (max_x - min_x) * 0.35)
        margin_y = max(25.0, (max_y - min_y) * 0.5)
        center = ((min_x + max_x) / 2.0, (min_y + max_y) / 2.0)
        for text in texts:
            parsed_qty = parse_quantity_value(str(getattr(text, "text", "") or ""))
            if parsed_qty is None:
                continue
            x = float(getattr(text, "x", 0) or 0)
            y = float(getattr(text, "y", 0) or 0)
            height = float(getattr(text, "height", 0) or 0)
            if not (
                min_x - margin_x <= x <= max_x + margin_x
                and min_y - margin_y <= y <= max_y + margin_y + height
            ):
                continue
            distance = math.hypot(x - center[0], y - center[1])
            if best_distance is None or distance < best_distance:
                best_distance = distance
                quantity, quantity_source = parsed_qty
        thickness = thickness_by_index.get(index)
        annotations[index] = PartAnnotation(
            quantity=quantity,
            quantity_source=quantity_source,
            thickness_mm=None if thickness is None else thickness[0],
            thickness_source="" if thickness is None else thickness[1],
        )
    return annotations


def read_drawing_hints(path: str | Path) -> DrawingHints:
    """读取 DXF 文字提示；DWG 或读不了的文件返回空提示（不抛异常）。"""

    source = Path(path)
    if source.suffix.casefold() != ".dxf":
        return DrawingHints()
    try:
        texts = _iter_texts(source)
    except Exception:
        return DrawingHints()
    return hints_from_texts(texts)
