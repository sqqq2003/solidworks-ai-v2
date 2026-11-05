"""Drive-side choice for the roller frame.

The baseline is the gear/sprocket side (齿轮侧). Choosing the other side is a
swap: the drive and both short-roller end fix plates move together. Baffles
are reserved so a later resize cannot ignore them. Feature names stay empty
until discovery; this module does not invent any.
"""

from __future__ import annotations

from dataclasses import dataclass

from roller_frame_math.errors import ConfigError

LEFT = "left"
RIGHT = "right"

# Logical parts. Not SolidWorks feature names.
GEAR_SIDE = "齿轮侧"
FIX_PLATE_GEAR_END = "齿轮侧短辊固定板"
FIX_PLATE_FREE_END = "另一端短辊固定板"
BAFFLE = "挡板"

RESERVED_ROLES: tuple[str, ...] = (
    "baffle",
    "short_roller_fix_gear_end",
    "short_roller_fix_free_end",
)

_ROLE_LABELS = {
    "baffle": BAFFLE,
    "short_roller_fix_gear_end": FIX_PLATE_GEAR_END,
    "short_roller_fix_free_end": FIX_PLATE_FREE_END,
}

_ALIASES = {
    "left": LEFT,
    "l": LEFT,
    "靠左": LEFT,
    "左": LEFT,
    "right": RIGHT,
    "r": RIGHT,
    "靠右": RIGHT,
    "右": RIGHT,
}


@dataclass(frozen=True)
class SidePlan:
    """``keep`` stays on 齿轮侧. ``swap`` moves the drive and both fix plates."""

    action: str
    requested: str | None
    mother_gear_side: str | None
    summary: str
    move_together: tuple[str, ...]
    reserved_roles: tuple[str, ...] = RESERVED_ROLES


def side_label(side: str | None) -> str:
    if side == LEFT:
        return "靠左"
    if side == RIGHT:
        return "靠右"
    return "未确认"


def parse_drive_side(value: object, *, key: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(
            f"{key} 必须是靠左/靠右（left/right）或空。空着表示保持齿轮侧。",
            stage="preflight",
            mate_class="configuration",
        )
    token = value.strip().casefold()
    # Chinese aliases are unchanged by casefold.
    parsed = _ALIASES.get(token) or _ALIASES.get(value.strip())
    if parsed is None:
        raise ConfigError(
            f"{key} 只能是 left、right、靠左、靠右，或空。收到 {value!r}。"
            "不填表示保持齿轮侧，不要猜左右。",
            stage="preflight",
            mate_class="configuration",
        )
    return parsed


def plan_drive_side(*, requested: str | None, mother_gear_side: str | None) -> SidePlan:
    """Decide whether this run keeps 齿轮侧 or swaps it to the other side."""

    requested = parse_drive_side(requested, key="drive_side")
    mother_gear_side = parse_drive_side(mother_gear_side, key="mother_drive_side")
    if requested is None:
        return SidePlan(
            action="keep",
            requested=None,
            mother_gear_side=mother_gear_side,
            summary="驱动侧: 保持齿轮侧，不换边。",
            move_together=(),
        )
    if mother_gear_side is None:
        raise ConfigError(
            f"请求把驱动放到{side_label(requested)}，但还不知道齿轮侧现在是靠左还是靠右。"
            "请在 config/frame.yaml 填写 mother_drive_side（left/right 或 靠左/靠右）。"
            "不能猜，所以已停止。",
            stage="preflight",
            mate_class="drive_side",
        )
    if requested == mother_gear_side:
        return SidePlan(
            action="keep",
            requested=requested,
            mother_gear_side=mother_gear_side,
            summary=f"驱动侧: {side_label(requested)}，与齿轮侧相同，不换边。",
            move_together=(),
        )
    return SidePlan(
        action="swap",
        requested=requested,
        mother_gear_side=mother_gear_side,
        summary=(
            f"驱动侧: 从齿轮侧（{side_label(mother_gear_side)}）换到{side_label(requested)}。"
            "两端短辊固定板必须和齿轮一起对调，挡板不能漏掉。"
        ),
        move_together=(GEAR_SIDE, FIX_PLATE_GEAR_END, FIX_PLATE_FREE_END),
    )


def enforce_side_plan(side: SidePlan, config: object, *, size_name: str) -> None:
    """Stop before a copy when a swap or a mapped reserved part cannot be applied."""

    mapped = tuple(role for role in RESERVED_ROLES if config.active_driver(role) is not None)
    if side.action == "swap":
        missing = tuple(_ROLE_LABELS[role] for role in RESERVED_ROLES if role not in mapped)
        detail = "、".join(side.move_together)
        missing_text = "、".join(missing) if missing else "无"
        raise ConfigError(
            f"{side.summary} 必须一起改的是：{detail}。"
            f"挡板也要纳入同一次改动。尚未映射的预留角色：{missing_text}。"
            "这些零件的特征名还没有从完整母体里读到，镜像步骤也还没有接到 SolidWorks。"
            "已停止，不会只换驱动侧或只改机架尺寸。",
            stage="side_swap",
            mate_class="drive_side",
            size_name=size_name,
        )
    if mapped:
        labels = "、".join(_ROLE_LABELS[role] for role in mapped)
        mate_class = _mapped_class(mapped)
        raise ConfigError(
            f"已经映射了 {labels}，但还没有对应的尺寸规则。"
            "不能在改 W/L/H 时跳过它们。请等规则接入后再改，或先把这些 name 留空。",
            stage="preflight",
            mate_class=mate_class,
            size_name=size_name,
        )


def _mapped_class(mapped: tuple[str, ...]) -> str:
    classes: list[str] = []
    if "baffle" in mapped:
        classes.append("baffles")
    if "short_roller_fix_gear_end" in mapped or "short_roller_fix_free_end" in mapped:
        classes.append("short_roller_fix_plates")
    return "+".join(classes) if classes else "drive_side"
