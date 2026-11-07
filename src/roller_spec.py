"""把图纸识别出的滚筒规格转成建模参数。

界面（单件 / 批量）与 SolidWorks 插件命令行都走这里，避免三处各写一套规则
导致「界面上能生成、插件生成得不一样」。
"""

from __future__ import annotations

import re
from pathlib import Path

from roller_drawing import RollerDrawingVariant
from solidworks_generator import DEFAULT_SHAFT_THREAD_DESIGNATION, RollerSpec

_UNSAFE_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class RollerSpecError(ValueError):
    """规格缺关键尺寸，无法建模。"""


def spec_from_variant(variant: RollerDrawingVariant) -> RollerSpec:
    """按图纸规格生成 RollerSpec；无动力件不带齿数与节距。"""

    if variant.overall_length_mm is None:
        raise RollerSpecError(f"{variant.roller_type}缺少总长，无法生成。")
    if variant.outer_diameter_mm is None:
        raise RollerSpecError(f"{variant.roller_type}缺少外径，无法生成。")

    powered = variant.is_powered
    return RollerSpec(
        roller_type=variant.roller_type,
        overall_length_mm=float(variant.overall_length_mm),
        outer_diameter_mm=float(variant.outer_diameter_mm),
        wall_thickness_mm=float(variant.wall_thickness_mm or 1.2),
        shaft_diameter_mm=float(variant.shaft_diameter_mm or 12.0),
        shaft_projection_mm=float(variant.shaft_projection_mm or 18.0),
        sprocket_teeth=variant.sprocket_teeth if powered else None,
        chain_pitch_mm=variant.chain_pitch_mm if powered else None,
        shaft_exposed_mm=variant.shaft_exposed_mm,
        shaft_thread_designation=(
            variant.shaft_thread_designation or DEFAULT_SHAFT_THREAD_DESIGNATION
        ),
        shaft_step_diameter_mm=(
            None if powered else variant.shaft_step_diameter_mm
        ),
    )


def variant_label(variant: RollerDrawingVariant) -> str:
    """列表里显示的一行摘要。"""

    length = (
        f"{variant.overall_length_mm:g}"
        if variant.overall_length_mm is not None
        else "待定"
    )
    diameter = (
        f"{variant.outer_diameter_mm:g}"
        if variant.outer_diameter_mm is not None
        else "待定"
    )
    shaft = (
        f"{variant.shaft_diameter_mm:g}"
        if variant.shaft_diameter_mm is not None
        else "待定"
    )
    return (
        f"{variant.roller_type}  Φ{diameter} × {length}"
        f"  轴 Φ{shaft}  ×{variant.quantity}"
    )


def variant_filename(
    variant: RollerDrawingVariant,
    stem: str,
    *,
    existing: set[Path] | None = None,
) -> str:
    """生成零件文件名；同名时自动加序号，绝不覆盖已有零件。"""

    length = (
        f"{variant.overall_length_mm:g}"
        if variant.overall_length_mm is not None
        else "待定"
    )
    diameter = (
        f"{variant.outer_diameter_mm:g}"
        if variant.outer_diameter_mm is not None
        else "待定"
    )
    # 文件名里不能出现 ? < > 等字符，未知尺寸统一写成「待定」。
    raw = f"{stem}_{variant.roller_type}_Φ{diameter}x{length}"
    base = _UNSAFE_FILENAME.sub("_", raw)
    candidate = Path(f"{base}.SLDPRT")
    taken = existing or set()
    counter = 2
    while candidate in taken or candidate.exists():
        candidate = Path(f"{base}_{counter}.SLDPRT")
        counter += 1
    return candidate.name
