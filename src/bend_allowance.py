from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal


# SolidWorks swBendAllowanceTypes_e
SW_BEND_ALLOWANCE_BEND_TABLE = 1
SW_BEND_ALLOWANCE_K_FACTOR = 2
SW_BEND_ALLOWANCE_DIRECT = 3
SW_BEND_ALLOWANCE_DEDUCTION = 4

BendMode = Literal["k_factor", "bend_deduction", "bend_allowance"]

# 常用材料默认 K 因子（中性层相对板厚的位置，0~1）。
MATERIAL_K_FACTORS: dict[str, float] = {
    "软钢/冷轧": 0.44,
    "不锈钢": 0.40,
    "铝": 0.33,
    "黄铜": 0.35,
    "自定义": 0.44,
}


@dataclass(frozen=True)
class BendAllowanceResult:
    """一次折弯的补偿 / 扣除结果（单位 mm，角度为折弯角）。"""

    thickness_mm: float
    radius_mm: float
    angle_degrees: float
    k_factor: float
    bend_allowance_mm: float
    bend_deduction_mm: float
    outside_setback_mm: float
    # 90° 时常说的「扣除倍数」≈ BD / T
    deduction_factor: float

    @property
    def angle_radians(self) -> float:
        return math.radians(self.angle_degrees)


@dataclass(frozen=True)
class BendAllowanceSpec:
    """写入 SolidWorks CustomBendAllowance 的规格。"""

    mode: BendMode
    k_factor: float = 0.44
    bend_deduction_mm: float | None = None
    bend_allowance_mm: float | None = None
    material_name: str = "软钢/冷轧"

    @property
    def sw_type(self) -> int:
        if self.mode == "k_factor":
            return SW_BEND_ALLOWANCE_K_FACTOR
        if self.mode == "bend_deduction":
            return SW_BEND_ALLOWANCE_DEDUCTION
        return SW_BEND_ALLOWANCE_DIRECT


def _validate_inputs(
    thickness_mm: float,
    radius_mm: float,
    angle_degrees: float,
    k_factor: float,
) -> None:
    if not math.isfinite(thickness_mm) or thickness_mm <= 0:
        raise ValueError("板厚必须大于 0。")
    if not math.isfinite(radius_mm) or radius_mm < 0:
        raise ValueError("折弯内半径不能为负。")
    if not math.isfinite(angle_degrees) or not 0 < angle_degrees < 180:
        raise ValueError("折弯角度必须在 0°~180° 之间（不含端点）。")
    if not math.isfinite(k_factor) or not 0.0 <= k_factor <= 1.0:
        raise ValueError("K 因子必须在 0~1 之间。")


def bend_allowance_mm(
    thickness_mm: float,
    radius_mm: float,
    angle_degrees: float,
    k_factor: float,
) -> float:
    """折弯补偿 BA = θ(R + K·T)，θ 为弧度。

    展开料长（两外缘直角边量到尖角）常用：L = Leg1 + Leg2 − BD，
    其中 BD 由 ``bend_deduction_mm`` 给出；等价于在折弯区用 BA 代替两段尖角直线。
    """

    _validate_inputs(thickness_mm, radius_mm, angle_degrees, k_factor)
    return math.radians(angle_degrees) * (radius_mm + k_factor * thickness_mm)


def outside_setback_mm(
    thickness_mm: float,
    radius_mm: float,
    angle_degrees: float,
) -> float:
    """外侧回退 OSSB = (R + T)·tan(θ/2)。"""

    _validate_inputs(thickness_mm, radius_mm, angle_degrees, 0.5)
    half = math.radians(angle_degrees) / 2.0
    return (radius_mm + thickness_mm) * math.tan(half)


def bend_deduction_mm(
    thickness_mm: float,
    radius_mm: float,
    angle_degrees: float,
    k_factor: float,
) -> float:
    """折弯扣除 BD = 2·OSSB − BA。

    展开长：``flat = leg1 + leg2 - BD``（leg 量到模具尖角 / 外模线交点）。
    """

    ba = bend_allowance_mm(thickness_mm, radius_mm, angle_degrees, k_factor)
    ossb = outside_setback_mm(thickness_mm, radius_mm, angle_degrees)
    return 2.0 * ossb - ba


def compute_bend_allowance(
    thickness_mm: float,
    radius_mm: float,
    angle_degrees: float,
    k_factor: float,
) -> BendAllowanceResult:
    """由板厚、内半径、折弯角、K 因子算出 BA / BD / OSSB。"""

    _validate_inputs(thickness_mm, radius_mm, angle_degrees, k_factor)
    ba = bend_allowance_mm(thickness_mm, radius_mm, angle_degrees, k_factor)
    ossb = outside_setback_mm(thickness_mm, radius_mm, angle_degrees)
    bd = 2.0 * ossb - ba
    factor = bd / thickness_mm if thickness_mm > 1e-12 else 0.0
    return BendAllowanceResult(
        thickness_mm=thickness_mm,
        radius_mm=radius_mm,
        angle_degrees=angle_degrees,
        k_factor=k_factor,
        bend_allowance_mm=ba,
        bend_deduction_mm=bd,
        outside_setback_mm=ossb,
        deduction_factor=factor,
    )


def k_factor_from_bend_deduction(
    thickness_mm: float,
    radius_mm: float,
    angle_degrees: float,
    bend_deduction: float,
) -> float:
    """由已知折弯扣除反推 K 因子（车间扣数表 → K）。"""

    _validate_inputs(thickness_mm, radius_mm, angle_degrees, 0.5)
    if not math.isfinite(bend_deduction):
        raise ValueError("折弯扣除必须是有限数值。")
    theta = math.radians(angle_degrees)
    if abs(theta) <= 1e-12:
        raise ValueError("折弯角度过小，无法反推 K 因子。")
    ossb = outside_setback_mm(thickness_mm, radius_mm, angle_degrees)
    # BD = 2·OSSB − θ(R + K·T)  ⇒  K = ((2·OSSB − BD)/θ − R) / T
    ba = 2.0 * ossb - bend_deduction
    k_factor = (ba / theta - radius_mm) / thickness_mm
    if not math.isfinite(k_factor):
        raise ValueError("无法由该折弯扣除反推 K 因子。")
    return k_factor


def flat_length_mm(leg1_mm: float, leg2_mm: float, deduction_mm: float) -> float:
    """两直角边（量到尖角）的展开长：L = Leg1 + Leg2 − BD。"""

    if not math.isfinite(leg1_mm) or leg1_mm < 0:
        raise ValueError("边长 1 无效。")
    if not math.isfinite(leg2_mm) or leg2_mm < 0:
        raise ValueError("边长 2 无效。")
    if not math.isfinite(deduction_mm):
        raise ValueError("折弯扣除无效。")
    return leg1_mm + leg2_mm - deduction_mm


def resolve_bend_allowance_spec(
    *,
    thickness_mm: float,
    radius_mm: float,
    angle_degrees: float,
    mode: BendMode,
    k_factor: float,
    bend_deduction_mm: float | None = None,
    bend_allowance_mm_value: float | None = None,
    material_name: str = "软钢/冷轧",
) -> tuple[BendAllowanceSpec, BendAllowanceResult]:
    """根据界面模式得到写入 SolidWorks 的规格，以及完整计算结果（便于预览）。"""

    computed = compute_bend_allowance(
        thickness_mm, radius_mm, angle_degrees, k_factor
    )
    if mode == "k_factor":
        spec = BendAllowanceSpec(
            mode="k_factor",
            k_factor=k_factor,
            bend_deduction_mm=computed.bend_deduction_mm,
            bend_allowance_mm=computed.bend_allowance_mm,
            material_name=material_name,
        )
        return spec, computed

    if mode == "bend_deduction":
        deduction = (
            computed.bend_deduction_mm
            if bend_deduction_mm is None
            else float(bend_deduction_mm)
        )
        if not math.isfinite(deduction):
            raise ValueError("折弯扣除必须是有限数值。")
        # 用用户扣数反推等效 K，刷新预览数字。
        try:
            derived_k = k_factor_from_bend_deduction(
                thickness_mm, radius_mm, angle_degrees, deduction
            )
        except ValueError:
            derived_k = k_factor
        preview = BendAllowanceResult(
            thickness_mm=thickness_mm,
            radius_mm=radius_mm,
            angle_degrees=angle_degrees,
            k_factor=derived_k,
            bend_allowance_mm=2.0
            * outside_setback_mm(thickness_mm, radius_mm, angle_degrees)
            - deduction,
            bend_deduction_mm=deduction,
            outside_setback_mm=outside_setback_mm(
                thickness_mm, radius_mm, angle_degrees
            ),
            deduction_factor=deduction / thickness_mm if thickness_mm else 0.0,
        )
        spec = BendAllowanceSpec(
            mode="bend_deduction",
            k_factor=derived_k,
            bend_deduction_mm=deduction,
            bend_allowance_mm=preview.bend_allowance_mm,
            material_name=material_name,
        )
        return spec, preview

    allowance = (
        computed.bend_allowance_mm
        if bend_allowance_mm_value is None
        else float(bend_allowance_mm_value)
    )
    if not math.isfinite(allowance) or allowance < 0:
        raise ValueError("折弯补偿必须是非负有限数值。")
    ossb = outside_setback_mm(thickness_mm, radius_mm, angle_degrees)
    deduction = 2.0 * ossb - allowance
    preview = BendAllowanceResult(
        thickness_mm=thickness_mm,
        radius_mm=radius_mm,
        angle_degrees=angle_degrees,
        k_factor=k_factor,
        bend_allowance_mm=allowance,
        bend_deduction_mm=deduction,
        outside_setback_mm=ossb,
        deduction_factor=deduction / thickness_mm if thickness_mm else 0.0,
    )
    spec = BendAllowanceSpec(
        mode="bend_allowance",
        k_factor=k_factor,
        bend_deduction_mm=deduction,
        bend_allowance_mm=allowance,
        material_name=material_name,
    )
    return spec, preview


def format_bend_summary(result: BendAllowanceResult) -> str:
    """界面上一行摘要。"""

    return (
        f"BD {result.bend_deduction_mm:.2f} mm（{result.deduction_factor:.2f}×t）"
        f"  BA {result.bend_allowance_mm:.2f}  K {result.k_factor:.2f}"
    )
