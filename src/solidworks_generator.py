from __future__ import annotations

import logging
import math
import os
import tempfile
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterable, Callable

from bend_allowance import BendAllowanceSpec
from cad_analyzer import (
    DrawingAnalysis,
    Primitive,
    SketchSegment,
    primitive_bounds,
)
from profile_sanitize import (
    profile_span_mm,
    refit_circular_fillets,
    reverse_closed_profile,
    sanitize_closed_profile,
)
from profile_selection import (
    contained_hole_indices,
    outermost_containing_profile_index,
)
from sw_session import (
    SW_SESSION_CALL_TIMEOUT_SEC,
    SessionOwnershipError,
    SwCallTimeoutError,
    call_with_watchdog,
    connect_application,
    current_lease,
    on_task_sta,
    release_task_documents,
    require_model_write,
    ensure_application_keepalive,
    run_on_task_sta,
)


SOLIDWORKS_TYPELIB_ID = "{83A33D31-27C5-11CE-BFD4-00400513BB57}"
# 33 对应 SW2025。以前这个数是写死的，换一台装了别的版本 SolidWorks 的机器，
# EnsureModule 就会失败、整个生成功能直接不可用。现在只在探测不到时当兜底。
SOLIDWORKS_TYPELIB_MAJOR = 33
# 装了多个版本时按新到旧试；探测不到已装版本就按这张表回退。
_TRY_TYPELIB_MAJORS = (33, 32, 31, 30, 29, 28, 27, 26, 25, 24, 23)
_TYPELIB_MAJOR_CACHE: int | None = None
SW_DEFAULT_TEMPLATE_PART = 8
SW_BODY_TYPE_SOLID = 0
# swDocumentTypes_e：零件=1，装配=2，工程图=3。
SW_DOCUMENT_TYPE_PART = 1
# swOpenDocOptions_e：静默打开，不弹对话框。
SW_OPEN_DOC_SILENT = 1
# SolidWorks swEndConditions_e：Blind=0, ThroughAll=1, MidPlane=6。
SW_END_CONDITION_BLIND = 0
SW_END_CONDITION_THROUGH_ALL = 1
SW_END_CONDITION_MID_PLANE = 6
# InsertSheetMetal3dBend / 草图折弯 PositionType（与属性栏图标顺序一致，同 jog）：
# 折弯中心线=1，材料在内=2，材料在外=3，折弯在外=4。
# 注意：不要用边法兰 swFlangePositionTypeBendCenterLine=4，否则会变成「折弯在外」导致 API 折弯失败。
SW_BEND_POSITION_BEND_CENTERLINE = 1
SW_BEND_POSITION_MATERIAL_INSIDE = 2
SW_BEND_POSITION_MATERIAL_OUTSIDE = 3
SW_BEND_POSITION_BEND_OUTSIDE = 4
# 默认按软钢 K=0.44 算折弯扣除；界面可改成直接写扣除/补偿。
DEFAULT_BEND_K_FACTOR = 0.44
SW_ARC_DIRECTION_CLOCKWISE = -1
SW_ARC_DIRECTION_COUNTERCLOCKWISE = 1
SW_START_CONDITION_SKETCH_PLANE = 0
SW_START_CONDITION_OFFSET = 3
DEFAULT_CHAIN_PITCH_MM = 12.7
# 4 分（12.7 mm）链常用 08B 滚子，滚子直径约为节距的 0.67 倍。
CHAIN_ROLLER_DIAMETER_RATIO = 0.67


def _com_read(instance: Any, name: str) -> Any:
    """pywin32 may expose parameterless COM members as properties or methods."""
    value = getattr(instance, name)
    return value() if callable(value) else value


def _installed_typelib_majors() -> tuple[int, ...]:
    """从注册表读出本机已注册的 SolidWorks 类型库主版本号。

    SolidWorks 的类型库 GUID 是跨版本稳定的，变的是 HKCR\\TypeLib\\{GUID} 下的
    版本子键（形如 "33.0"）。装了几个版本这里就有几个子键。
    """

    try:
        import winreg
    except ImportError:  # 非 Windows 上根本连不了 SolidWorks
        return ()
    try:
        with winreg.OpenKey(
            winreg.HKEY_CLASSES_ROOT,
            f"TypeLib\\{SOLIDWORKS_TYPELIB_ID}",
        ) as key:
            count = winreg.QueryInfoKey(key)[0]
            names = [winreg.EnumKey(key, index) for index in range(count)]
    except OSError:
        return ()
    majors: list[int] = []
    for name in names:
        head = name.split(".", 1)[0]
        if head.isdigit():
            majors.append(int(head))
    return tuple(sorted(set(majors), reverse=True))


def typelib_major() -> int:
    """挑一个本机真能加载的类型库主版本号，结果缓存下来。

    顺序：注册表里已装的（新→旧）→ 兜底表里逐个试（新→旧）→ 写死的 33。
    """

    global _TYPELIB_MAJOR_CACHE
    if _TYPELIB_MAJOR_CACHE is not None:
        return _TYPELIB_MAJOR_CACHE

    # 注册表子键并不可靠（本机枚举出 21、1，而实际装的是 33），
    # 所以只把它当候选来源之一，最终一律按版本号从高到低试、取第一个能加载的。
    # 能加载说明这个版本的类型库确实注册了，取最高即最新安装的那版。
    candidates = set(_installed_typelib_majors())
    candidates.update(_TRY_TYPELIB_MAJORS)
    candidates.add(SOLIDWORKS_TYPELIB_MAJOR)

    try:
        import win32com.client
    except ImportError:
        _TYPELIB_MAJOR_CACHE = SOLIDWORKS_TYPELIB_MAJOR
        return _TYPELIB_MAJOR_CACHE

    for major in sorted(candidates, reverse=True):
        try:
            win32com.client.gencache.EnsureModule(
                SOLIDWORKS_TYPELIB_ID, 0, major, 0
            )
        except Exception:  # noqa: BLE001 - EnsureModule 失败就换下一个版本
            logger.debug("SolidWorks 类型库主版本 %d 不可用", major)
            continue
        logger.info("SolidWorks 类型库主版本 %d 加载成功", major)
        _TYPELIB_MAJOR_CACHE = major
        return major

    # 一个都加载不了时仍返回兜底值，让调用方拿到原本的报错，而不是这里静默吞掉。
    _TYPELIB_MAJOR_CACHE = SOLIDWORKS_TYPELIB_MAJOR
    return _TYPELIB_MAJOR_CACHE


def ensure_solidworks_typelib() -> Any:
    """拿到 SolidWorks 强类型模块，自动适配当前装的版本。"""

    import win32com.client

    return win32com.client.gencache.EnsureModule(
        SOLIDWORKS_TYPELIB_ID, 0, typelib_major(), 0
    )
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
# step6 累计 +3.5mm，才能让浅槽朝板面越过中心线达到现场约 3.4mm。
MAX_AUTO_BEND_ATTEMPTS = 3
MAX_RELIEF_STEPS = MAX_AUTO_BEND_ATTEMPTS - 1
# 写死：矩形释放槽扩级（绝对值，不是板厚比例）。
# step0 不扩；step1 长宽各 +1.0mm；之后每级再 +0.5mm。
# 累计：step≥1 → 1.0 + (step-1)*0.5
RECT_RELIEF_FIRST_EXPAND_MM = 1.0
RECT_RELIEF_EXPAND_MM = 0.5


# 默认关闭 CAD 直导。InsertDwgOrDxfFile2 导入的草图在 SolidWorks 里改不了，
# 生成按钮和一键导出都用 SketchManager 重画外轮廓、孔和折弯线。
# 仍可显式传 cad_import=True 走直导（失败会回退重画）。
USE_CAD_IMPORT_DEFAULT = False
# 批量导出时保存后立即关闭文档，避免 SW 里堆积几十个打开的零件。
CLOSE_SAVED_DOCS = False
SW_IMPORT_DXFDWG_TO_EXISTING_PART = 4
SW_LENGTH_UNIT_MM = 0


def resolve_use_cad_import(cad_import: bool | None) -> bool:
    """None 走默认（关闭）。只有显式 True 才调用 InsertDwgOrDxfFile2。"""

    if cad_import is None:
        return USE_CAD_IMPORT_DEFAULT
    return bool(cad_import)


def rect_relief_extra_mm(relief_step: int) -> float:
    """relief_step 对应的矩形释放槽边长累计扩量（mm）。step≤0 → 0。"""
    if relief_step <= 0:
        return 0.0
    return RECT_RELIEF_FIRST_EXPAND_MM + (relief_step - 1) * RECT_RELIEF_EXPAND_MM


# InsertSheetMetal3dBend may open PropertyManager and block forever
BEND_INSERT_TIMEOUT_SEC = 12.0
# Whole auto-bend phase wall clock; then BendRejected -> relief/flat
AUTO_BEND_WALL_TIMEOUT_SEC = 40.0
# Max InsertSheetMetal3dBend attempts per bend feature before reject
AUTO_BEND_MAX_INSERT_ATTEMPTS = 8

logger = logging.getLogger(__name__)


class SolidWorksGenerationError(RuntimeError):
    """Raised when SolidWorks cannot create or save the sheet-metal part."""


class BendRejectedError(SolidWorksGenerationError):
    def __init__(
        self,
        bend_indices: tuple[int, ...],
        *,
        relief_step: int = 0,
        max_relief_steps: int = MAX_RELIEF_STEPS,
    ) -> None:
        listed_bends = ", ".join(str(index + 1) for index in bend_indices)
        message = (
            f"SolidWorks 拒绝创建第 {listed_bends} 条折弯特征。"
            "可能原因包括折弯交会处释放槽不足、折弯线相交，"
            "或折弯线未穿过当前平面区域。"
        )
        if relief_step:
            message += f"已尝试扩大释放槽 {relief_step} 次。"
        if relief_step >= max_relief_steps:
            message += "已达到自动尝试上限，请人工检查释放槽和折弯线。"
        else:
            message += "可预览建议的释放槽位置，并确认自动逐级扩大后重试。"
        super().__init__(message)
        self.bend_indices = bend_indices
        self.relief_step = relief_step
        self.max_relief_steps = max_relief_steps
        self.completed_bend_count = 0
        self.bend_group_attempts: tuple[dict, ...] = ()


class ComDisconnectedBendError(BendRejectedError):
    """COM disconnect during bend; the caller may retry with a larger relief.

    timed_out=True means the insert watchdog fired. An unproven session is not
    force-killed. If the STA call is still stuck, the task worker is poisoned
    and later calls refuse instead of recycling that session.
    """

    def __init__(
        self,
        bend_indices: tuple[int, ...],
        *,
        relief_step: int = 0,
        max_relief_steps: int = MAX_RELIEF_STEPS,
        timed_out: bool = False,
    ) -> None:
        super().__init__(
            bend_indices,
            relief_step=relief_step,
            max_relief_steps=max_relief_steps,
        )
        self.timed_out = bool(timed_out)


# RPC_E_DISCONNECTED / RPC_S_SERVER_UNAVAILABLE 等常见断连 HRESULT
_COM_DISCONNECT_HRESULTS = frozenset(
    {
        -2147417848,  # 0x80010108 RPC_E_DISCONNECTED
        -2147023174,  # 0x800706BA RPC_S_SERVER_UNAVAILABLE
        -2147418111,  # 0x80010001 RPC_E_CALL_REJECTED（偶发，当断连处理）
        -2147467261,  # 0x80004003 E_POINTER（对象已释放）
    }
)


def _is_com_disconnect_error(error: BaseException | None) -> bool:
    """判断是否为 SolidWorks/COM 对象与客户端断开。"""

    if error is None:
        return False
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        args = getattr(current, "args", ())
        if args:
            hr = args[0]
            if isinstance(hr, int):
                # signed / unsigned HRESULT
                if hr in _COM_DISCONNECT_HRESULTS or (hr & 0xFFFFFFFF) in {
                    h & 0xFFFFFFFF for h in _COM_DISCONNECT_HRESULTS
                }:
                    return True
            elif isinstance(hr, BaseException) and id(hr) not in seen:
                current = hr
                continue
        message = str(current)
        if "断开连接" in message or "disconnected" in message.casefold():
            return True
        current = current.__cause__ or current.__context__
    return False


def _set_sw_automation_mode(solidworks: Any, enabled: bool) -> None:
    """Reduce interactive dialogs during automation.

    GetActiveObject / Dispatch alone must not change UserControl or
    CommandInProgress. Exclusive proof is required first.
    """

    lease = require_model_write()
    if getattr(lease, "keep_application_open", False) is True:
        # Background + last CloseDoc exits SW even without an ExitApp call.
        # Do not reset UserControl=False between S1 generation and S2 reopen.
        ensure_application_keepalive(lease, solidworks)
    else:
        try:
            solidworks.UserControl = not enabled
        except Exception:
            logger.debug("UserControl set failed", exc_info=True)
    try:
        solidworks.CommandInProgress = bool(enabled)
    except Exception:
        logger.debug("CommandInProgress set failed", exc_info=True)



_auto_bend_deadline: float | None = None


def _list_open_document_titles(application: Any) -> list[str]:
    """Best-effort open-document titles. Raises if the session cannot be listed."""

    titles: list[str] = []
    count = int(_com_read(application, "GetDocumentCount"))
    if count < 0 or count > 10000:
        raise SessionOwnershipError("invalid document count")
    current = _com_read(application, "GetFirstDocument")
    for _ in range(count):
        if current is None:
            raise SessionOwnershipError("document enumeration shorter than count")
        title = _com_read(current, "GetTitle")
        if not title or str(title) in titles:
            raise SessionOwnershipError("document inventory has empty/ambiguous titles")
        titles.append(str(title))
        current = _com_read(current, "GetNext")
    if current is not None:
        raise SessionOwnershipError("document enumeration longer than count")
    return titles


def _connect_task_solidworks(lease, win32com: Any, pythoncom: Any):
    """Reuse a proved native launch; legacy Dispatch/attach stays unproven."""

    if lease is None:
        raise SessionOwnershipError(
            "SolidWorks call is not on the task STA worker; refusing to attach "
            "to a session this task cannot prove it owns."
        )

    if lease.native_launch is not None:
        return lease.native_launch.reconnect(lease)

    def _get_active():
        return win32com.client.GetActiveObject("SldWorks.Application")

    def _dispatch():
        return win32com.client.Dispatch("SldWorks.Application")

    def _absent(error: BaseException) -> bool:
        return isinstance(error, pythoncom.com_error)

    return connect_application(
        lease,
        get_active=_get_active,
        dispatch=_dispatch,
        list_titles=_list_open_document_titles,
        is_absent=_absent,
    )


def _release_generation_session(
    lease,
    solidworks,
    typed_solidworks,
    *,
    document_title,
    close_document: bool,
    saved: bool,
    model,
) -> None:
    """Close an owned document. Exit the application only when exclusive."""

    application = typed_solidworks if typed_solidworks is not None else solidworks
    resolver = None
    if close_document and saved and model is not None:

        def resolver():
            updated = model.GetTitle()
            return updated or document_title

    try:
        release_task_documents(
            lease,
            application,
            title=document_title,
            close=close_document,
            resolve_title=resolver,
        )
    except SessionOwnershipError:
        logger.error(
            "skipped SolidWorks teardown because this task cannot prove ownership",
            exc_info=True,
        )


class _SwWatchdogTimeout(SwCallTimeoutError):
    """Bend insert exceeded its deadline.

    The watchdog does not force-kill SolidWorks. An unproven session is left
    running, and the waiting caller returns instead of hanging.
    """


def _call_with_sw_watchdog(timeout_sec: float, func, *args, **kwargs):
    """Bound a SolidWorks call. The watcher thread does not call COM."""

    try:
        return call_with_watchdog(timeout_sec, func, *args, **kwargs)
    except _SwWatchdogTimeout:
        raise
    except SwCallTimeoutError as error:
        raise _SwWatchdogTimeout(str(error)) from error


@dataclass(frozen=True)
class GenerationResult:
    path: Path
    profile_index: int
    bend_count: int
    hole_count: int
    folded_bounds: tuple[float, float, float, float, float, float]
    flat_bounds: tuple[float, float, float, float, float, float]
    relief_slot_count: int = 0
    # True=程序已 InsertSheetMetal3dBend；False=仅平板+折弯线草图，留给 SW 手折。
    auto_bent: bool = False
    bend_sketch_name: str = ""
    # 平板件中折弯线参考草图实际直线数（-1=未读到；自动折成时为 0）。
    bend_sketch_line_count: int = 0
    # True=基体法兰草图来自原图 DWG/DXF 原样导入；False=回退 Python 重画。
    cad_imported: bool = False
    auto_bend_attempts: int = 0
    auto_bend_abandoned: bool = False
    auto_bend_failed_count: int = 0
    bend_allowance_verified: bool = False
    k_factor_readback: float | None = None
    relief_step_used: int = 0
    bend_attempts: tuple[dict, ...] = ()
    bend_group_attempts: tuple[dict, ...] = ()


@dataclass(frozen=True)
class ReliefCutout:
    center: tuple[float, float]
    radius_mm: float
    replaced_profile_index: int | None = None


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
class RollerGenerationResult:
    path: Path
    roller_type: str
    overall_length_mm: float
    barrel_length_mm: float
    bounds: tuple[float, float, float, float, float, float]
    tube_length_mm: float = 0.0
    sprocket_outer_diameter_mm: float | None = None


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


def _line_intersection(
    first: Primitive,
    second: Primitive,
) -> tuple[float, float] | None:
    first_start, first_end = first.points[0], first.points[-1]
    second_start, second_end = second.points[0], second.points[-1]
    first_dx = first_end[0] - first_start[0]
    first_dy = first_end[1] - first_start[1]
    second_dx = second_end[0] - second_start[0]
    second_dy = second_end[1] - second_start[1]
    denominator = first_dx * second_dy - first_dy * second_dx
    if abs(denominator) <= 1e-10:
        return None
    offset_x = second_start[0] - first_start[0]
    offset_y = second_start[1] - first_start[1]
    factor = (offset_x * second_dy - offset_y * second_dx) / denominator
    return (
        first_start[0] + factor * first_dx,
        first_start[1] + factor * first_dy,
    )


def _segment_intersection(
    first_start: tuple[float, float],
    first_end: tuple[float, float],
    second_start: tuple[float, float],
    second_end: tuple[float, float],
) -> tuple[float, float] | None:
    first_dx = first_end[0] - first_start[0]
    first_dy = first_end[1] - first_start[1]
    second_dx = second_end[0] - second_start[0]
    second_dy = second_end[1] - second_start[1]
    denominator = first_dx * second_dy - first_dy * second_dx
    if abs(denominator) <= 1e-12:
        return None
    offset_x = second_start[0] - first_start[0]
    offset_y = second_start[1] - first_start[1]
    first_factor = (offset_x * second_dy - offset_y * second_dx) / denominator
    second_factor = (offset_x * first_dy - offset_y * first_dx) / denominator
    tolerance = 1e-9
    if not -tolerance <= first_factor <= 1.0 + tolerance:
        return None
    if not -tolerance <= second_factor <= 1.0 + tolerance:
        return None
    return (
        first_start[0] + first_factor * first_dx,
        first_start[1] + first_factor * first_dy,
    )


def _bend_profile_intersections(
    bend: Primitive,
    profile: Primitive,
) -> tuple[tuple[float, float], ...]:
    """折弯线与外轮廓的交点，即折弯端部需要释放空间的位置。"""
    start, end = bend.points[0], bend.points[-1]
    points = profile.points
    found: list[tuple[float, float]] = []
    for first, second in zip(points, points[1:]):
        hit = _segment_intersection(start, end, first, second)
        if hit is not None:
            found.append(hit)
    return tuple(found)


def _ray_profile_hit(
    origin: tuple[float, float],
    direction: tuple[float, float],
    profile: Primitive,
) -> tuple[float, float] | None:
    """从 origin 沿 direction 射出，返回与外轮廓最近的交点。"""
    origin_x, origin_y = origin
    direction_x, direction_y = direction
    points = profile.points
    best_distance: float | None = None
    best_point: tuple[float, float] | None = None
    for first, second in zip(points, points[1:]):
        edge_x = second[0] - first[0]
        edge_y = second[1] - first[1]
        denominator = direction_x * edge_y - direction_y * edge_x
        if abs(denominator) <= 1e-12:
            continue
        offset_x = first[0] - origin_x
        offset_y = first[1] - origin_y
        ray_factor = (offset_x * edge_y - offset_y * edge_x) / denominator
        edge_factor = (
            offset_x * direction_y - offset_y * direction_x
        ) / denominator
        if ray_factor < -1e-9 or not -1e-9 <= edge_factor <= 1.0 + 1e-9:
            continue
        if best_distance is not None and ray_factor >= best_distance:
            continue
        best_distance = ray_factor
        best_point = (
            origin_x + direction_x * ray_factor,
            origin_y + direction_y * ray_factor,
        )
    return best_point


def _bend_outline_ends(
    bend: Primitive,
    profile: Primitive,
) -> tuple[tuple[float, float], ...]:
    """折弯两端与外轮廓的交点。

    折弯线本身就跨过轮廓时直接取交点；图纸里把折弯线画成悬在零件内部
    的短线段时（常见于两端各画一小段示意），则沿折弯方向延长到轮廓，
    否则软件无法给出释放槽位置，只能放弃生成。
    """
    start, end = bend.points[0], bend.points[-1]
    direct = _bend_profile_intersections(bend, profile)
    if direct:
        return direct
    delta_x = end[0] - start[0]
    delta_y = end[1] - start[1]
    length = math.hypot(delta_x, delta_y)
    if length <= 1e-12:
        return ()
    unit_x, unit_y = delta_x / length, delta_y / length
    found: list[tuple[float, float]] = []
    forward = _ray_profile_hit(end, (unit_x, unit_y), profile)
    if forward is not None:
        found.append(forward)
    backward = _ray_profile_hit(start, (-unit_x, -unit_y), profile)
    if backward is not None:
        found.append(backward)
    return tuple(found)


def _bend_feature_outline_span(
    bend: Primitive,
    profile: Primitive,
) -> tuple[tuple[float, float], tuple[float, float]] | None:
    """特征草图用的整段穿越：即使红线只碰到一条边，也取这条线上离得最远的两个交点。"""

    start, end = bend.points[0], bend.points[-1]
    delta_x = end[0] - start[0]
    delta_y = end[1] - start[1]
    length = math.hypot(delta_x, delta_y)
    if length <= 1e-12:
        return None
    unit_x, unit_y = delta_x / length, delta_y / length
    found: list[tuple[float, float]] = list(_bend_profile_intersections(bend, profile))
    midpoint = ((start[0] + end[0]) / 2.0, (start[1] + end[1]) / 2.0)
    for origin, direction in (
        (end, (unit_x, unit_y)),
        (start, (-unit_x, -unit_y)),
        (midpoint, (unit_x, unit_y)),
        (midpoint, (-unit_x, -unit_y)),
    ):
        hit = _ray_profile_hit(origin, direction, profile)
        if hit is not None:
            found.append(hit)
    if len(found) < 2:
        return None

    def _along(point: tuple[float, float]) -> float:
        return point[0] * unit_x + point[1] * unit_y

    found.sort(key=_along)
    if math.dist(found[0], found[-1]) <= 1e-6:
        return None
    return found[0], found[-1]



def _profile_ring_points(
    profile: Primitive,
) -> list[tuple[float, float]]:
    points = list(profile.points)
    if len(points) > 1 and math.dist(points[0], points[-1]) <= 1e-9:
        points = points[:-1]
    return points


def _polyline_from_ring(
    profile: Primitive,
    ring: list[tuple[float, float]],
) -> Primitive:
    if len(ring) < 3:
        return profile
    closed = list(ring)
    if math.dist(closed[0], closed[-1]) > 1e-9:
        closed.append(closed[0])
    segments = tuple(
        SketchSegment(start, end)
        for start, end in zip(closed, closed[1:])
        if math.dist(start, end) > 1e-12
    )
    return replace(
        profile,
        points=tuple(closed),
        closed=True,
        curve_segments=segments,
        circle_center=None,
        circle_radius=None,
        kind=profile.kind if profile.kind not in ("CIRCLE",) else "LINE_LOOP",
    )


def _is_axis_aligned_pair(
    a: tuple[float, float],
    b: tuple[float, float],
    *,
    tol: float = 1e-6,
) -> bool:
    return abs(a[0] - b[0]) <= tol or abs(a[1] - b[1]) <= tol


def axis_aligned_rect_bounds(
    profile: Primitive,
    *,
    tol: float = 1e-4,
) -> tuple[float, float, float, float] | None:
    """若轮廓是轴对齐矩形，返回 (minx, miny, maxx, maxy)。"""

    ring = _profile_ring_points(profile)
    if len(ring) < 4:
        return None
    for start, end in zip(ring, ring[1:] + ring[:1]):
        if not _is_axis_aligned_pair(start, end, tol=tol):
            return None
    xs = [point[0] for point in ring]
    ys = [point[1] for point in ring]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    if max_x - min_x <= tol or max_y - min_y <= tol:
        return None
    for x, y in ring:
        on_v = abs(x - min_x) <= tol or abs(x - max_x) <= tol
        on_h = abs(y - min_y) <= tol or abs(y - max_y) <= tol
        if not (on_v or on_h):
            return None
        if on_v and not (min_y - tol <= y <= max_y + tol):
            return None
        if on_h and not (min_x - tol <= x <= max_x + tol):
            return None
    return min_x, min_y, max_x, max_y


def expand_axis_aligned_rect_profile(
    profile: Primitive,
    extra_mm: float,
) -> Primitive:
    """矩形孔：长、宽各加大 extra_mm，中心不变。"""

    if extra_mm <= 0:
        return profile
    bounds = axis_aligned_rect_bounds(profile)
    if bounds is None:
        return profile
    min_x, min_y, max_x, max_y = bounds
    width = max_x - min_x
    height = max_y - min_y
    center = ((min_x + max_x) / 2.0, (min_y + max_y) / 2.0)
    half_w = (width + extra_mm) / 2.0
    half_h = (height + extra_mm) / 2.0
    ring = [
        (center[0] - half_w, center[1] - half_h),
        (center[0] + half_w, center[1] - half_h),
        (center[0] + half_w, center[1] + half_h),
        (center[0] - half_w, center[1] + half_h),
    ]
    return _polyline_from_ring(profile, ring)


def _distance_point_to_segment(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length_sq = dx * dx + dy * dy
    if length_sq <= 1e-18:
        return math.dist(point, start)
    factor = ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length_sq
    factor = min(1.0, max(0.0, factor))
    return math.dist(point, (start[0] + factor * dx, start[1] + factor * dy))


def _panel_sign_from_bends(
    axis: str,
    cx: float,
    cy: float,
    bend_lines: tuple[Primitive, ...],
) -> float | None:
    """离槽最近的折弯线：沿法向哪一侧已经在板面里，扩槽就继续往哪一侧。"""

    best: tuple[tuple[float, float], tuple[float, float]] | None = None
    best_distance = 1e9
    for bend in bend_lines:
        if len(bend.points) < 2:
            continue
        start, end = bend.points[0], bend.points[-1]
        distance = _distance_point_to_segment((cx, cy), start, end)
        if distance < best_distance:
            best_distance = distance
            best = (start, end)
    if best is None or best_distance > 25.0:
        return None
    start, end = best
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length = math.hypot(dx, dy)
    if length <= 1e-9:
        return None
    normal_x, normal_y = -dy / length, dx / length
    signed = (cx - start[0]) * normal_x + (cy - start[1]) * normal_y
    component = signed * (normal_x if axis == "x" else normal_y)
    if abs(component) <= 1e-6:
        return None
    return 1.0 if component > 0.0 else -1.0


def _one_sided_panel_sign(
    axis: str,
    cluster: list[tuple[int, float, float, bool, bool]],
    ring: list[tuple[float, float]],
    bend_lines: tuple[Primitive, ...],
) -> float:
    """两侧对推时不再各分一半。整份 extra 只加在朝板面的一侧。"""

    cx = sum(ring[item[0]][0] for item in cluster) / len(cluster)
    cy = sum(ring[item[0]][1] for item in cluster) / len(cluster)
    from_bend = _panel_sign_from_bends(axis, cx, cy, bend_lines)
    if from_bend is not None:
        return from_bend
    part_x = sum(point[0] for point in ring) / len(ring)
    part_y = sum(point[1] for point in ring) / len(ring)
    delta = (part_x - cx) if axis == "x" else (part_y - cy)
    if abs(delta) <= 1e-6:
        return 1.0
    return 1.0 if delta > 0.0 else -1.0


def expand_rectangular_relief_notches(
    profile: Primitive,
    extra_mm: float,
    *,
    max_notch_edge_mm: float | None = None,
    bend_lines: tuple[Primitive, ...] = (),
) -> Primitive:
    """外轮廓轴对齐矩形释放槽：长与宽各加大 extra_mm，只朝板面一侧。

    凹角按槽簇处理。某一轴上只有一侧有凹角时，整份 extra 推那一侧。
    两侧都有凹角时也不再各推 extra/2：深度轴整份推向折弯中心线的板面一侧
    （没有折弯线时推向零件内部），宽度轴整份加在稳定的一侧。
    邻点增量用 merge-max，避免叠成双倍。不把槽口改成斜切。
    """

    if extra_mm <= 0:
        return profile
    ring = _profile_ring_points(profile)
    n = len(ring)
    if n < 6:
        return profile

    area = 0.0
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        area += x1 * y2 - x2 * y1
    ccw = area > 0

    span_x = max(p[0] for p in ring) - min(p[0] for p in ring)
    span_y = max(p[1] for p in ring) - min(p[1] for p in ring)
    if max_notch_edge_mm is None:
        max_notch_edge_mm = max(8.0, min(40.0, 0.12 * min(span_x, span_y)))

    def _merge(old: float, new: float) -> float:
        if new == 0.0:
            return old
        if old == 0.0:
            return new
        if (old > 0 and new > 0) or (old < 0 and new < 0):
            return math.copysign(max(abs(old), abs(new)), new)
        # 相反方向：保留幅度更大者
        return new if abs(new) >= abs(old) else old

    # Detect concave AA corners and their raw push directions.
    corners: list[tuple[int, float, float, bool, bool]] = []
    for i in range(n):
        prev_pt = ring[(i - 1) % n]
        point = ring[i]
        next_pt = ring[(i + 1) % n]
        if not (
            _is_axis_aligned_pair(prev_pt, point)
            and _is_axis_aligned_pair(point, next_pt)
        ):
            continue
        len_in = math.dist(prev_pt, point)
        len_out = math.dist(point, next_pt)
        if len_in > max_notch_edge_mm or len_out > max_notch_edge_mm:
            continue
        if len_in <= 1e-9 or len_out <= 1e-9:
            continue
        cross = (point[0] - prev_pt[0]) * (next_pt[1] - point[1]) - (
            point[1] - prev_pt[1]
        ) * (next_pt[0] - point[0])
        is_concave = cross < 0 if ccw else cross > 0
        if not is_concave:
            continue
        horizontal_in = abs(point[1] - prev_pt[1]) <= 1e-6
        horizontal_out = abs(point[1] - next_pt[1]) <= 1e-6
        if horizontal_in == horizontal_out:
            continue
        ua = (prev_pt[0] - point[0], prev_pt[1] - point[1])
        ub = (next_pt[0] - point[0], next_pt[1] - point[1])
        sx = 0.0
        sy = 0.0
        if abs(ua[0] + ub[0]) > 1e-12:
            sx = -math.copysign(1.0, ua[0] + ub[0])
        if abs(ua[1] + ub[1]) > 1e-12:
            sy = -math.copysign(1.0, ua[1] + ub[1])
        if sx == 0.0 and sy == 0.0:
            continue
        corners.append((i, sx, sy, horizontal_in, horizontal_out))

    if not corners:
        return profile

    ordered = sorted(corners, key=lambda item: item[0])
    clusters: list[list[tuple[int, float, float, bool, bool]]] = []
    current = [ordered[0]]
    for item in ordered[1:]:
        if item[0] - current[-1][0] <= 1:
            current.append(item)
        else:
            clusters.append(current)
            current = [item]
    if clusters and (ordered[0][0] + n - current[-1][0]) <= 1:
        current.extend(clusters[0])
        clusters[0] = current
    else:
        clusters.append(current)

    deltas = [(0.0, 0.0) for _ in range(n)]
    for cluster in clusters:
        # 长宽各加 extra，但整份只推向板面一侧，不两侧均分。
        # 凹角更多的一侧就是槽往板面凹进去的方向；两侧一样多时，
        # 深度轴跟最近的折弯中心线（没有线就跟零件内部），宽度轴只动一侧。
        # 现场：往翼板侧扩几乎无效，槽要往板面越过中心线才折得成。
        def _axis_scale(sign: float, n_pos: int, n_neg: int, axis: str) -> float:
            if sign == 0.0 or n_pos == 0 or n_neg == 0:
                return 1.0
            if n_pos != n_neg:
                major = 1.0 if n_pos > n_neg else -1.0
                return 1.0 if sign == major else 0.0
            chosen = _one_sided_panel_sign(axis, cluster, ring, bend_lines)
            return 1.0 if sign == chosen else 0.0

        n_pos_x = sum(1 for _, sx, _, _, _ in cluster if sx > 0)
        n_neg_x = sum(1 for _, sx, _, _, _ in cluster if sx < 0)
        n_pos_y = sum(1 for _, _, sy, _, _ in cluster if sy > 0)
        n_neg_y = sum(1 for _, _, sy, _, _ in cluster if sy < 0)
        for i, sx, sy, horizontal_in, horizontal_out in cluster:
            dpx = extra_mm * sx * _axis_scale(sx, n_pos_x, n_neg_x, "x")
            dpy = extra_mm * sy * _axis_scale(sy, n_pos_y, n_neg_y, "y")
            deltas[i] = (_merge(deltas[i][0], dpx), _merge(deltas[i][1], dpy))
            prev_i = (i - 1) % n
            next_i = (i + 1) % n
            if horizontal_in:
                deltas[prev_i] = (
                    deltas[prev_i][0],
                    _merge(deltas[prev_i][1], dpy),
                )
            else:
                deltas[prev_i] = (
                    _merge(deltas[prev_i][0], dpx),
                    deltas[prev_i][1],
                )
            if horizontal_out:
                deltas[next_i] = (
                    deltas[next_i][0],
                    _merge(deltas[next_i][1], dpy),
                )
            else:
                deltas[next_i] = (
                    _merge(deltas[next_i][0], dpx),
                    deltas[next_i][1],
                )

    if all(abs(dx) <= 1e-15 and abs(dy) <= 1e-15 for dx, dy in deltas):
        return profile
    expanded = [
        (point[0] + delta[0], point[1] + delta[1])
        for point, delta in zip(ring, deltas)
    ]
    return _polyline_from_ring(profile, expanded)

def is_small_rectangular_relief_hole(
    hole: Primitive,
    outer: Primitive,
    *,
    max_side_mm: float | None = None,
) -> bool:
    bounds = axis_aligned_rect_bounds(hole)
    if bounds is None:
        return False
    min_x, min_y, max_x, max_y = bounds
    width = max_x - min_x
    height = max_y - min_y
    span_x, span_y = profile_span_mm(outer)
    if max_side_mm is None:
        max_side_mm = max(8.0, min(40.0, 0.12 * min(span_x, span_y)))
    return max(width, height) <= max_side_mm + 1e-9


def expand_rect_hole_one_side(
    hole: Primitive,
    extra_mm: float,
    panel_x: float,
    panel_y: float,
) -> Primitive:
    """矩形孔长、宽各加 extra_mm，增量只加在 panel_x / panel_y 指向的一侧。"""

    if extra_mm <= 0:
        return hole
    bounds = axis_aligned_rect_bounds(hole)
    if bounds is None:
        return hole
    min_x, min_y, max_x, max_y = bounds

    def grow(low: float, high: float, sign: float) -> tuple[float, float]:
        if sign < 0:
            return low - extra_mm, high
        return low, high + extra_mm

    min_x, max_x = grow(min_x, max_x, panel_x)
    min_y, max_y = grow(min_y, max_y, panel_y)
    ring = [
        (min_x, min_y),
        (max_x, min_y),
        (max_x, max_y),
        (min_x, max_y),
    ]
    return _polyline_from_ring(hole, ring)


def _rect_hole_growth_signs(
    hole: Primitive,
    bend_lines: tuple[Primitive, ...],
    outer: Primitive,
) -> tuple[float, float]:
    bounds = axis_aligned_rect_bounds(hole)
    if bounds is None:
        return 1.0, 1.0
    cx = (bounds[0] + bounds[2]) / 2.0
    cy = (bounds[1] + bounds[3]) / 2.0
    sign_x = _panel_sign_from_bends("x", cx, cy, bend_lines)
    sign_y = _panel_sign_from_bends("y", cx, cy, bend_lines)
    outer_bounds = primitive_bounds(outer)
    part_x = (outer_bounds[0] + outer_bounds[2]) / 2.0
    part_y = (outer_bounds[1] + outer_bounds[3]) / 2.0
    if sign_x is None:
        sign_x = 1.0 if part_x >= cx else -1.0
    if sign_y is None:
        sign_y = 1.0 if part_y >= cy else -1.0
    return sign_x, sign_y


def apply_rectangular_relief_expansion(
    profile: Primitive,
    hole_profiles: tuple[tuple[Primitive, tuple[tuple[float, float], ...]], ...],
    relief_step: int,
    bend_lines: tuple[Primitive, ...] = (),
) -> tuple[
    Primitive,
    tuple[tuple[Primitive, tuple[tuple[float, float], ...]], ...],
    int,
]:
    """按级别扩大外轮廓矩形槽与小型矩形内孔。返回 (轮廓, 孔, 改动计数)。"""

    if relief_step <= 0:
        return profile, hole_profiles, 0
    extra = rect_relief_extra_mm(relief_step)
    expanded_profile = expand_rectangular_relief_notches(
        profile,
        extra,
        bend_lines=bend_lines,
    )
    changed = 0 if expanded_profile is profile else 1
    # 顶点坐标变化才算改动
    if expanded_profile.points != profile.points:
        changed = 1
        profile = expanded_profile
    else:
        profile = expanded_profile

    new_holes: list[tuple[Primitive, tuple[tuple[float, float], ...]]] = []
    for hole, hole_points in hole_profiles:
        if is_small_rectangular_relief_hole(hole, profile):
            sign_x, sign_y = _rect_hole_growth_signs(hole, bend_lines, profile)
            grown = expand_rect_hole_one_side(hole, extra, sign_x, sign_y)
            if grown.points != hole.points:
                changed += 1
                ring = _profile_ring_points(grown)
                new_holes.append((grown, tuple(ring)))
                continue
        new_holes.append((hole, hole_points))
    return profile, tuple(new_holes), changed


# 补槽不预开固定长度。每次失败只在向上、向内各加一点点。
RELIEF_FLANGE_BITE_MM = 0.2


def relief_cut_extents_mm(relief_step: int) -> tuple[float, float]:
    """返回这一级的 (向上, 向内)。两个方向同一小增量，不按板厚换算。"""

    extra = rect_relief_extra_mm(relief_step)
    return extra, extra


def minimal_relief_width_mm(thickness_mm: float) -> float:
    """工艺槽宽 k≥t（五金厂局部弯曲），同时不低于 SendCutSend 的 0.5t 下限。"""

    return max(float(thickness_mm), 0.5)


def minimal_relief_depth_past_centerline_mm(
    thickness_mm: float,
    radius_mm: float,
) -> float:
    """自折弯中心线朝板面的最小深度：t + R + 0.5mm（SendCutSend，从折弯线量）。

    现场约 3.4mm 越过中心线才折得成，和 t=2、R≈1 时的这个公式是同一量级。
    初槽用公式，不把 3.4 写成固定开口，薄板才不会一口开太大；
    折不成再按 step 只朝板面加深。
    """

    return float(thickness_mm) + float(radius_mm) + 0.5


def _interior_run_mm(
    profile: Primitive,
    origin: tuple[float, float],
    direction: tuple[float, float],
    *,
    limit_mm: float = 400.0,
) -> float:
    step = 0.5
    distance = 0.0
    bounds = primitive_bounds(profile)
    while distance < limit_mm:
        distance += step
        point = (
            origin[0] + direction[0] * distance,
            origin[1] + direction[1] * distance,
        )
        if not _point_in_profile(point, profile, bounds):
            return max(0.0, distance - step)
    return limit_mm


def _panel_axis_signs(
    profile: Primitive,
    point: tuple[float, float],
) -> tuple[float, float]:
    """从交点往 ±X / ±Y 看，材料更厚的一侧是板面。"""

    positive_x = _interior_run_mm(profile, point, (1.0, 0.0))
    negative_x = _interior_run_mm(profile, point, (-1.0, 0.0))
    positive_y = _interior_run_mm(profile, point, (0.0, 1.0))
    negative_y = _interior_run_mm(profile, point, (0.0, -1.0))
    sign_x = 1.0 if positive_x >= negative_x else -1.0
    sign_y = 1.0 if positive_y >= negative_y else -1.0
    return sign_x, sign_y


def _rectangle_hole(
    min_x: float,
    min_y: float,
    max_x: float,
    max_y: float,
) -> tuple[Primitive, tuple[tuple[float, float], ...]]:
    ring = (
        (min_x, min_y),
        (max_x, min_y),
        (max_x, max_y),
        (min_x, max_y),
        (min_x, min_y),
    )
    segments = tuple(SketchSegment(start, end) for start, end in zip(ring, ring[1:]))
    hole = Primitive(ring, True, False, "RELIEF", "LINE_LOOP", segments)
    return hole, ring


def ensure_intersection_reliefs(
    profile: Primitive,
    hole_profiles: tuple[tuple[Primitive, tuple[tuple[float, float], ...]], ...],
    bend_lines: tuple[Primitive, ...],
    thickness_mm: float,
    radius_mm: float,
    *,
    relief_step: int = 0,
) -> tuple[
    Primitive,
    tuple[tuple[Primitive, tuple[tuple[float, float], ...]], ...],
    int,
]:
    """交汇折弯附近没有释放槽时，补一块直角矩形槽，不斜切。

    step0 不新开槽。之后向上、向内各加本级的一小段（先 1.0mm，再每次 0.5mm），
    两个方向都加，不单走一边，也不一次开成固定长槽。已有槽则不动。
    """

    del radius_mm
    if len(bend_lines) < 2:
        return profile, hole_profiles, 0
    upward_mm, inward_mm = relief_cut_extents_mm(relief_step)
    if upward_mm <= 0 or inward_mm <= 0:
        return profile, hole_profiles, 0
    reach = max(3.0, min(max(upward_mm, inward_mm), 8.0))
    bounds = primitive_bounds(profile)
    added: list[tuple[Primitive, tuple[tuple[float, float], ...]]] = []
    seen: list[tuple[float, float]] = []
    for first_index, first in enumerate(bend_lines):
        for second in bend_lines[first_index + 1 :]:
            point = _line_intersection(first, second)
            if point is None:
                continue
            if not _point_in_profile(point, profile, bounds):
                continue
            near_limit = max(6.0, thickness_mm * 3.0)
            if (
                _distance_point_to_segment(point, first.points[0], first.points[-1])
                > near_limit
                or _distance_point_to_segment(point, second.points[0], second.points[-1])
                > near_limit
            ):
                continue
            if any(math.dist(point, previous) <= reach for previous in seen):
                continue
            sign_x, sign_y = _panel_axis_signs(profile, point)
            # 向上、向内都挖，不把增量只留给材料更长的那一侧。
            extent_x = upward_mm
            extent_y = inward_mm
            min_x = point[0] if sign_x > 0 else point[0] - extent_x
            max_x = point[0] + extent_x if sign_x > 0 else point[0]
            min_y = point[1] if sign_y > 0 else point[1] - extent_y
            max_y = point[1] + extent_y if sign_y > 0 else point[1]
            center = ((min_x + max_x) / 2.0, (min_y + max_y) / 2.0)
            if not _point_in_profile(center, profile, bounds):
                continue
            if any(math.dist(point, vertex) <= reach for vertex in profile.points):
                continue
            blocked = False
            for hole, _hole_points in (*hole_profiles, *added):
                hole_bounds = primitive_bounds(hole)
                if _point_in_profile(point, hole, hole_bounds) or _point_in_profile(
                    center, hole, hole_bounds
                ):
                    blocked = True
                    break
                if any(math.dist(point, vertex) <= reach for vertex in hole.points):
                    blocked = True
                    break
            if blocked:
                continue
            added.append(_rectangle_hole(min_x, min_y, max_x, max_y))
            seen.append(point)
    if not added:
        return profile, hole_profiles, 0
    return profile, hole_profiles + tuple(added), len(added)


def suggest_relief_cutouts(
    analysis: DrawingAnalysis,
    profiles: tuple[Primitive, ...],
    outer_profile_index: int,
    bend_indices: Iterable[int],
    thickness_mm: float,
    relief_step: int,
) -> tuple[ReliefCutout, ...]:
    """建议折弯交点 / 端点附近的圆形释放槽（仅预览用；生成路径不调用）。

    ``relief_step``：
    - 0：不预开圆孔（step0 只用图纸原槽）；
    - 1..N：圆孔半径 = max(已有圆孔, 0) + step×0.5×t，不与矩形扩槽叠加进实体。
    """

    indices = tuple(dict.fromkeys(int(index) for index in bend_indices))
    if not indices:
        raise ValueError("无法自动定位释放槽：没有可用的折弯线。")
    if relief_step < 0:
        raise ValueError("释放槽重试级数不能为负数。")
    if not 0 <= outer_profile_index < len(profiles):
        raise ValueError("外轮廓索引无效。")

    # step0：原槽，不建议额外圆孔。
    if relief_step <= 0:
        return ()

    minimum_separation = max(thickness_mm * 0.5, 0.05)
    outer_profile = profiles[outer_profile_index]
    outer_bounds = primitive_bounds(outer_profile)
    centers: list[tuple[float, float]] = []
    # 优先：折弯线延长交点（拐角最需要释放）。
    for first_position, first_index in enumerate(indices):
        for second_index in indices[first_position + 1 :]:
            intersection = _line_intersection(
                analysis.bend_lines[first_index],
                analysis.bend_lines[second_index],
            )
            if intersection is None:
                continue
            if not _point_in_profile(intersection, outer_profile, outer_bounds):
                continue
            if all(
                math.dist(intersection, center) > minimum_separation
                for center in centers
            ):
                centers.append(intersection)
    # 再补：每条折弯与外轮廓的端部交点（即使有交点，端部也常需要槽）。
    for index in indices:
        for point in _bend_outline_ends(
            analysis.bend_lines[index],
            outer_profile,
        ):
            if not _point_in_profile(point, outer_profile, outer_bounds):
                # 交点在边上时 _point_in_profile 视为 True；若仍在外则内偏一点。
                continue
            if all(
                math.dist(point, center) > minimum_separation
                for center in centers
            ):
                centers.append(point)
    if not centers:
        listed_bends = ", ".join(str(index + 1) for index in indices)
        raise ValueError(
            f"第 {listed_bends} 条折弯线既没有可用交点，也没有落在外轮廓上，"
            "无法自动定位释放槽；请手动检查折弯线是否穿过零件。"
        )

    cutouts: list[ReliefCutout] = []
    existing_hole_indices = contained_hole_indices(
        profiles,
        outer_profile_index,
    )
    for center in centers:
        matched_profile: int | None = None
        base_radius = 0.0
        for profile_index in existing_hole_indices:
            profile = profiles[profile_index]
            if profile.kind != "CIRCLE":
                continue
            circle_center = profile.circle_center
            circle_radius = profile.circle_radius
            if circle_center is None or circle_radius is None:
                continue
            match_tolerance = max(thickness_mm * 2.0, 0.1)
            if math.dist(circle_center, center) <= match_tolerance:
                matched_profile = profile_index
                base_radius = circle_radius
                break
        # step0 → 0.5t；之后每级 +0.5t。已有圆孔则在其上继续扩大。
        # 仅 retry 时建议圆孔：半径 = 已有圆孔(若有) + step×0.5t；不强制预开 0.5t。
        radius = base_radius + relief_step * (thickness_mm * 0.5)
        if radius <= 1e-9:
            radius = thickness_mm * 0.5
        cutouts.append(ReliefCutout(center, radius, matched_profile))
    return tuple(cutouts)


def _point_in_profile(
    point: tuple[float, float],
    profile: Primitive,
    bounds: tuple[float, float, float, float] | None = None,
) -> bool:
    x, y = point
    vertices = profile.points
    if len(vertices) < 4:
        return False
    if bounds is None:
        bounds = (
            min(vertex[0] for vertex in vertices),
            min(vertex[1] for vertex in vertices),
            max(vertex[0] for vertex in vertices),
            max(vertex[1] for vertex in vertices),
        )
    min_x, min_y, max_x, max_y = bounds
    if x < min_x or x > max_x or y < min_y or y > max_y:
        return False

    inside = False
    for start, end in zip(vertices, vertices[1:]):
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        cross = (x - start[0]) * dy - (y - start[1]) * dx
        if abs(cross) <= 1e-7 and (
            min(start[0], end[0]) - 1e-7 <= x <= max(start[0], end[0]) + 1e-7
            and min(start[1], end[1]) - 1e-7 <= y <= max(start[1], end[1]) + 1e-7
        ):
            return True
        if (start[1] > y) != (end[1] > y):
            crossing_x = start[0] + (y - start[1]) * dx / dy
            if x < crossing_x:
                inside = not inside
    return inside


def profile_bend_indices(
    profile: Primitive,
    bends: Iterable[Primitive],
    holes: Iterable[Primitive] = (),
) -> tuple[int, ...]:
    """折弯线中点落在外轮廓内；剔除落在内孔里的短线（孔中心十字线）。"""
    if not profile.closed:
        return ()
    hole_list = [
        (
            hole,
            (
                min(point[0] for point in hole.points),
                min(point[1] for point in hole.points),
                max(point[0] for point in hole.points),
                max(point[1] for point in hole.points),
            ),
        )
        for hole in holes
        if hole.closed and hole.points
    ]
    bounds = (
        min(point[0] for point in profile.points),
        min(point[1] for point in profile.points),
        max(point[0] for point in profile.points),
        max(point[1] for point in profile.points),
    )
    matches: list[int] = []
    for index, bend in enumerate(bends):
        midpoint = (
            (bend.points[0][0] + bend.points[-1][0]) / 2,
            (bend.points[0][1] + bend.points[-1][1]) / 2,
        )
        if (
            bounds[0] <= midpoint[0] <= bounds[2]
            and bounds[1] <= midpoint[1] <= bounds[3]
            and _point_in_profile(midpoint, profile, bounds)
            and not any(
                hb[0] <= midpoint[0] <= hb[2]
                and hb[1] <= midpoint[1] <= hb[3]
                and _point_in_profile(midpoint, hole, hb)
                # 只剔孔中心十字：线长不超过孔尺寸 1.5 倍 + 6 mm；
                # 真正的折弯线贯穿板面，远长于孔。
                and math.dist(bend.points[0], bend.points[-1])
                <= 1.5 * max(hb[2] - hb[0], hb[3] - hb[1]) + 6.0
                for hole, hb in hole_list
            )
        ):
            matches.append(index)
    return tuple(matches)


def _as_interface(module: Any, instance: Any, interface: str) -> Any:
    return getattr(module, interface)(instance._oleobj_)


def _features(model: Any, module: Any) -> list[Any]:
    features: list[Any] = []
    for index in range(model.GetFeatureCount()):
        raw_feature = model.FeatureByPositionReverse(index)
        if raw_feature is not None:
            features.append(_as_interface(module, raw_feature, "IFeature"))
    return features


def _latest_profile_sketch(
    model: Any,
    module: Any,
    known_names: set[str],
) -> Any | None:
    """Return the sketch feature that was just created and is not yet known.

    The last feature added is almost always the sketch that was just closed, so
    checking it first avoids enumerating every feature in the model. When that
    does not match, fall back to the exhaustive scan so behaviour is unchanged.
    """
    raw_feature = model.FeatureByPositionReverse(0)
    if raw_feature is not None:
        candidate = _as_interface(module, raw_feature, "IFeature")
        if (
            candidate.GetTypeName2() == "ProfileFeature"
            and candidate.Name not in known_names
        ):
            return candidate
    return next(
        (
            feature
            for feature in _features(model, module)
            if feature.GetTypeName2() == "ProfileFeature"
            and feature.Name not in known_names
        ),
        None,
    )


def _validate_single_closed_contour(
    sketch_feature: Any,
    profile: Primitive,
    module: Any,
) -> None:
    sketch = _as_interface(module, sketch_feature.GetSpecificFeature2(), "ISketch")
    contours = sketch.GetSketchContours() or ()
    closed = tuple(
        bool(_as_interface(module, contour, "ISketchContour").IsClosed())
        for contour in contours
    )
    if len(closed) != 1 or not all(closed):
        min_x, min_y, max_x, max_y = primitive_bounds(profile)
        raise SolidWorksGenerationError(
            "SolidWorks 无法识别为单一闭合轮廓："
            f"草图检测到 {len(closed)} 个闭合/未闭合环，"
            f"CAD 尺寸约 {max_x - min_x:.3f} × {max_y - min_y:.3f} mm。"
            "请检查所选边界是否有断点、重叠线、自交或误选内部孔线。"
        )


def _select_sketch_contours(
    model: Any,
    extension: Any,
    module: Any,
    sketch_feature: Any,
) -> bool:
    """选中草图闭合环；基体法兰/拉伸比只选 SKETCH 特征更稳。"""

    model.ClearSelection2(True)
    try:
        sketch = _as_interface(
            module, sketch_feature.GetSpecificFeature2(), "ISketch"
        )
        contours = sketch.GetSketchContours() or ()
        selected_any = False
        for index, raw_contour in enumerate(contours):
            contour = _as_interface(module, raw_contour, "ISketchContour")
            if not bool(contour.IsClosed()):
                continue
            # Select2(Append) 在部分版本可用；失败再 Select4。
            picked = False
            select2 = getattr(contour, "Select2", None)
            if callable(select2):
                try:
                    picked = bool(select2(index > 0, None))
                except Exception:  # noqa: BLE001
                    picked = False
            if not picked:
                picked = bool(
                    _as_interface(module, raw_contour, "IEntity").Select4(
                        index > 0, None
                    )
                )
            selected_any = selected_any or picked
        if selected_any:
            return True
    except Exception:  # noqa: BLE001
        pass
    model.ClearSelection2(True)
    if _as_interface(module, sketch_feature, "IEntity").Select4(False, None):
        return True
    return bool(
        extension.SelectByID2(
            sketch_feature.Name,
            "SKETCH",
            0.0,
            0.0,
            0.0,
            False,
            0,
            None,
            0,
        )
    )


def _polyline_only_profile(profile: Primitive) -> Primitive:
    """丢掉圆弧段，只用折线闭环——CreateArc 端点微缝时 SW 常拒拉伸。"""

    raw = list(profile.points)
    if len(raw) >= 2 and math.dist(raw[0], raw[-1]) <= 1e-9:
        raw = raw[:-1]
    if len(raw) < 3:
        return profile
    segments = tuple(
        SketchSegment(start, end)
        for start, end in zip(raw, raw[1:] + raw[:1])
        if math.dist(start, end) > 1e-9
    )
    if len(segments) < 3:
        return profile
    return Primitive(
        tuple(raw) + (raw[0],),
        True,
        False,
        profile.layer,
        "LINE_LOOP",
        segments,
        None,
        None,
    )


def _try_insert_base_flange(
    feature_manager: Any,
    thickness_m: float,
    radius_m: float,
    thicken_dir: bool,
    bend_allowance: BendAllowanceSpec | None = None,
    module: Any = None,
) -> Any | None:
    """尝试 InsertSheetMetalBaseFlange / BaseFlange2。"""

    custom_bend = _build_custom_bend_allowance(feature_manager, bend_allowance, module)
    insert2 = getattr(feature_manager, "InsertSheetMetalBaseFlange2", None)
    if callable(insert2):
        try:
            candidate = insert2(
                thickness_m,
                thicken_dir,
                radius_m,
                0.02,
                0.0,
                False,
                0,
                0,
                0,
                custom_bend,
                True,
                4,
                0.001,
                0.001,
                0.5,
                False,
                False,
                False,
            )
            if candidate is not None:
                return candidate
        except Exception:  # noqa: BLE001
            pass
    try:
        return feature_manager.InsertSheetMetalBaseFlange(
            thickness_m,
            thicken_dir,
            radius_m,
            0.02,
            0.0,
            False,
            0,
            0,
            0,
            custom_bend,
            True,
            4,
            0.001,
            0.001,
            0.5,
            False,
        )
    except Exception:  # noqa: BLE001
        return None


def _try_extrude_thin_solid(
    feature_manager: Any,
    thickness_m: float,
) -> Any | None:
    """空零件上首次拉伸必须 Merge=False，否则多版本直接返回 None。"""

    # (merge, use_feat_scope, use_auto_select, mid_plane)
    strategies = (
        (False, False, True, False),
        (False, True, True, False),
        (True, True, True, False),
        (False, False, True, True),
    )
    for merge, use_scope, auto_select, mid_plane in strategies:
        end_cond = (
            SW_END_CONDITION_MID_PLANE if mid_plane else SW_END_CONDITION_BLIND
        )
        depth = (thickness_m / 2.0) if mid_plane else thickness_m
        try:
            extrude = feature_manager.FeatureExtrusion2(
                True,
                False,
                False,
                end_cond,
                0,
                depth,
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
                use_scope,
                auto_select,
                0,
                0,
                False,
            )
        except Exception:  # noqa: BLE001
            extrude = None
        if extrude is not None:
            return extrude
        # 旧接口回退。
        extrusion = getattr(feature_manager, "FeatureExtrusion", None)
        if callable(extrusion):
            try:
                extrude = extrusion(
                    True,
                    False,
                    False,
                    end_cond,
                    0,
                    depth,
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
                    use_scope,
                    auto_select,
                )
            except Exception:  # noqa: BLE001
                extrude = None
            if extrude is not None:
                return extrude
    return None


def _body_bounds(part: Any, module: Any) -> tuple[float, float, float, float, float, float]:
    raw_bodies = part.GetBodies2(SW_BODY_TYPE_SOLID, False)
    if not raw_bodies:
        raise SolidWorksGenerationError("SolidWorks 未生成有效的钣金实体。")
    body = _as_interface(module, raw_bodies[0], "IBody2")
    boxes = [
        _as_interface(module, raw_face, "IFace2").GetBox()
        for raw_face in body.GetFaces()
    ]
    if not boxes:
        raise SolidWorksGenerationError("SolidWorks 钣金实体没有可读取的面。")
    return (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        min(box[2] for box in boxes),
        max(box[3] for box in boxes),
        max(box[4] for box in boxes),
        max(box[5] for box in boxes),
    )


def _build_custom_bend_allowance(
    feature_manager: Any,
    bend_allowance: BendAllowanceSpec | None,
    module: Any = None,
) -> Any | None:
    """创建 SolidWorks CustomBendAllowance；长度用米，K 为无量纲。"""

    if bend_allowance is None:
        return None
    creator = getattr(feature_manager, "CreateCustomBendAllowance", None)
    if not callable(creator):
        raise SolidWorksGenerationError("CreateCustomBendAllowance unavailable; refusing default allowance")
    custom = creator()
    if custom is None:
        raise SolidWorksGenerationError("CreateCustomBendAllowance returned no interface")
    # Use generated typelib ICustomBendAllowance, never a late-bound raw setter.
    # Gork observed an access violation on a dynamic KFactor property write.
    if module is not None:
        custom = _as_interface(module, custom, "ICustomBendAllowance")
    custom.Type = bend_allowance.sw_type
    if bend_allowance.mode == "k_factor":
        custom.KFactor = float(bend_allowance.k_factor)
    elif bend_allowance.mode == "bend_deduction":
        if bend_allowance.bend_deduction_mm is None:
            raise ValueError("折弯扣除模式缺少扣除值。")
        custom.BendDeduction = float(bend_allowance.bend_deduction_mm) / 1000.0
    else:
        if bend_allowance.bend_allowance_mm is None:
            raise ValueError("折弯补偿模式缺少补偿值。")
        custom.BendAllowance = float(bend_allowance.bend_allowance_mm) / 1000.0
    return custom


def _apply_sheet_metal_bend_allowance(
    model: Any,
    module: Any,
    bend_allowance: BendAllowanceSpec | None,
) -> None:
    """把扣除/K 因子写到零件的 Sheet-Metal 特征，保证展开与折弯一致。"""

    if bend_allowance is None:
        return
    for feature in _features(model, module):
        if feature.GetTypeName2() != "SheetMetal":
            continue
        definition = feature.GetDefinition()
        if definition is None:
            continue
        try:
            sheet_data = _as_interface(module, definition, "ISheetMetalFeatureData")
        except Exception:  # noqa: BLE001 - 版本差异时跳过
            continue
        getter = getattr(sheet_data, "GetCustomBendAllowance", None)
        setter = getattr(sheet_data, "SetCustomBendAllowance", None)
        if not callable(getter) or not callable(setter):
            # 旧接口：直接写 BendAllowanceType / BendDeduction。
            try:
                sheet_data.BendAllowanceType = bend_allowance.sw_type
                if bend_allowance.mode == "k_factor":
                    sheet_data.KFactor = float(bend_allowance.k_factor)
                elif bend_allowance.mode == "bend_deduction":
                    sheet_data.BendDeduction = (
                        float(bend_allowance.bend_deduction_mm or 0.0) / 1000.0
                    )
                else:
                    sheet_data.BendAllowance = (
                        float(bend_allowance.bend_allowance_mm or 0.0) / 1000.0
                    )
                feature.ModifyDefinition(sheet_data, model, None)
            except Exception:  # noqa: BLE001
                logger.warning("无法写入 Sheet-Metal 折弯扣除（旧接口）", exc_info=True)
            return
        try:
            if not sheet_data.AccessSelections(model, None):
                continue
            custom = getter()
            if custom is not None:
                custom = _as_interface(module, custom, "ICustomBendAllowance")
            if custom is None:
                sheet_data.ReleaseSelectionAccess()
                continue
            custom.Type = bend_allowance.sw_type
            if bend_allowance.mode == "k_factor":
                custom.KFactor = float(bend_allowance.k_factor)
            elif bend_allowance.mode == "bend_deduction":
                custom.BendDeduction = (
                    float(bend_allowance.bend_deduction_mm or 0.0) / 1000.0
                )
            else:
                custom.BendAllowance = (
                    float(bend_allowance.bend_allowance_mm or 0.0) / 1000.0
                )
            setter(custom)
            feature.ModifyDefinition(sheet_data, model, None)
            sheet_data.ReleaseSelectionAccess()
            logger.info(
                "已写入钣金折弯参数：mode=%s type=%d",
                bend_allowance.mode,
                bend_allowance.sw_type,
            )
            return
        except Exception:  # noqa: BLE001
            logger.warning("写入 Sheet-Metal 折弯扣除失败", exc_info=True)
            try:
                sheet_data.ReleaseSelectionAccess()
            except Exception:  # noqa: BLE001
                pass
            return


def _verify_sheet_metal_bend_allowance(model, module, spec):
    """Read a fresh native definition; ModifyDefinition=True is not evidence."""
    if spec is None:
        return None
    found = False
    observed = None
    for feature in _features(model, module):
        if feature.GetTypeName2() != "SheetMetal":
            continue
        found = True
        data = _as_interface(module, feature.GetDefinition(), "ISheetMetalFeatureData")
        if not data.AccessSelections(model, None):
            raise SolidWorksGenerationError("cannot read persisted sheet-metal bend allowance")
        try:
            custom = data.GetCustomBendAllowance()
            if custom is None:
                raise SolidWorksGenerationError("persisted CustomBendAllowance is unavailable")
            custom = _as_interface(module, custom, "ICustomBendAllowance")
            if int(custom.Type) != spec.sw_type:
                raise SolidWorksGenerationError("persisted bend allowance mode does not match request")
            field, wanted = {
                "k_factor": ("KFactor", spec.k_factor),
                "bend_deduction": ("BendDeduction", None if spec.bend_deduction_mm is None else spec.bend_deduction_mm / 1000),
                "bend_allowance": ("BendAllowance", None if spec.bend_allowance_mm is None else spec.bend_allowance_mm / 1000),
            }[spec.mode]
            observed = float(getattr(custom, field))
            if wanted is None or not math.isfinite(observed) or not math.isclose(observed, wanted, rel_tol=1e-8, abs_tol=1e-9):
                raise SolidWorksGenerationError(
                    f"persisted {field} mismatch: requested={wanted}, readback={observed}; not saving")
        finally:
            data.ReleaseSelectionAccess()
    if not found:
        raise SolidWorksGenerationError("SheetMetal feature missing; bend allowance is unverified")
    return observed


def _distance_point_to_segment(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length_sq = dx * dx + dy * dy
    if length_sq <= 1e-18:
        return math.dist(point, start)
    t = ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length_sq
    t = max(0.0, min(1.0, t))
    closest = (start[0] + t * dx, start[1] + t * dy)
    return math.dist(point, closest)


def _best_fixed_face_point(
    outer_profile: Primitive,
    bends: tuple[Primitive, ...],
    preferred: tuple[float, float] | None = None,
) -> tuple[float, float]:
    """选固定面点击：落在材料内、尽量远离所有折弯线（通常是中间不动的那一块）。"""

    return _fixed_face_pick_candidates(outer_profile, bends, preferred)[0]


def _fixed_face_pick_candidates(
    outer_profile: Primitive,
    bends: tuple[Primitive, ...],
    preferred: tuple[float, float] | None = None,
    *,
    holes: tuple[Primitive, ...] = (),
) -> list[tuple[float, float]]:
    """Select material in one fixed-panel cell, never by short-mark endpoints.

    Bend marks are finite annotations, but a moving panel is separated by the
    entire bend axis. A point beyond a short mark can already be on a flange
    folded by a previous group. Rank the common central cell using full axes
    and exclude cutouts. An explicit anchor is authoritative, not a seed for
    silently trying a different panel.
    """
    min_x, min_y, max_x, max_y = primitive_bounds(outer_profile)
    axes = []
    for bend in bends:
        start, end = bend.points[0], bend.points[-1]
        dx, dy = end[0] - start[0], end[1] - start[1]
        length = math.hypot(dx, dy)
        if length <= 1e-9:
            raise ValueError("fixed-panel selection received a zero-length bend")
        axes.append((start, -dy / length, dx / length))

    def signed(point, axis):
        start, nx, ny = axis
        return (point[0] - start[0]) * nx + (point[1] - start[1]) * ny

    def material(point):
        return (_point_in_profile(point, outer_profile)
                and not any(_point_in_profile(point, hole) for hole in holes))

    if preferred is not None:
        if (not all(math.isfinite(value) for value in preferred)
                or not material(preferred)
                or any(abs(signed(preferred, axis)) <= 1e-6 for axis in axes)):
            raise ValueError("fixed-panel anchor must be material outside holes and bend axes")
        return [preferred]

    reference = ((min_x + max_x) / 2, (min_y + max_y) / 2)
    reference_sides = [signed(reference, axis) for axis in axes]
    boundary_profiles = (outer_profile,) + tuple(holes)
    boundaries = []
    for profile in boundary_profiles:
        ring = _profile_ring_points(profile)
        boundaries.extend(zip(ring, ring[1:] + ring[:1]))
    scored = []
    central = []
    for ix in range(13):
        for iy in range(13):
            point = (min_x + (max_x - min_x) * (ix + 0.5) / 13,
                     min_y + (max_y - min_y) * (iy + 0.5) / 13)
            if not material(point):
                continue
            distances = [abs(signed(point, axis)) for axis in axes]
            if distances and min(distances) < max(0.15, (max_x-min_x+max_y-min_y)*0.01):
                continue
            distances += [_distance_point_to_segment(point, start, end)
                          for start, end in boundaries]
            score = min(distances) if distances else 0.0
            row = (score, -math.dist(point, reference), point)
            scored.append(row)
            if all(abs(side) <= 1e-7 or signed(point, axis) * side > 0
                   for side, axis in zip(reference_sides, axes)):
                central.append(row)
    # For nonconvex profiles the bbox centre can lie outside material. Use an
    # actual material sample then pin it for the complete folding sequence.
    ranked = sorted(central or scored, reverse=True)
    if not ranked:
        raise ValueError("no fixed-panel material point could be verified")
    return [row[2] for row in ranked[:8]]



def _region_seed_points(
    outer_profile: Primitive,
    bends: tuple[Primitive, ...],
) -> list[tuple[float, tuple[float, float]]]:
    """按近似平行折弯线把板料切成条带，取每条带中心作为固定面种子。"""

    if not bends:
        return []
    min_x, min_y, max_x, max_y = primitive_bounds(outer_profile)
    # 用第一条折弯方向判断主轴：更接近竖直 → 按 x 分带；否则按 y。
    first = bends[0]
    dx = abs(first.points[-1][0] - first.points[0][0])
    dy = abs(first.points[-1][1] - first.points[0][1])
    vertical = dy >= dx
    positions: list[float] = []
    for bend in bends:
        if vertical:
            positions.append((bend.points[0][0] + bend.points[-1][0]) / 2.0)
        else:
            positions.append((bend.points[0][1] + bend.points[-1][1]) / 2.0)
    positions = sorted(positions)
    edges = ([min_x] + positions + [max_x]) if vertical else (
        [min_y] + positions + [max_y]
    )
    seeds: list[tuple[float, tuple[float, float]]] = []
    for left, right in zip(edges, edges[1:]):
        if right - left <= 1e-6:
            continue
        mid = (left + right) / 2.0
        if vertical:
            point = (mid, (min_y + max_y) / 2.0)
        else:
            point = ((min_x + max_x) / 2.0, mid)
        # 分数：条带宽度（越宽越像固定底板）。
        seeds.append((right - left, point))
    seeds.sort(key=lambda item: item[0], reverse=True)
    return seeds


def _planar_faces_by_area(part: Any, module: Any) -> list[Any]:
    body = _as_interface(
        module,
        part.GetBodies2(SW_BODY_TYPE_SOLID, False)[0],
        "IBody2",
    )
    faces = [
        _as_interface(module, raw_face, "IFace2")
        for raw_face in body.GetFaces()
    ]
    planar: list[Any] = []
    for face in faces:
        try:
            surface = face.GetSurface()
            if surface is not None and bool(surface.IsPlane()):
                planar.append(face)
        except Exception:  # noqa: BLE001
            planar.append(face)
    if not planar:
        planar = faces
    planar.sort(key=lambda face: face.GetArea(), reverse=True)
    return planar


def _fixed_panel_plane_z(face: Any, module: Any = None) -> float:
    """Read exact planar geometry; GetBox is approximate, not a plane equation."""
    surface = _com_read(face, "GetSurface")
    if module is not None:
        surface = _as_interface(module, surface, "ISurface")
    if surface is None or not bool(_com_read(surface, "IsPlane")):
        raise ValueError("not_planar")
    plane = tuple(float(v) for v in _com_read(surface, "PlaneParams"))
    if len(plane) != 6 or not all(math.isfinite(v) for v in plane):
        raise ValueError("invalid_plane_parameters")
    nx, ny, nz, _, _, z = plane
    norm = math.sqrt(nx*nx + ny*ny + nz*nz)
    if norm <= 1e-12 or math.hypot(nx, ny) / norm > 1e-8:
        raise ValueError("not_fixed_xy_plane")
    return z


def _fixed_panel_faces(
    faces: Iterable[Any], anchor_mm: tuple[float, float],
    origin_mm: tuple[float, float], thickness_mm: float, *, module: Any = None,
) -> list[Any]:
    """Verify the unchanged fixed panel using exact plane + trimmed-face query."""
    x, y = ((anchor_mm[i] - origin_mm[i]) / 1000.0 for i in (0, 1))
    thickness_m = thickness_mm / 1000.0
    tolerance = 1e-7  # metres; numerical tolerance, never manufacturing clearance
    accepted = []
    rejected: dict[str, int] = {}
    for face in faces:
        try:
            z = _fixed_panel_plane_z(face, module)
            if min(abs(z), abs(z-thickness_m), abs(z+thickness_m)) > tolerance:
                raise ValueError("not_fixed_blank_level")
            closest = tuple(float(v) for v in face.GetClosestPointOn(x, y, z))
            if len(closest) < 3 or not all(math.isfinite(v) for v in closest[:3]):
                raise ValueError("invalid_closest_point")
            if math.dist((x, y, z), closest[:3]) > tolerance:
                raise ValueError("anchor_outside_trimmed_face")
            accepted.append(face)
        except Exception as error:
            if _is_com_disconnect_error(error):
                raise
            reason = str(error) if isinstance(error, ValueError) else type(error).__name__
            rejected[reason] = rejected.get(reason, 0) + 1
    logger.info("Fixed panel face verification: candidates=%d rejected=%s",
                len(accepted), rejected)
    return accepted


def _delete_model_item(model: Any, name: str, item_type: str) -> None:
    try:
        model.ClearSelection2(True)
        if model.Extension.SelectByID2(
            name, item_type, 0, 0, 0, False, 0, None, 0
        ):
            model.EditDelete()
    except Exception:  # noqa: BLE001
        pass


def _select_bend_sketch_for_feature(
    model: Any,
    extension: Any,
    module: Any,
    bend_sketch: Any,
) -> bool:
    """选中折弯草图；优先选草图线段（部分 SW 版本只认线段，不认整张草图）。

    COM 断连一律向上抛，由 ``_create_bend_feature`` 转成
    ``ComDisconnectedBendError``，避免同文档死磕并跳过释放槽重试。
    其它失败返回 False。
    """

    try:
        sketch_name = str(bend_sketch.Name)
    except Exception as error:  # noqa: BLE001
        if _is_com_disconnect_error(error):
            raise
        return False
    try:
        model.ClearSelection2(True)
    except Exception as error:  # noqa: BLE001
        if _is_com_disconnect_error(error):
            raise
        return False
    selected_segment = False
    try:
        sketch = _as_interface(
            module, bend_sketch.GetSpecificFeature2(), "ISketch"
        )
        segments = sketch.GetSketchSegments() or ()
        for index, raw_segment in enumerate(segments):
            segment = _as_interface(module, raw_segment, "ISketchSegment")
            # 第一条替换选择，其后追加。
            if segment.Select4(index > 0, None):
                selected_segment = True
            else:
                # 名称选择回退：Line1@SketchN
                line_name = f"Line{index + 1}@{sketch_name}"
                if extension.SelectByID2(
                    line_name,
                    "EXTSKETCHSEGMENT",
                    0.0,
                    0.0,
                    0.0,
                    index > 0,
                    0,
                    None,
                    0,
                ):
                    selected_segment = True
    except Exception as error:  # noqa: BLE001
        if _is_com_disconnect_error(error):
            raise
        selected_segment = False
    if selected_segment:
        return True
    try:
        return bool(
            extension.SelectByID2(
                sketch_name,
                "SKETCH",
                0.0,
                0.0,
                0.0,
                False,
                0,
                None,
                0,
            )
        )
    except Exception as error:  # noqa: BLE001
        if _is_com_disconnect_error(error):
            raise
        return False


def _try_insert_sheet_metal_bend(
    model: Any,
    feature_manager: Any,
    extension: Any,
    module: Any,
    bend_sketch: Any,
    sketch_face: Any,
    pick_point: tuple[float, float, float],
    angle_rad: float,
    radius_m: float,
    flip: bool,
    bend_pos: int,
    use_default_radius: bool,
    custom_bend: Any | None,
    *, diagnostic: dict | None = None,
) -> bool:
    """选草图+固定面并 InsertSheetMetal3dBend；成功重建返回 True。

    COM 断连向上抛；普通失败返回 False，供参数组合继续试。
    """

    trace = {} if diagnostic is None else diagnostic
    trace.update(stage="select_sketch", status="failed")
    try:
        if not _select_bend_sketch_for_feature(model, extension, module, bend_sketch):
            return False
        trace["stage"] = "select_fixed_face"
        picked = extension.SelectByID2(
            "",
            "FACE",
            pick_point[0],
            pick_point[1],
            pick_point[2],
            True,
            0,
            None,
            0,
        )
        if not picked:
            picked = _as_interface(module, sketch_face, "IEntity").Select4(True, None)
        if not picked:
            return False
        def _do_insert():
            return feature_manager.InsertSheetMetal3dBend(
                angle_rad,
                use_default_radius,
                0.0 if use_default_radius else radius_m,
                flip,
                bend_pos,
                custom_bend,
            )

        trace["stage"] = "insert"
        bend_feature = _call_with_sw_watchdog(
            BEND_INSERT_TIMEOUT_SEC, _do_insert
        )
        if bend_feature is None:
            trace["reason"] = "native_insert_returned_none"
            return False
        bend_feature = _as_interface(module, bend_feature, "IFeature")
        type_name = bend_feature.GetTypeName2()
        trace["feature_type"] = str(type_name)
        try:
            trace["native_error"] = bend_feature.GetErrorCode2()
        except Exception as error:
            if _is_com_disconnect_error(error):
                raise
            trace["native_error_unavailable"] = type(error).__name__
        if type_name != "SM3dBend":
            _delete_model_item(model, bend_feature.Name, "BODYFEATURE")
            return False
        trace["stage"] = "rebuild"
        if not _com_read(model, "EditRebuild3"):
            _delete_model_item(model, bend_feature.Name, "BODYFEATURE")
            return False
        trace.update(stage="complete", status="created")
        return True
    except _SwWatchdogTimeout:
        trace.update(status="timed_out", error_kind="SwWatchdogTimeout")
        raise
    except Exception as error:  # noqa: BLE001
        trace["error_kind"] = type(error).__name__
        if _is_com_disconnect_error(error):
            raise
        return False


class NativeSketchTransformError(SolidWorksGenerationError):
    """Native math disagreed: abort this job without relief retries."""


def _native_point_array(point):
    """Explicit SAFEARRAY(double); tuple VARIANT arrays can fail in SW2022."""
    values = tuple(float(v) for v in point)
    if len(values) != 3 or not all(math.isfinite(v) for v in values):
        raise NativeSketchTransformError("invalid native point array")
    import pythoncom
    from win32com.client import VARIANT
    return VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, values)


def _verified_bend_sketch_point(module, transform_object, point):
    """Use SW's native math as the oracle before writing any bend sketch line."""
    lease = require_model_write()
    binding = getattr(lease, "native_launch", None)
    if binding is None:
        raise SessionOwnershipError("native transform verification requires owned launch")
    utility = _as_interface(module, _com_read(binding.app, "GetMathUtility"), "IMathUtility")
    native_point = _as_interface(module, utility.CreatePoint(_native_point_array(point)), "IMathPoint")
    projected = _as_interface(module, native_point.MultiplyTransform(transform_object), "IMathPoint")
    actual = tuple(float(v) for v in _com_read(projected, "ArrayData"))
    expected = _transform_to_sketch(_com_read(transform_object, "ArrayData"), point)
    if len(actual) != 3 or not all(math.isfinite(v) for v in actual):
        raise NativeSketchTransformError("native sketch transform returned invalid coordinates")
    if math.dist(expected, actual[:2]) > 1e-8 or abs(actual[2]) > 1e-8:
        raise NativeSketchTransformError("native sketch transform mismatch or point off sketch plane")
    return actual[:2]


def _create_bend_sketch_on_face(
    model: Any,
    sketch_manager: Any,
    extension: Any,
    module: Any,
    analysis: DrawingAnalysis,
    bend_indices: tuple[int, ...],
    origin: tuple[float, float],
    thickness_mm: float,
    outer_profile: Primitive,
    sketch_face: Any,
    seed_xy: tuple[float, float],
) -> tuple[Any, tuple[float, float, float]] | None:
    """在指定平面上画折弯特征草图。线会穿出板边，识别长度不在这里改。"""

    face_z = _fixed_panel_plane_z(sketch_face, module)
    pick_point = (
        (seed_xy[0] - origin[0]) / 1000.0,
        (seed_xy[1] - origin[1]) / 1000.0,
        face_z,
    )
    model.ClearSelection2(True)
    if not _as_interface(module, sketch_face, "IEntity").Select4(False, None):
        if not extension.SelectByID2(
            "",
            "FACE",
            pick_point[0],
            pick_point[1],
            pick_point[2],
            False,
            0,
            None,
            0,
        ):
            return None
    known_profile_sketches = {
        feature.Name
        for feature in _features(model, module)
        if feature.GetTypeName2() == "ProfileFeature"
    }
    sketch_manager.InsertSketch(True)
    active_sketch = _as_interface(module, sketch_manager.ActiveSketch, "ISketch")
    transform_object = _as_interface(
        module,
        active_sketch.ModelToSketchTransform,
        "IMathTransform",
    )
    transform = _com_read(transform_object, "ArrayData")
    previous_add_to_db = sketch_manager.AddToDB
    sketch_manager.AddToDB = True
    drawn: list[tuple[tuple[float, float], tuple[float, float]]] = []
    try:
        for bend_index in collapse_collinear_bend_indices(analysis, bend_indices):
            bend = analysis.bend_lines[bend_index]
            if math.dist(bend.points[0], bend.points[-1]) <= 1e-7:
                raise ValueError(f"第 {bend_index + 1} 条折弯线长度为零。")
            feature_start, feature_end = _bend_feature_segment(
                bend, outer_profile, thickness_mm
            )
            span = (feature_start, feature_end)
            if any(_same_feature_span(span, previous) for previous in drawn):
                continue
            drawn.append(span)
            model_start = (
                (feature_start[0] - origin[0]) / 1000.0,
                (feature_start[1] - origin[1]) / 1000.0,
                face_z,
            )
            model_end = (
                (feature_end[0] - origin[0]) / 1000.0,
                (feature_end[1] - origin[1]) / 1000.0,
                face_z,
            )
            sketch_start = _verified_bend_sketch_point(module, transform_object, model_start)
            sketch_end = _verified_bend_sketch_point(module, transform_object, model_end)
            logger.info("Bend sketch coordinates: bend=%d transform=%s model=%s->%s sketch=%s->%s",
                        bend_index + 1, tuple(transform), model_start, model_end, sketch_start, sketch_end)
            sketch_manager.CreateLine(
                sketch_start[0],
                sketch_start[1],
                0.0,
                sketch_end[0],
                sketch_end[1],
                0.0,
            )
    finally:
        sketch_manager.AddToDB = previous_add_to_db
    model.ClearSelection2(True)
    sketch_manager.InsertSketch(True)
    bend_sketch = _latest_profile_sketch(model, module, known_profile_sketches)
    if bend_sketch is None:
        return None
    return bend_sketch, pick_point


def _create_bend_feature(
    model: Any,
    part: Any,
    feature_manager: Any,
    sketch_manager: Any,
    extension: Any,
    module: Any,
    analysis: DrawingAnalysis,
    bend_indices: tuple[int, ...],
    origin: tuple[float, float],
    thickness_mm: float,
    radius_mm: float,
    angle_degrees: float,
    flip_direction: bool,
    fixed_face_point: tuple[float, float] | None = None,
    relief_step: int = 0,
    bend_allowance: BendAllowanceSpec | None = None,
    outer_profile: Primitive | None = None,
    diagnostic_events: list[dict] | None = None,
) -> None:
    """创建草图折弯；多策略重试（同草图多线 / 位置枚举 / 反向 / 固定面候选）。"""

    if outer_profile is None:
        closed_profiles = [
            primitive
            for primitive in analysis.profiles
            if primitive.closed and not primitive.is_bend
        ]
        if not closed_profiles:
            raise SolidWorksGenerationError("没有可用于延长折弯线的外轮廓。")
        outer_profile = max(
            closed_profiles,
            key=lambda item: (primitive_bounds(item)[2] - primitive_bounds(item)[0])
            * (primitive_bounds(item)[3] - primitive_bounds(item)[1]),
        )

    bend_primitives = tuple(analysis.bend_lines[index] for index in bend_indices)
    pick_candidates = _fixed_face_pick_candidates(
        outer_profile, bend_primitives, preferred=fixed_face_point
    )

    planar_faces = _fixed_panel_faces(
        _planar_faces_by_area(part, module), pick_candidates[0], origin, thickness_mm, module=module)
    if not planar_faces:
        raise BendRejectedError(bend_indices, relief_step=relief_step)

    # 写死：折弯位置仅 BendCenterline=1，禁止再试其它 BendPos。
    position_candidates = (
        SW_BEND_POSITION_BEND_CENTERLINE,
    )
    flip_candidates = (flip_direction,)
    allowance_candidates: tuple[Any | None, ...] = (
        _build_custom_bend_allowance(feature_manager, bend_allowance, module),
    )
    pick_candidates = pick_candidates[:2]

    radius_m = radius_mm / 1000.0
    angle_rad = math.radians(angle_degrees)
    last_error: Exception | None = None
    global _auto_bend_deadline
    local_deadline = time.monotonic() + min(20.0, AUTO_BEND_WALL_TIMEOUT_SEC)
    if _auto_bend_deadline is not None:
        local_deadline = min(local_deadline, _auto_bend_deadline)
    deadline = local_deadline
    insert_attempts = 0

    def _bend_time_up() -> bool:
        return time.monotonic() >= deadline

    # Only verified fixed-panel skins, not the largest folded flanges.
    # At most 2 faces; each sketch once; few insert tries.
    for face_index, sketch_face in enumerate(planar_faces[:2]):
        if _bend_time_up():
            logger.warning(
                "auto-bend wall timeout before face loop: relief_step=%d",
                relief_step,
            )
            raise BendRejectedError(bend_indices, relief_step=relief_step)
        seed_xy = pick_candidates[0]
        try:
            created = _create_bend_sketch_on_face(
                model,
                sketch_manager,
                extension,
                module,
                analysis,
                bend_indices,
                origin,
                thickness_mm,
                outer_profile,
                sketch_face,
                seed_xy,
            )
        except (NativeSketchTransformError, SessionOwnershipError):
            raise
        except Exception as error:  # noqa: BLE001
            if _is_com_disconnect_error(error):
                logger.warning(
                    "创建折弯草图时 COM 断连：bends=%s relief_step=%d err=%s",
                    tuple(index + 1 for index in bend_indices),
                    relief_step,
                    error,
                )
                raise ComDisconnectedBendError(
                    bend_indices,
                    relief_step=relief_step,
                ) from error
            last_error = error
            continue
        if created is None:
            last_error = SolidWorksGenerationError("SolidWorks 没有创建折弯线草图。")
            continue
        bend_sketch, _ = created
        try:
            cached_sketch_name = str(bend_sketch.Name)
        except Exception as error:  # noqa: BLE001 - COM 断连
            logger.warning("无法缓存折弯草图名称：%s", error)
            last_error = SolidWorksGenerationError(
                f"SolidWorks 折弯草图 COM 已断开：{error}"
            )
            continue
        try:
            face_z = _fixed_panel_plane_z(sketch_face, module)
        except Exception as error:  # noqa: BLE001
            logger.warning("读取折弯草图面失败：%s", error)
            _delete_model_item(model, cached_sketch_name, "SKETCH")
            last_error = SolidWorksGenerationError(
                f"SolidWorks 折弯面 COM 已断开：{error}"
            )
            continue

        succeeded = False
        for seed_xy in pick_candidates:
            pick_point = (
                (seed_xy[0] - origin[0]) / 1000.0,
                (seed_xy[1] - origin[1]) / 1000.0,
                face_z,
            )
            # Prefer explicit radius only (one mode) to cut hang risk
            for use_default_radius in (False,):
                for bend_pos in position_candidates:
                    for flip in flip_candidates:
                        for custom_bend in allowance_candidates:
                            if _bend_time_up() or insert_attempts >= AUTO_BEND_MAX_INSERT_ATTEMPTS:
                                logger.warning(
                                    "auto-bend giving up: time_up=%s attempts=%d/%d relief_step=%d",
                                    _bend_time_up(),
                                    insert_attempts,
                                    AUTO_BEND_MAX_INSERT_ATTEMPTS,
                                    relief_step,
                                )
                                raise BendRejectedError(
                                    bend_indices, relief_step=relief_step
                                )
                            insert_attempts += 1
                            logger.info(
                                "InsertSheetMetal3dBend try #%d face=%d pos=%s flip=%s",
                                insert_attempts,
                                face_index,
                                bend_pos,
                                flip,
                            )
                            try:
                                detail = dict(face_index=face_index, pick_m=list(pick_point),
                                              bend_indices=list(bend_indices), index_base=0)
                                if diagnostic_events is not None:
                                    diagnostic_events.append(detail)
                                ok = _try_insert_sheet_metal_bend(
                                    model,
                                    feature_manager,
                                    extension,
                                    module,
                                    bend_sketch,
                                    sketch_face,
                                    pick_point,
                                    angle_rad,
                                    radius_m,
                                    flip,
                                    bend_pos,
                                    use_default_radius,
                                    custom_bend,
                                    diagnostic=detail,
                                )
                            except _SwWatchdogTimeout as error:
                                logger.error(
                                    "bend insert watchdog timeout; SolidWorks was not "
                                    "force-killed: bends=%s relief_step=%d",
                                    tuple(index + 1 for index in bend_indices),
                                    relief_step,
                                )
                                raise ComDisconnectedBendError(
                                    bend_indices,
                                    relief_step=relief_step,
                                    timed_out=True,
                                ) from error
                            except Exception as error:  # noqa: BLE001
                                if _is_com_disconnect_error(error):
                                    logger.warning(
                                        "折弯插入时 COM 断连，中止本档文档："
                                        "bends=%s relief_step=%d err=%s",
                                        tuple(index + 1 for index in bend_indices),
                                        relief_step,
                                        error,
                                    )
                                    raise ComDisconnectedBendError(
                                        bend_indices,
                                        relief_step=relief_step,
                                    ) from error
                                ok = False
                            if not ok:
                                continue
                            logger.info(
                                "自动折弯成功：bends=%s face=%d pos=%s flip=%s "
                                "defaultR=%s cba=%s pick=(%.3f,%.3f)",
                                tuple(index + 1 for index in bend_indices),
                                face_index,
                                bend_pos,
                                flip,
                                use_default_radius,
                                custom_bend is not None,
                                seed_xy[0],
                                seed_xy[1],
                            )
                            succeeded = True
                            break
                        if succeeded:
                            break
                    if succeeded:
                        break
                if succeeded:
                    break
            if succeeded:
                break

        if succeeded:
            return

        # 该草图所有参数都失败：删掉无用草图再换面（用缓存名，避免 COM 断连裸抛）。
        _delete_model_item(model, cached_sketch_name, "SKETCH")
        last_error = SolidWorksGenerationError(
            f"面 {face_index} 上 InsertSheetMetal3dBend 全部参数组合失败。"
        )

    if last_error is not None:
        logger.warning("自动折弯全部策略失败，最后错误：%s", last_error)
    raise BendRejectedError(
        bend_indices,
        relief_step=relief_step,
    )


def _bends_are_roughly_parallel(
    first: Primitive,
    second: Primitive,
    *,
    angle_tol_deg: float = 12.0,
) -> bool:
    dx1 = first.points[-1][0] - first.points[0][0]
    dy1 = first.points[-1][1] - first.points[0][1]
    dx2 = second.points[-1][0] - second.points[0][0]
    dy2 = second.points[-1][1] - second.points[0][1]
    len1 = math.hypot(dx1, dy1)
    len2 = math.hypot(dx2, dy2)
    if len1 <= 1e-12 or len2 <= 1e-12:
        return False
    cos_abs = abs((dx1 * dx2 + dy1 * dy2) / (len1 * len2))
    cos_abs = min(1.0, cos_abs)
    return math.degrees(math.acos(cos_abs)) <= angle_tol_deg


def _bends_are_collinear(
    first: Primitive,
    second: Primitive,
    *,
    distance_tol_mm: float = 1.0,
) -> bool:
    """两条折弯线落在同一条直线上。SolidWorks 同草图里放两条共线折弯会报错。"""

    if not _bends_are_roughly_parallel(first, second, angle_tol_deg=3.0):
        return False
    start, end = first.points[0], first.points[-1]
    length = math.hypot(end[0] - start[0], end[1] - start[1])
    if length <= 1e-9:
        return False

    def _offset(point: tuple[float, float]) -> float:
        return abs(
            (point[0] - start[0]) * (end[1] - start[1])
            - (point[1] - start[1]) * (end[0] - start[0])
        ) / length

    return all(_offset(point) <= distance_tol_mm for point in (second.points[0], second.points[-1]))


def collapse_collinear_bend_indices(
    analysis: DrawingAnalysis,
    bend_indices: tuple[int, ...],
) -> tuple[int, ...]:
    """共线的折弯线只留第一条进折弯特征草图。识别结果本身不合并、不接长。"""

    kept: list[int] = []
    for index in bend_indices:
        bend = analysis.bend_lines[index]
        if any(
            _bends_are_collinear(bend, analysis.bend_lines[previous])
            for previous in kept
        ):
            continue
        kept.append(index)
    return tuple(kept)


def _partition_bend_groups(
    analysis: DrawingAnalysis,
    bend_indices: tuple[int, ...],
) -> list[tuple[int, ...]]:
    """把折弯线分成「近似平行」组：同组可共草图一次折，交叉组再分批。"""

    remaining = list(bend_indices)
    groups: list[tuple[int, ...]] = []
    while remaining:
        seed = remaining.pop(0)
        group = [seed]
        still: list[int] = []
        for index in remaining:
            if _bends_are_roughly_parallel(
                analysis.bend_lines[seed], analysis.bend_lines[index]
            ):
                group.append(index)
            else:
                still.append(index)
        remaining = still
        groups.append(tuple(group))
    return groups


def _create_bends_with_fallbacks(*args, group_attempts=None, **kwargs) -> int:
    """Preserve group evidence even when the scheduler rejects or disconnects."""
    events = [] if group_attempts is None else group_attempts
    try:
        return _create_bends_with_fallbacks_impl(*args, group_attempts=events, **kwargs)
    except BendRejectedError as error:
        error.bend_group_attempts = tuple(dict(event) for event in events)
        raise


def _create_bends_with_fallbacks_impl(
    model: Any,
    part: Any,
    feature_manager: Any,
    sketch_manager: Any,
    extension: Any,
    module: Any,
    analysis: DrawingAnalysis,
    bend_indices: tuple[int, ...],
    origin: tuple[float, float],
    thickness_mm: float,
    radius_mm: float,
    angle_degrees: float,
    flip_direction: bool,
    fixed_face_point: tuple[float, float] | None,
    relief_step: int,
    bend_allowance: BendAllowanceSpec | None,
    outer_profile: Primitive,
    *,
    hole_profiles: tuple[Primitive, ...] = (),
    group_attempts: list[dict] | None = None,
) -> int:
    """自动折弯总调度：先全部同草图，再平行分组，最后逐条（仍在当前最大平面上）。"""

    if not bend_indices:
        return 0

    fixed_face_point = _fixed_face_pick_candidates(
        outer_profile, tuple(analysis.bend_lines[i] for i in bend_indices),
        preferred=fixed_face_point, holes=hole_profiles)[0]
    logger.info("Fixed panel pinned for all bend groups: xy=%s bends=%s",
                fixed_face_point, tuple(i + 1 for i in bend_indices))

    global _auto_bend_deadline
    _auto_bend_deadline = time.monotonic() + AUTO_BEND_WALL_TIMEOUT_SEC
    deadline = _auto_bend_deadline

    def _ensure_time(label: str) -> None:
        if time.monotonic() >= deadline:
            logger.warning(
                "auto-bend wall timeout at %s relief_step=%d",
                label,
                relief_step,
            )
            raise BendRejectedError(bend_indices, relief_step=relief_step)


    def _attempt(indices: tuple[int, ...]) -> None:
        event = dict(sequence=len(group_attempts) + 1 if group_attempts is not None else 1,
                     bend_indices=list(indices), index_base=0,
                     fixed_point_mm=list(fixed_face_point), relief_step=relief_step,
                     status="started", native_attempts=[], scope="feature_creation_not_native_acceptance")
        if group_attempts is not None:
            group_attempts.append(event)
        started = time.monotonic()
        try:
            _ensure_time("attempt")
            _create_bend_feature(
                model,
                part,
                feature_manager,
                sketch_manager,
                extension,
                module,
                analysis,
                indices,
                origin,
                thickness_mm,
                radius_mm,
                angle_degrees,
                flip_direction,
                fixed_face_point,
                relief_step,
                bend_allowance=bend_allowance,
                outer_profile=outer_profile,
                diagnostic_events=event["native_attempts"],
            )
        except Exception as error:
            event.update(status="failed", error_kind=type(error).__name__)
            raise
        else:
            event["status"] = "created"
        finally:
            event["elapsed_seconds"] = max(0.0, time.monotonic() - started)


    # 先全部同草图。失败且还没到总时限时，改平行分组，再逐条。
    # 一条坏线不再把其余折弯一起判死。超时仍立刻交给外层回退平板。
    try:
        _ensure_time("all-bends")
        _attempt(bend_indices)
        return len(bend_indices)
    except ComDisconnectedBendError:
        raise
    except BendRejectedError as error:
        if len(bend_indices) <= 1 or time.monotonic() >= deadline:
            logger.warning(
                "auto-bend rejected bends=%s relief_step=%d; defer to relief/flat",
                tuple(index + 1 for index in error.bend_indices),
                relief_step,
            )
            raise
        logger.warning(
            "同草图一次折弯失败 bends=%s，改为平行分组再逐条",
            tuple(index + 1 for index in bend_indices),
        )
        groups = _partition_bend_groups(analysis, bend_indices)
        pending: list[int] = []
        if len(groups) > 1:
            for group in groups:
                if time.monotonic() >= deadline:
                    raise BendRejectedError(bend_indices, relief_step=relief_step)
                if len(group) == 1:
                    pending.append(group[0])
                    continue
                try:
                    _attempt(group)
                except ComDisconnectedBendError:
                    raise
                except BendRejectedError:
                    pending.extend(group)
        else:
            pending = list(bend_indices)
        failed: list[int] = []
        for position, index in enumerate(pending):
            if time.monotonic() >= deadline:
                failed.extend(pending[position:])
                break
            try:
                _attempt((index,))
            except ComDisconnectedBendError:
                raise
            except BendRejectedError:
                failed.append(index)
        if not failed:
            return len(bend_indices)
        if len(failed) >= len(bend_indices):
            raise BendRejectedError(tuple(failed), relief_step=relief_step)
        # Partial success is still a rejected automatic attempt. Throw away
        # this unsaved task document before retrying deeper relief from source.
        error = BendRejectedError(tuple(failed), relief_step=relief_step)
        error.completed_bend_count = len(bend_indices) - len(failed)
        raise error


def _closed_points(profile: Primitive) -> tuple[tuple[float, float], ...]:
    points = list(profile.points)
    if len(points) > 1 and math.dist(points[0], points[-1]) <= 1e-7:
        points.pop()
    if len(points) < 3 or len(set(points)) < 3:
        raise ValueError("所选轮廓至少需要三个不同的顶点。")
    return tuple(points)


def _circle_parameters(
    points: tuple[tuple[float, float], ...],
) -> tuple[tuple[float, float], float]:
    center = (
        sum(point[0] for point in points) / len(points),
        sum(point[1] for point in points) / len(points),
    )
    radius = sum(math.dist(center, point) for point in points) / len(points)
    if radius <= 1e-9:
        raise ValueError("圆形轮廓半径为零。")
    return center, radius


def _transform_to_sketch(
    transform: tuple[float, ...] | list[float],
    point: tuple[float, float, float],
) -> tuple[float, float]:
    """Apply SW's row-vector rotation, uniform scale, then translation.

    ArrayData stores three rotation rows, translation at 9:12 and scale at
    12. Using contiguous rows as output dot products transposes the rotation:
    identity/reflection tests hide that error, a rotated sketch does not.
    """
    if len(transform) < 13:
        raise ValueError("SolidWorks transform requires rotation, translation and scale")
    values = tuple(float(v) for v in transform[:13])
    if not all(math.isfinite(v) for v in (*values, *point)) or values[12] == 0:
        raise ValueError("SolidWorks transform/point is non-finite or singular")
    x, y, z = point
    scale = values[12]
    return (
        scale * (values[0]*x + values[3]*y + values[6]*z) + values[9],
        scale * (values[1]*x + values[4]*y + values[7]*z) + values[10],
    )


def _arc_direction(sweep_angle: float, orientation: float = 1.0) -> int:
    if abs(sweep_angle) <= 1e-10 or abs(orientation) <= 1e-10:
        raise ValueError("圆弧方向或草图变换无效。")
    if sweep_angle * orientation > 0:
        return SW_ARC_DIRECTION_COUNTERCLOCKWISE
    return SW_ARC_DIRECTION_CLOCKWISE


def _create_sketch(
    sketch_manager: Any,
    points: Iterable[tuple[float, float]],
    origin: tuple[float, float],
    *,
    closed: bool,
    kind: str = "",
    curve_segments: Iterable[SketchSegment] = (),
    circle_center: tuple[float, float] | None = None,
    circle_radius: float | None = None,
) -> None:
    previous_add_to_db = sketch_manager.AddToDB
    sketch_manager.AddToDB = True
    try:
        _create_sketch_geometry(
            sketch_manager,
            points,
            origin,
            closed=closed,
            kind=kind,
            curve_segments=curve_segments,
            circle_center=circle_center,
            circle_radius=circle_radius,
        )
    finally:
        sketch_manager.AddToDB = previous_add_to_db


def _create_sketch_geometry(
    sketch_manager: Any,
    points: Iterable[tuple[float, float]],
    origin: tuple[float, float],
    *,
    closed: bool,
    kind: str = "",
    curve_segments: Iterable[SketchSegment] = (),
    circle_center: tuple[float, float] | None = None,
    circle_radius: float | None = None,
) -> None:
    source_points = tuple(points)
    if closed and kind == "CIRCLE":
        center, radius = (
            (circle_center, circle_radius)
            if circle_center is not None and circle_radius is not None
            else _circle_parameters(source_points)
        )
        sketch_manager.CreateCircleByRadius(
            (center[0] - origin[0]) / 1000.0,
            (center[1] - origin[1]) / 1000.0,
            0.0,
            radius / 1000.0,
        )
        return
    exact_segments = tuple(curve_segments)
    if not exact_segments:
        pairs = (
            zip(source_points, source_points[1:] + source_points[:1])
            if closed
            else zip(source_points, source_points[1:])
        )
        exact_segments = tuple(
            SketchSegment(start, end)
            for start, end in pairs
        )
    for segment in exact_segments:
        start = (
            (segment.start[0] - origin[0]) / 1000.0,
            (segment.start[1] - origin[1]) / 1000.0,
        )
        end = (
            (segment.end[0] - origin[0]) / 1000.0,
            (segment.end[1] - origin[1]) / 1000.0,
        )
        if math.dist(start, end) <= 1e-10:
            continue
        if segment.center is None or abs(segment.sweep_angle) <= 1e-10:
            sketch_manager.CreateLine(start[0], start[1], 0.0, end[0], end[1], 0.0)
            continue
        center = (
            (segment.center[0] - origin[0]) / 1000.0,
            (segment.center[1] - origin[1]) / 1000.0,
        )
        sketch_manager.CreateArc(
            center[0],
            center[1],
            0.0,
            start[0],
            start[1],
            0.0,
            end[0],
            end[1],
            0.0,
            _arc_direction(segment.sweep_angle),
        )


# 只让折弯特征草图穿出板边。识别结果和「折弯线_手折参考」仍用原长。
BEND_FEATURE_PIERCE_MM = 1.0


def _extended_bend_segment(
    bend: Primitive,
    outer_profile: Primitive,
    thickness_mm: float,
) -> tuple[tuple[float, float], tuple[float, float]]:
    """原样返回折弯线端点。识别和手折参考草图不延长。"""

    del outer_profile, thickness_mm
    start, end = bend.points[0], bend.points[-1]
    if math.dist(start, end) <= 1e-7:
        raise ValueError("折弯线长度为零。")
    return start, end


def _bend_feature_segment(
    bend: Primitive,
    outer_profile: Primitive,
    thickness_mm: float,
) -> tuple[tuple[float, float], tuple[float, float]]:
    """折弯特征草图用的线段：沿原方向穿出外轮廓一点点。

    SolidWorks 草图折弯要求折弯线穿过板面。图上的红线往往只是短标记，
    原长放进特征草图时折弯会被拒绝。这里只在特征草图里延伸到轮廓交点，
    每端再探出约 1mm，不改识别结果，也不把线无限拉长。
    """

    start, end = _extended_bend_segment(bend, outer_profile, thickness_mm)
    span = _bend_feature_outline_span(bend, outer_profile)
    if span is None:
        return start, end
    hits = span
    length = math.dist(start, end)
    unit_x = (end[0] - start[0]) / length
    unit_y = (end[1] - start[1]) / length
    hit_a, hit_b = hits[0], hits[1]
    if (hit_b[0] - hit_a[0]) * unit_x + (hit_b[1] - hit_a[1]) * unit_y < 0:
        hit_a, hit_b = hit_b, hit_a
    pierce = max(BEND_FEATURE_PIERCE_MM, 0.25 * thickness_mm)
    return (
        (hit_a[0] - unit_x * pierce, hit_a[1] - unit_y * pierce),
        (hit_b[0] + unit_x * pierce, hit_b[1] + unit_y * pierce),
    )


def _same_feature_span(
    first: tuple[tuple[float, float], tuple[float, float]],
    second: tuple[tuple[float, float], tuple[float, float]],
    tolerance: float = 0.3,
) -> bool:
    a0, a1 = first
    b0, b1 = second
    forward = math.dist(a0, b0) <= tolerance and math.dist(a1, b1) <= tolerance
    reverse = math.dist(a0, b1) <= tolerance and math.dist(a1, b0) <= tolerance
    return forward or reverse


def _create_bend_reference_sketch(
    model: Any,
    part: Any,
    sketch_manager: Any,
    extension: Any,
    module: Any,
    analysis: DrawingAnalysis,
    bend_indices: tuple[int, ...],
    origin: tuple[float, float],
    thickness_mm: float,
    outer_profile: Primitive,
    fixed_face_point: tuple[float, float] | None = None,
) -> tuple[str, int]:
    """在钣金大面上画出折弯线参考草图，方便在 SolidWorks 里手动画「草图折弯」。

    返回 (草图名, 草图中实际直线数)。草图保持显示，不隐藏、不删除。
    """

    body = _as_interface(
        module,
        part.GetBodies2(SW_BODY_TYPE_SOLID, False)[0],
        "IBody2",
    )
    faces = [
        _as_interface(module, raw_face, "IFace2")
        for raw_face in body.GetFaces()
    ]
    fixed_face = max(faces, key=lambda face: face.GetArea())
    face_box = fixed_face.GetBox()
    fixed_point = (
        (face_box[0] + face_box[3]) / 2,
        (face_box[1] + face_box[4]) / 2,
        (face_box[2] + face_box[5]) / 2,
    )
    pick_point = fixed_point
    if fixed_face_point is not None:
        pick_point = (
            (fixed_face_point[0] - origin[0]) / 1000.0,
            (fixed_face_point[1] - origin[1]) / 1000.0,
            (face_box[2] + face_box[5]) / 2.0,
        )
        if not extension.SelectByID2(
            "",
            "FACE",
            pick_point[0],
            pick_point[1],
            pick_point[2],
            False,
            0,
            None,
            0,
        ):
            _as_interface(module, fixed_face, "IEntity").Select4(False, None)
    else:
        _as_interface(module, fixed_face, "IEntity").Select4(False, None)

    known_profile_sketches = {
        feature.Name
        for feature in _features(model, module)
        if feature.GetTypeName2() == "ProfileFeature"
    }
    sketch_manager.InsertSketch(True)
    active_sketch = _as_interface(module, sketch_manager.ActiveSketch, "ISketch")
    transform = _as_interface(
        module,
        active_sketch.ModelToSketchTransform,
        "IMathTransform",
    ).ArrayData
    previous_add_to_db = sketch_manager.AddToDB
    sketch_manager.AddToDB = True
    try:
        for bend_index in bend_indices:
            bend = analysis.bend_lines[bend_index]
            extended_start, extended_end = _extended_bend_segment(
                bend, outer_profile, thickness_mm
            )
            model_start = (
                (extended_start[0] - origin[0]) / 1000.0,
                (extended_start[1] - origin[1]) / 1000.0,
                fixed_point[2],
            )
            model_end = (
                (extended_end[0] - origin[0]) / 1000.0,
                (extended_end[1] - origin[1]) / 1000.0,
                fixed_point[2],
            )
            sketch_start = _transform_to_sketch(transform, model_start)
            sketch_end = _transform_to_sketch(transform, model_end)
            sketch_manager.CreateLine(
                sketch_start[0],
                sketch_start[1],
                0.0,
                sketch_end[0],
                sketch_end[1],
                0.0,
            )
    finally:
        sketch_manager.AddToDB = previous_add_to_db
    model.ClearSelection2(True)
    sketch_manager.InsertSketch(True)
    sketch_feature = _latest_profile_sketch(model, module, known_profile_sketches)
    if sketch_feature is None:
        raise SolidWorksGenerationError("未能创建折弯线参考草图。")
    try:
        sketch_feature.Name = "折弯线_手折参考"
    except Exception:  # noqa: BLE001 - 名称冲突时保留默认名
        pass
    line_count = -1
    try:
        raw_sketch = sketch_feature.GetSpecificFeature2()
        try:
            sketch = _as_interface(module, raw_sketch, "ISketch")
        except Exception:  # noqa: BLE001 - 原始 PyIDispatch 无 _oleobj_
            sketch = getattr(module, "ISketch")(raw_sketch)
        segments = sketch.GetSketchSegments() or ()
        line_count = len(segments)
    except Exception:  # noqa: BLE001 - 读不到时仅记录
        logger.warning("无法读取折弯线参考草图的线段数。")
    try:
        sketch_feature.SetSuppression2(1, 2, None)  # 确保未压缩
    except Exception:  # noqa: BLE001
        pass
    try:
        model.Extension.SelectByID2(
            str(sketch_feature.Name), "SKETCH", 0, 0, 0, False, 0, None, 0
        )
        model.UnblankSketch()  # 确保显示
        model.ClearSelection2(True)
    except Exception:  # noqa: BLE001
        pass
    logger.info(
        "已创建折弯线参考草图：%s（识别 %d 条，草图实有 %d 条）",
        sketch_feature.Name,
        len(bend_indices),
        line_count,
    )
    if line_count >= 0 and line_count != len(bend_indices):
        logger.warning(
            "折弯线参考草图线数 %d 与识别数 %d 不一致！", line_count, len(bend_indices)
        )
    return str(sketch_feature.Name), line_count


def _import_cad_sketch(
    typed_solidworks: Any,
    model: Any,
    feature_manager: Any,
    type_library: Any,
    plane: Any,
    dxf_path: Path,
) -> Any | None:
    """IFeatureManager.InsertDwgOrDxfFile2：把临时 DXF 原样导入到基准面草图。"""

    model.ClearSelection2(True)
    if not _as_interface(type_library, plane, "IEntity").Select4(False, None):
        return None
    data = typed_solidworks.GetImportFileData(str(dxf_path))
    if data is None:
        return None
    import_data = _as_interface(type_library, data, "IImportDxfDwgData")
    for setter, args in (
        ("SetImportMethod", ("", SW_IMPORT_DXFDWG_TO_EXISTING_PART)),
        ("SetLengthUnit", ("", SW_LENGTH_UNIT_MM)),
    ):
        try:
            getattr(import_data, setter)(*args)
        except Exception as error:  # noqa: BLE001
            logger.debug("ImportDxfDwgData.%s 失败：%s", setter, error)
    feature = feature_manager.InsertDwgOrDxfFile2(str(dxf_path), import_data)
    model.ClearSelection2(True)
    if feature is None:
        return None
    return _as_interface(type_library, feature, "IFeature")


def _base_flange_from_cad_import(
    typed_solidworks: Any,
    model: Any,
    feature_manager: Any,
    extension: Any,
    type_library: Any,
    plane: Any,
    analysis: DrawingAnalysis,
    profile_index: int,
    hole_indices: Iterable[int],
    profile_before: Primitive,
    holes_before: tuple[tuple[Primitive, tuple[tuple[float, float], ...]], ...],
    profile_after: Primitive,
    holes_after: tuple[tuple[Primitive, tuple[tuple[float, float], ...]], ...],
    origin: tuple[float, float],
    output: Path,
    relief_step: int,
    rect_relief_count: int,
    thickness_m: float,
    radius_m: float,
    bend_allowance: BendAllowanceSpec | None = None,
) -> Any | None:
    """抽所选件原始图元→临时 DXF→SW 导入草图→基体法兰（内孔随草图一起成形）。"""

    import cad_import

    started = time.monotonic()
    source_dxf = cad_import.source_dxf_for(analysis.path)
    outline_rings = [analysis.profiles[profile_index].points] + [
        analysis.profiles[index].points for index in hole_indices
    ]
    move_pairs: list[tuple[list, list]] = []
    if relief_step > 0:
        move_pairs.append(
            (_profile_ring_points(profile_before), _profile_ring_points(profile_after))
        )
        for (hole_b, _), (hole_a, _) in zip(holes_before, holes_after):
            if hole_b.points != hole_a.points:
                move_pairs.append(
                    (_profile_ring_points(hole_b), _profile_ring_points(hole_a))
                )
    coverage = [_profile_ring_points(profile_after)] + [
        _profile_ring_points(hole) for hole, _ in holes_after
    ]
    try:
        from paths_local import temp_dxf_dir
        work = temp_dxf_dir()
    except Exception:  # noqa: BLE001
        work = Path(tempfile.gettempdir()) / "cad2sw_part_dxf"
    dxf_path = work / f"{output.stem}_step{relief_step}_{os.getpid()}.dxf"
    info = cad_import.build_part_dxf(
        source_dxf,
        outline_rings,
        origin,
        dxf_path,
        move_pairs=move_pairs,
        coverage_rings=coverage,
    )
    if relief_step > 0 and rect_relief_count and info.moved_endpoints == 0:
        raise ValueError("释放槽扩大未能作用到导入图元（没有端点被移动）。")
    sketch = _import_cad_sketch(
        typed_solidworks, model, feature_manager, type_library, plane, dxf_path
    )
    if sketch is None:
        raise SolidWorksGenerationError("InsertDwgOrDxfFile2 未生成草图。")
    logger.info(
        "CAD 原图已导入草图：%s（直线 %d / 圆弧 %d / 圆 %d，释放槽级别 %d，%.1fs）",
        sketch.Name,
        info.lines,
        info.arcs,
        info.circles,
        relief_step,
        time.monotonic() - started,
    )
    for thicken_dir in (True, False):
        if not _select_sketch_contours(model, extension, type_library, sketch):
            break
        candidate = _try_insert_base_flange(
            feature_manager, thickness_m, radius_m, thicken_dir, bend_allowance, type_library
        )
        if candidate is not None:
            logger.info("基体法兰创建成功：CAD 直接导入 加厚方向=%s", thicken_dir)
            return candidate
    _delete_model_item(model, sketch.Name, "SKETCH")
    raise SolidWorksGenerationError("导入草图无法创建基体法兰。")


def generate_sheet_metal(
    analysis: DrawingAnalysis,
    profile_index: int,
    bend_indices: Iterable[int],
    thickness_mm: float,
    radius_mm: float,
    angle_degrees: float,
    output_path: str | Path,
    *,
    flip_direction: bool = False,
    fixed_face_point: tuple[float, float] | None = None,
    relief_bend_indices: Iterable[int] = (),
    relief_step: int = 0,
    bend_allowance: BendAllowanceSpec | None = None,
    auto_bend: bool = False,
    cad_import: bool | None = None,
    close_saved_document: bool = False,
) -> GenerationResult:
    if not on_task_sta():
        return run_on_task_sta(
            lambda: generate_sheet_metal(
                analysis,
                profile_index,
                bend_indices,
                thickness_mm,
                radius_mm,
                angle_degrees,
                output_path,
                flip_direction=flip_direction,
                fixed_face_point=fixed_face_point,
                relief_bend_indices=relief_bend_indices,
                relief_step=relief_step,
                bend_allowance=bend_allowance,
                auto_bend=auto_bend,
                cad_import=cad_import,
                close_saved_document=close_saved_document,
            ),
            timeout=SW_SESSION_CALL_TIMEOUT_SEC,
            task_name="generate_sheet_metal",
        )
    use_cad_import = resolve_use_cad_import(cad_import)
    if not 0 <= profile_index < len(analysis.profiles):
        raise ValueError("所选轮廓编号无效。")
    if not math.isfinite(thickness_mm) or thickness_mm <= 0:
        raise ValueError("板厚必须是大于 0 的有限数值。")
    if not math.isfinite(radius_mm) or radius_mm <= 0:
        raise ValueError("折弯半径必须是大于 0 的有限数值。")
    if not math.isfinite(angle_degrees) or not 0 < angle_degrees < 180:
        raise ValueError("折弯角度必须大于 0° 且小于 180°。")

    output = Path(output_path).expanduser().resolve()
    if output.suffix.casefold() != ".sldprt":
        raise ValueError("输出文件扩展名必须为 .SLDPRT。")
    if output.exists():
        raise FileExistsError(f"输出文件已存在：{output}")

    # 误选内部孔/槽时，自动升到包住它的最外轮廓再生成。
    resolved_index = outermost_containing_profile_index(
        analysis.profiles,
        profile_index,
    )
    if resolved_index != profile_index:
        logger.warning(
            "所选轮廓 #%d 位于更大外轮廓 #%d 内，已改用外轮廓生成基体法兰",
            profile_index + 1,
            resolved_index + 1,
        )
        profile_index = resolved_index

    profile = analysis.profiles[profile_index]
    if not profile.closed or profile.is_bend:
        raise ValueError("只能选择闭合的非折弯轮廓创建钣金基体。")
    min_edge_mm = max(0.05, min(thickness_mm * 0.05, 0.5))
    profile = sanitize_closed_profile(profile, min_edge_mm=min_edge_mm)
    points = _closed_points(profile)
    hole_indices = contained_hole_indices(analysis.profiles, profile_index)
    hole_profiles_list: list[tuple[Primitive, tuple[tuple[float, float], ...]]] = []
    for index in hole_indices:
        hole = sanitize_closed_profile(
            analysis.profiles[index],
            min_edge_mm=min_edge_mm,
        )
        hole_profiles_list.append((hole, _closed_points(hole)))
    hole_profiles = tuple(hole_profiles_list)
    selected_bends = tuple(dict.fromkeys(int(index) for index in bend_indices))
    if any(index < 0 or index >= len(analysis.bend_lines) for index in selected_bends):
        raise ValueError("所选折弯线编号无效。")
    relief_bends = tuple(
        dict.fromkeys(int(index) for index in relief_bend_indices)
    )
    if any(index not in selected_bends for index in relief_bends):
        raise ValueError("释放槽只能添加到本次选择的折弯线上。")
    if not 0 <= relief_step <= MAX_RELIEF_STEPS:
        raise ValueError(
            f"释放槽自动扩大次数必须在 0 到 {MAX_RELIEF_STEPS} 之间。"
        )

    logger.info(
        "生成钣金零件：图纸=%s 轮廓=#%d 折弯=%d 条 板厚=%.3f 半径=%.3f "
        "角度=%.3f 反向=%s 释放槽级别=%d 输出=%s",
        analysis.path,
        profile_index + 1,
        len(selected_bends),
        thickness_mm,
        radius_mm,
        angle_degrees,
        flip_direction,
        relief_step,
        output,
    )

    min_x, min_y, max_x, max_y = primitive_bounds(profile)
    origin = ((min_x + max_x) / 2, (min_y + max_y) / 2)
    # step0 原槽；交汇处没有槽时补最小矩形槽。BendRejected 后只朝板面加深。
    # 绝不叠加 0.5t 圆孔释放，也不把矩形槽斜切掉。
    relief_cutouts: tuple[ReliefCutout, ...] = ()
    rect_relief_count = 0
    selected_bend_lines = tuple(analysis.bend_lines[index] for index in selected_bends)
    profile, hole_profiles, added_relief = ensure_intersection_reliefs(
        profile,
        hole_profiles,
        selected_bend_lines,
        thickness_mm,
        radius_mm,
        relief_step=relief_step,
    )
    if added_relief:
        logger.info(
            "交汇折弯附近无释放槽，已补直角槽 %d 处（向上、向内各 %.1f mm）",
            added_relief,
            rect_relief_extra_mm(relief_step),
        )
    rect_relief_count = added_relief
    profile_before_relief = profile
    holes_before_relief = hole_profiles
    if relief_step > 0:
        profile, hole_profiles, grown_relief = apply_rectangular_relief_expansion(
            profile,
            hole_profiles,
            relief_step,
            selected_bend_lines,
        )
        rect_relief_count = max(rect_relief_count, grown_relief)
        points = _closed_points(profile)
        min_x, min_y, max_x, max_y = primitive_bounds(profile)
        origin = ((min_x + max_x) / 2, (min_y + max_y) / 2)
        logger.info(
            "矩形释放槽扩大：级别=%d 边长各+%.1fmm 改动=%d",
            relief_step,
            rect_relief_extra_mm(relief_step),
            rect_relief_count,
        )

    profile_after_relief = profile
    try:
        import pythoncom
        import win32com.client
    except ImportError as error:
        raise SolidWorksGenerationError(
            "生成钣金需要 pywin32；请使用配置了 SolidWorks 的 Python 环境运行程序。"
        ) from error

    solidworks: Any = None
    raw_model: Any = None
    document_title: str | None = None
    saved = False
    com_initialized = False
    started_solidworks = False
    typed_solidworks: Any = None
    model = None
    lease = None
    bend_phase = False
    try:
        lease = current_lease()
        pythoncom.CoInitialize()
        com_initialized = True
        solidworks, started_solidworks = _connect_task_solidworks(
            lease, win32com, pythoncom
        )
        logger.info(
            "已连接 SolidWorks（本次由程序激活且尚未证明独占：created_by_task=%s）",
            started_solidworks,
        )
        type_library = ensure_solidworks_typelib()
        typed_solidworks = _as_interface(type_library, solidworks, "ISldWorks")
        if lease is not None:
            lease.note_bound_application(typed_solidworks)
        _set_sw_automation_mode(typed_solidworks, True)
        template_path = typed_solidworks.GetUserPreferenceStringValue(
            SW_DEFAULT_TEMPLATE_PART
        )
        if not template_path or not Path(template_path).is_file():
            raise SolidWorksGenerationError(
                "SolidWorks 的默认零件模板不可用；请在系统选项中设置默认零件模板。"
            )

        require_model_write(lease)
        raw_model = typed_solidworks.NewDocument(template_path, 0, 0.0, 0.0)
        if raw_model is None:
            raise SolidWorksGenerationError("SolidWorks 未能创建新的零件文档。")
        model = _as_interface(type_library, raw_model, "IModelDoc2")
        document_title = str(model.GetTitle())
        if lease is not None:
            lease.note_owned_document(document_title, handle_id=id(raw_model))
        part = _as_interface(type_library, raw_model, "IPartDoc")
        feature_manager = _as_interface(
            type_library, model.FeatureManager, "IFeatureManager"
        )
        sketch_manager = _as_interface(
            type_library, model.SketchManager, "ISketchManager"
        )
        extension = _as_interface(
            type_library, model.Extension, "IModelDocExtension"
        )

        reference_planes = [
            feature
            for feature in _features(model, type_library)
            if feature.GetTypeName2() == "RefPlane"
        ]
        if not reference_planes:
            raise SolidWorksGenerationError("零件模板中没有可用的基准面。")
        span_x, span_y = profile_span_mm(profile)
        # 折线密化的圆角先重拟成单段弧，再交给 CreateArc。
        profile = refit_circular_fillets(profile)
        # 方向 × 圆弧/纯折线：圆弧端点微缝时改折线常能过。
        profile_variants: list[tuple[str, Primitive]] = []
        for label, candidate in (
            ("正向圆弧", profile),
            ("反向圆弧", reverse_closed_profile(profile)),
            ("正向折线", _polyline_only_profile(profile)),
            ("反向折线", _polyline_only_profile(reverse_closed_profile(profile))),
        ):
            profile_variants.append((label, refit_circular_fillets(candidate)))
        base_flange = None
        last_contour_error: Exception | None = None
        thickness_m = thickness_mm / 1000.0
        radius_m = radius_mm / 1000.0
        cad_imported = False
        if use_cad_import:
            try:
                base_flange = _base_flange_from_cad_import(
                    typed_solidworks,
                    model,
                    feature_manager,
                    extension,
                    type_library,
                    reference_planes[-1],
                    analysis,
                    profile_index,
                    hole_indices,
                    profile_before_relief,
                    holes_before_relief,
                    profile_after_relief,
                    hole_profiles,
                    origin,
                    output,
                    relief_step,
                    rect_relief_count,
                    thickness_m,
                    radius_m,
                    bend_allowance,
                )
            except (BendRejectedError, FileExistsError):
                raise
            except Exception as error:  # noqa: BLE001 - 任何导入问题都回退旧路径
                logger.warning("CAD 直接导入失败，回退为程序重画轮廓：%s", error)
                base_flange = None
            cad_imported = base_flange is not None

        def _sketch_closed_profile(attempt_profile: Primitive) -> Any | None:
            attempt_points = _closed_points(attempt_profile)
            attempt_origin = (
                (
                    min(point[0] for point in attempt_points)
                    + max(point[0] for point in attempt_points)
                )
                / 2.0,
                (
                    min(point[1] for point in attempt_points)
                    + max(point[1] for point in attempt_points)
                )
                / 2.0,
            )
            known_before = {
                feature.Name
                for feature in _features(model, type_library)
                if feature.GetTypeName2() == "ProfileFeature"
            }
            model.ClearSelection2(True)
            if not _as_interface(
                type_library, reference_planes[-1], "IEntity"
            ).Select4(False, None):
                return None
            sketch_manager.InsertSketch(True)
            _create_sketch(
                sketch_manager,
                attempt_points,
                attempt_origin,
                closed=True,
                kind=attempt_profile.kind or "LINE_LOOP",
                curve_segments=attempt_profile.curve_segments,
                circle_center=attempt_profile.circle_center,
                circle_radius=attempt_profile.circle_radius,
            )
            model.ClearSelection2(True)
            sketch_manager.InsertSketch(True)
            sketch = _latest_profile_sketch(model, type_library, known_before)
            if sketch is None:
                return None
            return sketch, attempt_points, attempt_origin

        for attempt, (label, attempt_profile) in enumerate(
            profile_variants if base_flange is None else ()
        ):
            sketched = _sketch_closed_profile(attempt_profile)
            if sketched is None:
                last_contour_error = SolidWorksGenerationError(
                    "SolidWorks 没有创建轮廓草图。"
                )
                continue
            profile_sketch, attempt_points, attempt_origin = sketched
            try:
                _validate_single_closed_contour(
                    profile_sketch, attempt_profile, type_library
                )
            except SolidWorksGenerationError as error:
                last_contour_error = error
                logger.warning(
                    "基体草图校验失败（%s）：%s", label, error
                )
                _delete_model_item(model, profile_sketch.Name, "SKETCH")
                continue
            if not _select_sketch_contours(
                model, extension, type_library, profile_sketch
            ):
                last_contour_error = SolidWorksGenerationError(
                    "SolidWorks 未能选中基体法兰轮廓草图。"
                )
                _delete_model_item(model, profile_sketch.Name, "SKETCH")
                continue
            for thicken_dir in (True, False):
                if not _select_sketch_contours(
                    model, extension, type_library, profile_sketch
                ):
                    break
                candidate = _try_insert_base_flange(
                    feature_manager,
                    thickness_m,
                    radius_m,
                    thicken_dir,
                    bend_allowance,
                    type_library,
                )
                if candidate is not None:
                    base_flange = candidate
                    profile = attempt_profile
                    points = attempt_points
                    origin = attempt_origin
                    logger.info(
                        "基体法兰创建成功：尝试=%s 加厚方向=%s",
                        label,
                        thicken_dir,
                    )
                    break
            if base_flange is not None:
                break
            logger.warning("基体法兰创建失败（%s），删除草图后换策略", label)
            _delete_model_item(model, profile_sketch.Name, "SKETCH")

        if base_flange is None:
            # 回退：闭合轮廓拉伸成薄板，再插入钣金折弯定义。
            logger.warning("改用拉伸实体 + InsertBends 作为钣金回退路径")
            extrude = None
            for label, attempt_profile in profile_variants:
                sketched = _sketch_closed_profile(attempt_profile)
                if sketched is None:
                    continue
                profile_sketch, attempt_points, attempt_origin = sketched
                try:
                    _validate_single_closed_contour(
                        profile_sketch, attempt_profile, type_library
                    )
                except SolidWorksGenerationError as error:
                    last_contour_error = error
                    _delete_model_item(model, profile_sketch.Name, "SKETCH")
                    continue
                if not _select_sketch_contours(
                    model, extension, type_library, profile_sketch
                ):
                    _delete_model_item(model, profile_sketch.Name, "SKETCH")
                    continue
                extrude = _try_extrude_thin_solid(feature_manager, thickness_m)
                if extrude is not None:
                    profile = attempt_profile
                    points = attempt_points
                    origin = attempt_origin
                    logger.info("拉伸回退成功：%s", label)
                    break
                logger.warning("拉伸回退失败（%s），换下一轮廓策略", label)
                _delete_model_item(model, profile_sketch.Name, "SKETCH")
            if extrude is None:
                detail = (
                    str(last_contour_error)
                    if last_contour_error is not None
                    else "草图未能生成可拉伸实体"
                )
                raise SolidWorksGenerationError(
                    "SolidWorks 拒绝创建钣金基体法兰，拉伸回退也失败。"
                    f"轮廓尺寸约 {span_x:.3f} × {span_y:.3f} mm，板厚 "
                    f"{thickness_mm:g} mm。{detail}。"
                    "请确认选的是最大外轮廓（可取消勾选「显示内部切除轮廓」），"
                    "并检查轮廓是否有断点、自交或重叠线。"
                )
            # InsertBends：把拉伸体转成钣金（半径单位 m）。
            bends_feature = None
            insert_bends = getattr(feature_manager, "InsertSheetMetalBends2", None)
            if callable(insert_bends):
                try:
                    bends_feature = insert_bends(
                        radius_m,
                        True,
                        True,
                        True,
                        True,
                        True,
                        False,
                    )
                except Exception:  # noqa: BLE001
                    bends_feature = None
            if bends_feature is None:
                insert_bends = getattr(model, "InsertBends2", None)
                if callable(insert_bends):
                    try:
                        bends_feature = insert_bends(
                            radius_m,
                            "",
                            "",
                            True,
                            True,
                            True,
                            True,
                        )
                    except Exception:  # noqa: BLE001
                        bends_feature = None
            if bends_feature is None:
                logger.warning(
                    "拉伸成功但未能插入钣金折弯定义；继续后续孔切除/折弯流程"
                )
                base_flange = _as_interface(type_library, extrude, "IFeature")
            else:
                base_flange = _as_interface(type_library, bends_feature, "IFeature")
                logger.info("已用拉伸+InsertBends 回退创建钣金：%s", base_flange.Name)
        else:
            base_flange = _as_interface(type_library, base_flange, "IFeature")
            type_name = base_flange.GetTypeName2()
            if type_name not in ("SMBaseFlange", "BaseBody", "Extrusion", "SolidBody"):
                # 部分版本返回名不同；只要不是空特征即可继续。
                if "Flange" not in type_name and "Sheet" not in type_name:
                    logger.warning("基体特征类型为 %s，继续尝试后续步骤", type_name)
            logger.info("基体法兰已创建：%s", base_flange.Name)

        if (hole_profiles and not cad_imported) or relief_cutouts:
            known_sketch_names = {
                feature.Name
                for feature in _features(model, type_library)
                if feature.GetTypeName2() == "ProfileFeature"
            }
            body = _as_interface(
                type_library,
                part.GetBodies2(SW_BODY_TYPE_SOLID, False)[0],
                "IBody2",
            )
            faces = [
                _as_interface(type_library, raw_face, "IFace2")
                for raw_face in body.GetFaces()
            ]
            top_face = max(
                faces,
                key=lambda face: (face.GetArea(), face.GetBox()[5]),
            )
            top_box = top_face.GetBox()
            top_point = (
                (top_box[0] + top_box[3]) / 2,
                (top_box[1] + top_box[4]) / 2,
                top_box[5],
            )
            body_face_count = len(faces)
            _as_interface(type_library, top_face, "IEntity").Select4(False, None)
            sketch_manager.InsertSketch(True)
            active_sketch = _as_interface(
                type_library, sketch_manager.ActiveSketch, "ISketch"
            )
            transform = _as_interface(
                type_library,
                active_sketch.ModelToSketchTransform,
                "IMathTransform",
            ).ArrayData
            sketch_orientation = (
                transform[0] * transform[4] - transform[1] * transform[3]
            )
            created_curves = 0
            previous_add_to_db = sketch_manager.AddToDB
            sketch_manager.AddToDB = True
            try:
                for hole_profile, hole_points in hole_profiles:
                    if hole_profile.kind == "CIRCLE":
                        center, radius = (
                            (
                                hole_profile.circle_center,
                                hole_profile.circle_radius,
                            )
                            if hole_profile.circle_center is not None
                            and hole_profile.circle_radius is not None
                            else _circle_parameters(hole_points)
                        )
                        center_sketch = _transform_to_sketch(
                            transform,
                            (
                                (center[0] - origin[0]) / 1000.0,
                                (center[1] - origin[1]) / 1000.0,
                                top_point[2],
                            ),
                        )
                        sketch_manager.CreateCircleByRadius(
                            center_sketch[0],
                            center_sketch[1],
                            0.0,
                            radius / 1000.0,
                        )
                        created_curves += 1
                        continue

                    hole_segments = hole_profile.curve_segments or tuple(
                        SketchSegment(start, end)
                        for start, end in zip(
                            hole_points,
                            hole_points[1:] + hole_points[:1],
                        )
                    )
                    for segment in hole_segments:
                        start_sketch = _transform_to_sketch(
                            transform,
                            (
                                (segment.start[0] - origin[0]) / 1000.0,
                                (segment.start[1] - origin[1]) / 1000.0,
                                top_point[2],
                            ),
                        )
                        end_sketch = _transform_to_sketch(
                            transform,
                            (
                                (segment.end[0] - origin[0]) / 1000.0,
                                (segment.end[1] - origin[1]) / 1000.0,
                                top_point[2],
                            ),
                        )
                        if segment.center is None or abs(segment.sweep_angle) <= 1e-10:
                            sketch_manager.CreateLine(
                                start_sketch[0],
                                start_sketch[1],
                                0.0,
                                end_sketch[0],
                                end_sketch[1],
                                0.0,
                            )
                            created_curves += 1
                            continue
                        center_sketch = _transform_to_sketch(
                            transform,
                            (
                                (segment.center[0] - origin[0]) / 1000.0,
                                (segment.center[1] - origin[1]) / 1000.0,
                                top_point[2],
                            ),
                        )
                        sketch_manager.CreateArc(
                            center_sketch[0],
                            center_sketch[1],
                            0.0,
                            start_sketch[0],
                            start_sketch[1],
                            0.0,
                            end_sketch[0],
                            end_sketch[1],
                            0.0,
                            _arc_direction(
                                segment.sweep_angle,
                                sketch_orientation,
                            ),
                        )
                        created_curves += 1
                for cutout in relief_cutouts:
                    center_sketch = _transform_to_sketch(
                        transform,
                        (
                            (cutout.center[0] - origin[0]) / 1000.0,
                            (cutout.center[1] - origin[1]) / 1000.0,
                            top_point[2],
                        ),
                    )
                    sketch_manager.CreateCircleByRadius(
                        center_sketch[0],
                        center_sketch[1],
                        0.0,
                        cutout.radius_mm / 1000.0,
                    )
                    created_curves += 1
            finally:
                sketch_manager.AddToDB = previous_add_to_db

            model.ClearSelection2(True)
            sketch_manager.InsertSketch(True)
            cut_sketch = _latest_profile_sketch(
                model,
                type_library,
                known_sketch_names,
            )
            if cut_sketch is None:
                raise SolidWorksGenerationError("SolidWorks 没有创建孔位草图。")
            if not extension.SelectByID2(
                cut_sketch.Name, "SKETCH", 0.0, 0.0, 0.0, False, 0, None, 0
            ):
                raise SolidWorksGenerationError("无法选择孔位草图。")
            hole_cut = feature_manager.FeatureCut3(
                False,
                False,
                False,
                SW_END_CONDITION_THROUGH_ALL,
                0,
                0.005,
                0.005,
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
                True,
                False,
                True,
                False,
                False,
                False,
                0,
                0.0,
                False,
            )
            if hole_cut is None:
                raise SolidWorksGenerationError(
                    f"SolidWorks 拒绝创建包含 {len(hole_profiles)} 个轮廓的孔位切除。"
                )
            if not _com_read(model, "EditRebuild3"):
                raise SolidWorksGenerationError("SolidWorks 重建孔位切除失败。")
            body = _as_interface(
                type_library,
                part.GetBodies2(SW_BODY_TYPE_SOLID, False)[0],
                "IBody2",
            )
            generated_faces = len(body.GetFaces())
            logger.info(
                "孔/槽切除：草图曲线 %d 条，切除前实体面 %d 个，切除后 %d 个",
                created_curves,
                body_face_count,
                generated_faces,
            )
            if generated_faces <= body_face_count:
                raise SolidWorksGenerationError(
                    f"SolidWorks 没有在钣金上生成孔位（草图曲线 {created_curves} 条，"
                    f"切除前/后实体面数 {body_face_count}/{generated_faces}）。"
                    "请检查内部轮廓是否与零件相交。"
                )
            logger.info("孔/槽切除完成：%d 个轮廓", len(hole_profiles))

        group_attempts: list[dict] = []
        bend_sketch_name = ""
        bend_sketch_line_count = 0
        auto_bent = False
        bend_phase = False
        if selected_bends and not auto_bend:
            # 默认路径：只出平板，折弯线画成参考草图，在 SW 里手折更稳（不必开释放槽）。
            bend_sketch_name, bend_sketch_line_count = _create_bend_reference_sketch(
                model,
                part,
                sketch_manager,
                extension,
                type_library,
                analysis,
                selected_bends,
                origin,
                thickness_mm,
                profile,
                fixed_face_point,
            )
        elif selected_bends and auto_bend:
            bend_phase = True
            global _auto_bend_deadline
            _auto_bend_deadline = time.monotonic() + AUTO_BEND_WALL_TIMEOUT_SEC
            completed_bends = _create_bends_with_fallbacks(
                model,
                part,
                feature_manager,
                sketch_manager,
                extension,
                type_library,
                analysis,
                selected_bends,
                origin,
                thickness_mm,
                radius_mm,
                angle_degrees,
                flip_direction,
                fixed_face_point,
                relief_step,
                bend_allowance,
                profile,
                hole_profiles=tuple(hole for hole, _ in hole_profiles),
                group_attempts=group_attempts,
            )
            auto_bent = completed_bends == len(selected_bends)

        # 基体法兰创建后写入全局钣金扣除，展开图与折弯特征一致。
        _apply_sheet_metal_bend_allowance(model, type_library, bend_allowance)

        try:
            rebuild_ok = _com_read(model, "EditRebuild3")
        except Exception as error:  # noqa: BLE001
            if bend_phase and _is_com_disconnect_error(error):
                logger.warning(
                    "折弯后重建时 COM 断连，触发释放槽重试：relief_step=%d err=%s",
                    relief_step,
                    error,
                )
                raise ComDisconnectedBendError(
                    selected_bends,
                    relief_step=relief_step,
                ) from error
            raise
        if not rebuild_ok:
            # 自动折弯后重建失败：常因释放槽不足，转 BendRejected 让 app 扩槽重开文档。
            if auto_bent and selected_bends:
                logger.warning(
                    "自动折弯后重建失败，触发释放槽重试：relief_step=%d",
                    relief_step,
                )
                raise BendRejectedError(selected_bends, relief_step=relief_step)
            raise SolidWorksGenerationError("SolidWorks 重建钣金模型失败。")
        allowance_readback = _verify_sheet_metal_bend_allowance(model, type_library, bend_allowance)
        folded_bounds = _body_bounds(part, type_library)
        flat_pattern = next(
            (
                feature
                for feature in _features(model, type_library)
                if feature.GetTypeName2() == "FlatPattern"
            ),
            None,
        )
        if flat_pattern is None:
            raise SolidWorksGenerationError("SolidWorks 未生成可展开的平板型式。")

        flat_bounds = folded_bounds
        if auto_bent:
            if not extension.SelectByID2(
                flat_pattern.Name, "BODYFEATURE", 0.0, 0.0, 0.0, False, 0, None, 0
            ):
                raise SolidWorksGenerationError("无法选择平板型式以验证展开。")
            model.EditUnsuppress2()
            model.ClearSelection2(True)
            if not _com_read(model, "EditRebuild3"):
                raise SolidWorksGenerationError("SolidWorks 展开钣金失败。")
            flat_bounds = _body_bounds(part, type_library)
            if all(
                abs(folded - flat) <= 1e-7
                for folded, flat in zip(folded_bounds, flat_bounds)
            ):
                raise SolidWorksGenerationError(
                    "SolidWorks 没有改变展开后的几何，已取消保存。"
                )
            if not extension.SelectByID2(
                flat_pattern.Name, "BODYFEATURE", 0.0, 0.0, 0.0, False, 0, None, 0
            ):
                raise SolidWorksGenerationError("无法选择平板型式以恢复折叠状态。")
            model.EditSuppress2()
            model.ClearSelection2(True)
            if not _com_read(model, "EditRebuild3"):
                raise SolidWorksGenerationError("SolidWorks 恢复折叠状态失败。")
        logger.info(
            "展开验证通过：折叠包围盒=%s 展开包围盒=%s",
            folded_bounds,
            flat_bounds,
        )

        output.parent.mkdir(parents=True, exist_ok=True)
        if output.exists():
            raise FileExistsError(f"输出文件已存在：{output}")
        allowance_readback = _verify_sheet_metal_bend_allowance(model, type_library, bend_allowance)
        require_model_write(lease)
        save_errors = model.SaveAs3(str(output), 0, 1)
        if save_errors != 0 or not output.is_file() or output.stat().st_size == 0:
            raise SolidWorksGenerationError(
                f"SolidWorks 未能保存有效的 SLDPRT 文件（错误代码：{save_errors}）。"
            )
        saved = True
        logger.info("钣金零件已保存：%s", output)
        return GenerationResult(
            output,
            profile_index,
            completed_bends if selected_bends and auto_bend else 0,
            len(hole_profiles),
            folded_bounds,
            flat_bounds,
            rect_relief_count if rect_relief_count else len(relief_cutouts),
            auto_bent=auto_bent,
            bend_sketch_name=bend_sketch_name,
            bend_sketch_line_count=bend_sketch_line_count,
            cad_imported=cad_imported,
            bend_allowance_verified=bend_allowance is not None,
            k_factor_readback=allowance_readback if bend_allowance is not None and bend_allowance.mode == "k_factor" else None,
            relief_step_used=relief_step,
            bend_group_attempts=tuple(group_attempts),
        )
    except BendRejectedError as error:
        if not error.bend_group_attempts:
            error.bend_group_attempts = tuple(locals().get("group_attempts", ()))
        # 含 ComDisconnectedBendError：原样抛出，供 app 扩大矩形释放槽后重开文档。
        raise
    except (SolidWorksGenerationError, ValueError, FileExistsError, SessionOwnershipError):
        raise
    except Exception as error:
        if bend_phase and _is_com_disconnect_error(error):
            logger.warning(
                "折弯阶段未捕获 COM 断连，转为释放槽重试：relief_step=%d err=%s",
                relief_step,
                error,
            )
            raise ComDisconnectedBendError(
                selected_bends,
                relief_step=relief_step,
            ) from error
        logger.exception("SolidWorks 创建钣金零件时出错")
        raise SolidWorksGenerationError(
            f"SolidWorks 创建钣金零件时出错：{error}"
        ) from error
    finally:
        try:
            _release_generation_session(
                lease,
                solidworks,
                typed_solidworks,
                document_title=document_title,
                close_document=(
                    solidworks is not None
                    and document_title is not None
                    and (not saved or started_solidworks or CLOSE_SAVED_DOCS or close_saved_document)
                ),
                saved=saved,
                model=model,
            )
        finally:
            if com_initialized:
                pythoncom.CoUninitialize()



def generate_sheet_metal_with_relief_retries(
    analysis: DrawingAnalysis, profile_index: int, bend_indices: Iterable[int],
    thickness_mm: float, radius_mm: float, angle_degrees: float,
    output_path: str | Path, *, flip_direction: bool = False,
    fixed_face_point: tuple[float, float] | None = None,
    relief_bend_indices: Iterable[int] = (), relief_step: int = 0,
    bend_allowance: BendAllowanceSpec | None = None, auto_bend: bool = True,
    cad_import: bool | None = None, progress: Callable[[str], None] | None = None,
    close_saved_document: bool = False,
) -> GenerationResult:
    """Bounded retries; return explicit degraded evidence for a flat fallback.

    A real timed-out/disconnected lease remains write-blocked: its fallback
    will fail closed rather than reconnecting to an unknown CAD session.
    """
    selected = tuple(dict.fromkeys(int(i) for i in bend_indices))
    relief = tuple(dict.fromkeys(int(i) for i in relief_bend_indices)) or selected
    step = int(relief_step)
    if not 0 <= step <= MAX_RELIEF_STEPS:
        raise ValueError("relief_step outside supported range")
    common = dict(flip_direction=flip_direction, fixed_face_point=fixed_face_point,
                  bend_allowance=bend_allowance, cad_import=cad_import,
                  close_saved_document=close_saved_document)
    args = (analysis, profile_index, selected, thickness_mm, radius_mm,
            angle_degrees, output_path)
    if not auto_bend:
        return generate_sheet_metal(*args, auto_bend=False, **common)
    attempts = 0
    failures = 0
    trace: list[dict] = []
    while step <= MAX_RELIEF_STEPS and attempts < MAX_AUTO_BEND_ATTEMPTS:
        attempts += 1
        if progress:
            progress(f"自动折弯第 {attempts}/{MAX_AUTO_BEND_ATTEMPTS} 次")
        try:
            result = generate_sheet_metal(*args, auto_bend=True,
                relief_bend_indices=relief, relief_step=step, **common)
            trace.append(dict(attempt=attempts, relief_step=step,
                relief_extra_mm=rect_relief_extra_mm(step), status="completed" if result.auto_bent else "degraded",
                completed_bend_count=result.bend_count, relief_slot_count=result.relief_slot_count,
                bend_group_attempts=list(result.bend_group_attempts)))
            return replace(result, auto_bend_attempts=attempts, bend_attempts=tuple(trace),
                           auto_bend_failed_count=max(0, len(selected) - result.bend_count),
                           auto_bend_abandoned=not result.auto_bent)
        except (ComDisconnectedBendError, BendRejectedError) as error:
            failures += 1
            trace.append(dict(attempt=attempts, relief_step=step,
                relief_extra_mm=rect_relief_extra_mm(step), status="rejected",
                failed_bend_indices=list(error.bend_indices), completed_bend_count=error.completed_bend_count,
                error_kind=type(error).__name__, error=str(error),
                bend_group_attempts=list(error.bend_group_attempts)))
            logger.warning("auto bend rejected attempt=%d relief_step=%d failed=%s completed=%d",
                attempts, step, error.bend_indices, error.completed_bend_count)
            if isinstance(error, ComDisconnectedBendError) and error.timed_out:
                break
            step += 1
    if progress:
        progress("自动折弯未完成，改为出平板及折弯参考线；需要人工复核")
    result = generate_sheet_metal(*args, auto_bend=False, **common)
    return replace(result, auto_bend_attempts=attempts, bend_attempts=tuple(trace),
                   auto_bend_failed_count=len(selected), auto_bend_abandoned=True)



def export_flat_pattern_dxf(
    part_path: str | Path,
    dxf_path: str | Path,
    *,
    close_document: bool = True,
) -> Path:
    """把钣金零件的展开图导出成 DXF，供激光下料 / 折弯定位使用。

    用 SolidWorks 自己的 ``IPartDoc::ExportFlatPatternView``，也就是
    「展开 → 另存为 DXF」同一条路径，弯折线与轮廓都按实际展开尺寸输出。
    """

    if not on_task_sta():
        return run_on_task_sta(
            lambda: export_flat_pattern_dxf(
                part_path,
                dxf_path,
                close_document=close_document,
            ),
            timeout=SW_SESSION_CALL_TIMEOUT_SEC,
            task_name="export_flat_pattern_dxf",
        )
    part = Path(part_path).expanduser().resolve()
    if not part.is_file():
        raise SolidWorksGenerationError(f"找不到零件文件：{part}")
    target = Path(dxf_path).expanduser().resolve()
    if target.suffix.casefold() != ".dxf":
        raise ValueError("展开图必须导出为 .dxf 文件。")
    if target == part or target.exists():
        raise FileExistsError("refusing to overwrite an existing DXF/source file")

    try:
        import pythoncom
        import win32com.client
    except ImportError as error:
        raise SolidWorksGenerationError(
            "导出展开图需要 pywin32；请使用配置了 SolidWorks 的 Python 环境。"
        ) from error

    com_initialized = False
    raw_model: Any = None
    opened_here = False
    model_title: str | None = None
    solidworks: Any = None
    typed_solidworks: Any = None
    lease = None
    titles_enumerated = False
    try:
        lease = current_lease()
        pythoncom.CoInitialize()
        com_initialized = True
        solidworks, _created_here = _connect_task_solidworks(
            lease, win32com, pythoncom
        )
        type_library = ensure_solidworks_typelib()
        typed_solidworks = _as_interface(type_library, solidworks, "ISldWorks")
        if lease is not None:
            lease.note_bound_application(typed_solidworks)
        require_model_write(lease)
        typed_solidworks.Visible = True

        # 用户已经打开的文档不归本任务。列不出来就不关闭任何文档。
        open_titles_before: set[str] = set()
        try:
            open_titles_before = set(_list_open_document_titles(typed_solidworks))
            titles_enumerated = True
        except Exception:
            logger.debug("无法枚举已打开文档，不关闭任何文档", exc_info=True)

        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise FileExistsError("DXF destination appeared before export")

        # OpenDoc6 在多数绑定下返回 (model, errors, warnings)，兼容两种返回形式。
        require_model_write(lease)
        opened = typed_solidworks.OpenDoc6(
            str(part),
            SW_DOCUMENT_TYPE_PART,
            SW_OPEN_DOC_SILENT,
            "",
            0,
            0,
        )
        raw_model = opened[0] if isinstance(opened, tuple) else opened
        if raw_model is None:
            raise SolidWorksGenerationError(
                f"SolidWorks 打不开零件：{part.name}（可能正被其他版本占用）"
            )
        title = raw_model.GetTitle
        model_title = str(title() if callable(title) else title)
        opened_here = bool(
            titles_enumerated and model_title not in open_titles_before
        )
        if opened_here and lease is not None and model_title is not None:
            lease.note_owned_document(model_title, handle_id=id(raw_model))

        part_doc = _as_interface(type_library, raw_model, "IPartDoc")
        ok = part_doc.ExportFlatPatternView(str(target), 0)
        if not ok or not target.is_file():
            raise SolidWorksGenerationError(
                "导出展开图失败：该零件可能不含钣金展开特征（只有钣金平板/折弯件才能导出）。"
            )
        logger.info("已导出展开图：%s → %s", part.name, target)
        return target
    except Exception as error:
        if isinstance(error, (SolidWorksGenerationError, ValueError, SessionOwnershipError)):
            raise
        raise SolidWorksGenerationError(f"导出展开图时出错：{error}") from error
    finally:
        try:
            if close_document and opened_here and model_title:
                _release_generation_session(
                    lease,
                    solidworks,
                    typed_solidworks,
                    document_title=model_title,
                    close_document=True,
                    saved=False,
                    model=None,
                )
        finally:
            if com_initialized:
                pythoncom.CoUninitialize()


def generate_roller_part(
    spec: RollerSpec,
    output_path: str | Path,
) -> RollerGenerationResult:
    if not on_task_sta():
        return run_on_task_sta(
            lambda: generate_roller_part(spec, output_path),
            timeout=SW_SESSION_CALL_TIMEOUT_SEC,
            task_name="generate_roller_part",
        )
    layout = compute_roller_layout(spec)
    barrel_length = layout.barrel_length_mm
    output = Path(output_path).expanduser().resolve()
    if output.suffix.casefold() != ".sldprt":
        raise ValueError("输出文件扩展名必须为 .SLDPRT。")
    if output.exists():
        raise FileExistsError(f"输出文件已存在：{output}")

    logger.info(
        "生成滚筒零件：类型=%s 总长=%.3f 筒身长=%.3f 外径=%.3f 壁厚=%.3f "
        "轴径=%.3f 轴头伸出=%.3f 光轴外露=%s 螺纹=%s 齿数=%s 链节距=%s 输出=%s",
        spec.roller_type,
        spec.overall_length_mm,
        barrel_length,
        spec.outer_diameter_mm,
        spec.wall_thickness_mm,
        spec.shaft_diameter_mm,
        spec.shaft_projection_mm,
        spec.shaft_exposed_mm,
        spec.shaft_thread_designation,
        spec.sprocket_teeth,
        spec.chain_pitch_mm,
        output,
    )

    try:
        import pythoncom
        import win32com.client
    except ImportError as error:
        raise SolidWorksGenerationError(
            "生成滚筒需要 pywin32；请使用配置了 SolidWorks 的 Python 环境运行程序。"
        ) from error

    solidworks: Any = None
    raw_model: Any = None
    document_title: str | None = None
    saved = False
    com_initialized = False
    started_solidworks = False
    typed_solidworks: Any = None
    model = None
    lease = None
    try:
        lease = current_lease()
        pythoncom.CoInitialize()
        com_initialized = True
        solidworks, started_solidworks = _connect_task_solidworks(
            lease, win32com, pythoncom
        )
        type_library = ensure_solidworks_typelib()
        typed_solidworks = _as_interface(type_library, solidworks, "ISldWorks")
        if lease is not None:
            lease.note_bound_application(typed_solidworks)
        template_path = typed_solidworks.GetUserPreferenceStringValue(
            SW_DEFAULT_TEMPLATE_PART
        )
        if not template_path or not Path(template_path).is_file():
            raise SolidWorksGenerationError(
                "SolidWorks 的默认零件模板不可用；请在系统选项中设置默认零件模板。"
            )

        require_model_write(lease)
        raw_model = typed_solidworks.NewDocument(template_path, 0, 0.0, 0.0)
        if raw_model is None:
            raise SolidWorksGenerationError("SolidWorks 未能创建新的滚筒零件文档。")
        model = _as_interface(type_library, raw_model, "IModelDoc2")
        document_title = str(model.GetTitle())
        if lease is not None:
            lease.note_owned_document(document_title, handle_id=id(raw_model))
        part = _as_interface(type_library, raw_model, "IPartDoc")
        feature_manager = _as_interface(
            type_library, model.FeatureManager, "IFeatureManager"
        )
        sketch_manager = _as_interface(
            type_library, model.SketchManager, "ISketchManager"
        )

        reference_planes = [
            feature
            for feature in _features(model, type_library)
            if feature.GetTypeName2() == "RefPlane"
        ]
        if not reference_planes:
            raise SolidWorksGenerationError("零件模板中没有可用的基准面。")
        reference_plane = reference_planes[-1]

        def create_closed_sketch(
            polylines_mm: tuple[tuple[tuple[float, float], ...], ...],
            axis_start_mm: float,
            axis_end_mm: float,
            label: str,
            *,
            segment_loops: tuple[tuple[dict[str, object], ...], ...] | None = None,
        ) -> Any:
            known_sketch_names = {
                feature.Name
                for feature in _features(model, type_library)
                if feature.GetTypeName2() == "ProfileFeature"
            }
            if not _as_interface(
                type_library, reference_plane, "IEntity"
            ).Select4(False, None):
                raise SolidWorksGenerationError(f"无法选择{label}草图基准面。")
            sketch_manager.InsertSketch(True)
            previous_add_to_db = sketch_manager.AddToDB
            sketch_manager.AddToDB = True
            expected_contours = 0
            try:
                sketch_manager.CreateCenterLine(
                    axis_start_mm / 1000.0,
                    0.0,
                    0.0,
                    axis_end_mm / 1000.0,
                    0.0,
                    0.0,
                )
                if segment_loops is not None:
                    expected_contours = len(segment_loops)
                    for loop in segment_loops:
                        if len(loop) < 3:
                            raise SolidWorksGenerationError(
                                f"{label}轮廓段数不足，无法形成闭合草图。"
                            )
                        for curve in loop:
                            start = curve["start"]
                            end = curve["end"]
                            if curve["kind"] == "line":
                                created = sketch_manager.CreateLine(
                                    start[0] / 1000.0,  # type: ignore[index]
                                    start[1] / 1000.0,  # type: ignore[index]
                                    0.0,
                                    end[0] / 1000.0,  # type: ignore[index]
                                    end[1] / 1000.0,  # type: ignore[index]
                                    0.0,
                                )
                            else:
                                center = curve["center"]
                                created = sketch_manager.CreateArc(
                                    center[0] / 1000.0,  # type: ignore[index]
                                    center[1] / 1000.0,  # type: ignore[index]
                                    0.0,
                                    start[0] / 1000.0,  # type: ignore[index]
                                    start[1] / 1000.0,  # type: ignore[index]
                                    0.0,
                                    end[0] / 1000.0,  # type: ignore[index]
                                    end[1] / 1000.0,  # type: ignore[index]
                                    0.0,
                                    int(curve["direction"]),  # type: ignore[arg-type]
                                )
                            if created is None:
                                raise SolidWorksGenerationError(
                                    f"{label}草图{curve['kind']}创建失败。"
                                )
                else:
                    expected_contours = len(polylines_mm)
                    for polyline in polylines_mm:
                        if len(polyline) < 3:
                            raise SolidWorksGenerationError(
                                f"{label}轮廓点数不足，无法形成闭合草图。"
                            )
                        closed_points = polyline + (polyline[0],)
                        for start, end in zip(closed_points, closed_points[1:]):
                            sketch_manager.CreateLine(
                                start[0] / 1000.0,
                                start[1] / 1000.0,
                                0.0,
                                end[0] / 1000.0,
                                end[1] / 1000.0,
                                0.0,
                            )
            finally:
                sketch_manager.AddToDB = previous_add_to_db
            model.ClearSelection2(True)
            sketch_manager.InsertSketch(True)
            sketch_feature = _latest_profile_sketch(
                model,
                type_library,
                known_sketch_names,
            )
            if sketch_feature is None:
                raise SolidWorksGenerationError(f"SolidWorks 未能创建{label}草图。")
            sketch = _as_interface(
                type_library,
                sketch_feature.GetSpecificFeature2(),
                "ISketch",
            )
            contours = sketch.GetSketchContours() or ()
            if len(contours) != expected_contours or any(
                not _as_interface(type_library, contour, "ISketchContour").IsClosed()
                for contour in contours
            ):
                raise SolidWorksGenerationError(
                    f"SolidWorks 未能识别{label}中的预期闭合轮廓。"
                )
            return sketch_feature

        def revolve_sketch(sketch_feature: Any, *, cut: bool, label: str) -> Any:
            if not _as_interface(
                type_library, sketch_feature, "IEntity"
            ).Select4(False, None):
                raise SolidWorksGenerationError(f"无法选择{label}草图。")
            if cut:
                feature = feature_manager.FeatureRevolveCut(
                    2.0 * math.pi,
                    False,
                    0.0,
                    0,
                    0,
                    True,
                    True,
                )
            else:
                feature = feature_manager.FeatureRevolve2(
                    True,
                    True,
                    False,
                    False,
                    False,
                    False,
                    0,
                    0,
                    2.0 * math.pi,
                    0.0,
                    False,
                    False,
                    0.0,
                    0.0,
                    0,
                    0.0,
                    0.0,
                    True,
                    True,
                    True,
                )
            model.ClearSelection2(True)
            if feature is None or not _com_read(model, "EditRebuild3"):
                raise SolidWorksGenerationError(f"SolidWorks 创建{label}失败。")
            return feature

        tip_half, _, _, _ = roller_axial_extents(spec)
        shaft_radius = spec.shaft_diameter_mm / 2.0
        barrel_radius = spec.outer_diameter_mm / 2.0
        inner_radius = barrel_radius - spec.wall_thickness_mm
        main_segments = roller_revolve_segments(spec, layout)
        main_sketch = create_closed_sketch(
            (),
            -tip_half,
            tip_half,
            "滚筒外轮廓",
            segment_loops=(main_segments,),
        )
        revolve_sketch(main_sketch, cut=False, label="滚筒外轮廓旋转")

        for span_index, (cavity_start, cavity_end) in enumerate(
            layout.cavity_spans_mm,
            start=1,
        ):
            cavity_profile = (
                (cavity_start, shaft_radius),
                (cavity_end, shaft_radius),
                (cavity_end, inner_radius),
                (cavity_start, inner_radius),
            )
            cavity_sketch = create_closed_sketch(
                (cavity_profile,),
                -tip_half,
                tip_half,
                f"滚筒内腔 {span_index}",
            )
            revolve_sketch(
                cavity_sketch,
                cut=True,
                label=f"滚筒内腔切除 {span_index}",
            )

        def model_volume_m3() -> float:
            mass_property = model.Extension.CreateMassProperty()
            try:
                volume = mass_property.Volume
            except AttributeError:
                volume = mass_property.GetVolume()
            return float(volume)

        def create_pocket_sketch(
            pockets: tuple[tuple[dict[str, object], ...], ...],
        ) -> Any:
            known_sketch_names = {
                feature.Name
                for feature in _features(model, type_library)
                if feature.GetTypeName2() == "ProfileFeature"
            }
            sketch_manager.InsertSketch(True)
            previous_add_to_db = sketch_manager.AddToDB
            sketch_manager.AddToDB = True
            try:
                for pocket in pockets:
                    for curve in pocket:
                        start = curve["start"]
                        end = curve["end"]
                        if curve["kind"] == "line":
                            created = sketch_manager.CreateLine(
                                start[0] / 1000.0,  # type: ignore[index]
                                start[1] / 1000.0,  # type: ignore[index]
                                0.0,
                                end[0] / 1000.0,  # type: ignore[index]
                                end[1] / 1000.0,  # type: ignore[index]
                                0.0,
                            )
                        else:
                            center = curve["center"]
                            created = sketch_manager.CreateArc(
                                center[0] / 1000.0,  # type: ignore[index]
                                center[1] / 1000.0,  # type: ignore[index]
                                0.0,
                                start[0] / 1000.0,  # type: ignore[index]
                                start[1] / 1000.0,  # type: ignore[index]
                                0.0,
                                end[0] / 1000.0,  # type: ignore[index]
                                end[1] / 1000.0,  # type: ignore[index]
                                0.0,
                                int(curve["direction"]),  # type: ignore[arg-type]
                            )
                        if created is None:
                            raise SolidWorksGenerationError(
                                "链轮齿槽草图线段/圆弧创建失败"
                                f"（{curve['kind']}）。"
                            )
            finally:
                sketch_manager.AddToDB = previous_add_to_db
            model.ClearSelection2(True)
            sketch_manager.InsertSketch(True)
            sketch_feature = _latest_profile_sketch(
                model,
                type_library,
                known_sketch_names,
            )
            if sketch_feature is None:
                return None
            sketch = _as_interface(
                type_library,
                sketch_feature.GetSpecificFeature2(),
                "ISketch",
            )
            contours = sketch.GetSketchContours() or ()
            closed = [
                contour
                for contour in contours
                if _as_interface(type_library, contour, "ISketchContour").IsClosed()
            ]
            if len(closed) != len(pockets):
                raise SolidWorksGenerationError(
                    f"链轮齿槽草图应有 {len(pockets)} 个闭合轮廓，"
                    f"实际识别到 {len(closed)} 个。"
                )
            return sketch_feature

        def create_sprocket_cut() -> None:
            """对齐参考件：在链轮区法向基准面上画齿槽，再单向盲切到端面。

            切除起点略伸入首排内侧轮毂，终点与 ``body_max`` 齐平，绝不切入轴头，
            避免端面上出现星形切痕；不用中面切除，防止深度被当成单侧再翻倍。
            """

            if (
                layout.sprocket_cut_span_mm is None
                or layout.sprocket_pitch_radius_mm is None
                or layout.sprocket_seat_radius_mm is None
                or layout.sprocket_row_width_mm is None
                or spec.sprocket_teeth is None
            ):
                return
            cut_start, cut_end = layout.sprocket_cut_span_mm
            depth = cut_end - cut_start
            if depth <= 0.5:
                raise SolidWorksGenerationError("链轮排间距过小，无法切齿。")
            if cut_end > layout.body_max_mm + 1e-6:
                raise SolidWorksGenerationError(
                    "切齿终点超出链轮端面，会切入轴头。"
                )

            tip_radius = float(layout.sprocket_outer_diameter_mm or 0.0) / 2.0
            pockets = sprocket_tooth_pockets(
                int(spec.sprocket_teeth),
                float(layout.sprocket_pitch_radius_mm),
                float(layout.sprocket_seat_radius_mm),
                tip_radius,
            )
            # 每排齿顶厚 + 两侧根宽倒角都会被切到。
            bevel = SPROCKET_TOOTH_BEVEL_REF_MM * _pitch_scale(
                spec.chain_pitch_mm or DEFAULT_CHAIN_PITCH_MM
            )
            axial_engage = float(layout.sprocket_row_width_mm) + 2.0 * bevel
            expected_volume = (
                int(spec.sprocket_teeth)
                * len(layout.sprocket_rows_mm)
                * sprocket_pocket_area(pockets[0])
                * axial_engage
                * 1e-9
            )

            planes = [
                feature
                for feature in _features(model, type_library)
                if feature.GetTypeName2() == "RefPlane"
            ]
            perpendicular = planes[0]
            for plane in planes:
                if "右视" in plane.Name or "侧视" in plane.Name or "右" in plane.Name:
                    perpendicular = plane
                    break
            else:
                for plane in planes:
                    if plane is not reference_plane and plane is not perpendicular:
                        perpendicular = plane
                        break

            last_error: Exception | None = None
            # 基准面放在 cut_start，再试翻转平面法向与切除方向。
            for plane_flip in (False, True):
                # 本机 SW2025 实测：cut_flip=True 才是切得动的方向，排在最前，
                # 省掉一次注定失败的建模；False 留作其他版本的兜底。
                for cut_flip in (True, False):
                    feature_count = model.GetFeatureCount()
                    volume_before = model_volume_m3()
                    try:
                        model.ClearSelection2(True)
                        if not _as_interface(
                            type_library, perpendicular, "IEntity"
                        ).Select4(False, None):
                            raise SolidWorksGenerationError(
                                "无法选择与滚筒轴线垂直的基准面。"
                            )
                        known_planes = {
                            feature.Name
                            for feature in _features(model, type_library)
                            if feature.GetTypeName2() == "RefPlane"
                        }
                        model.CreatePlaneAtOffset(cut_start / 1000.0, plane_flip)
                        offset_plane = next(
                            (
                                feature
                                for feature in _features(model, type_library)
                                if feature.GetTypeName2() == "RefPlane"
                                and feature.Name not in known_planes
                            ),
                            None,
                        )
                        if offset_plane is None:
                            raise SolidWorksGenerationError(
                                "无法创建链轮切齿用的基准面。"
                            )
                        if not _as_interface(
                            type_library, offset_plane, "IEntity"
                        ).Select4(False, None):
                            raise SolidWorksGenerationError(
                                "无法选择新建的链轮切齿基准面。"
                            )
                        pocket_sketch = create_pocket_sketch(pockets)
                        if pocket_sketch is None:
                            raise SolidWorksGenerationError(
                                "SolidWorks 未能创建链轮齿槽草图。"
                            )
                        if not _as_interface(
                            type_library, pocket_sketch, "IEntity"
                        ).Select4(False, None):
                            raise SolidWorksGenerationError(
                                "无法选择链轮齿槽草图。"
                            )
                        cut_feature = feature_manager.FeatureCut4(
                            True,
                            False,
                            cut_flip,
                            SW_END_CONDITION_BLIND,
                            0,
                            depth / 1000.0,
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
                            False,
                            True,
                            True,
                            False,
                            True,
                            True,
                            SW_START_CONDITION_SKETCH_PLANE,
                            0.0,
                            False,
                            True,
                        )
                        model.ClearSelection2(True)
                        if cut_feature is None or not _com_read(model, "EditRebuild3"):
                            raise SolidWorksGenerationError(
                                "链轮切齿特征创建失败。"
                            )
                        removed = volume_before - model_volume_m3()
                        if expected_volume * 0.75 <= removed <= expected_volume * 1.35:
                            logger.info(
                                "链轮切齿完成：齿数=%d 深度=%.3f mm "
                                "切除体积=%.3f mm³（预期约 %.3f mm³）",
                                int(spec.sprocket_teeth),
                                depth,
                                removed * 1e9,
                                expected_volume * 1e9,
                            )
                            return
                        last_error = SolidWorksGenerationError(
                            "切齿切除体积异常："
                            f"实际 {removed * 1e9:.1f} mm³，"
                            f"预期约 {expected_volume * 1e9:.1f} mm³。"
                        )
                        # 探测某个方向组合失败属于正常过程，不该在日志里像报错。
                        logger.debug(
                            "%s plane_flip=%s cut_flip=%s",
                            last_error,
                            plane_flip,
                            cut_flip,
                        )
                    except Exception as error:  # noqa: BLE001 - 翻转后重试
                        last_error = error
                        logger.warning("链轮切齿尝试失败：%s", error)
                    steps = model.GetFeatureCount() - feature_count
                    for _ in range(max(0, steps)):
                        model.EditUndo2(1)
            raise SolidWorksGenerationError(
                f"SolidWorks 未能切出链轮齿槽：{last_error}"
            )

        def create_shaft_hole(
            axis_x: float,
            direction: float,
            label: str,
        ) -> None:
            """在轴端生成螺纹底孔（参考件为 M10 / Ø8.5；亦可选 M8）。"""

            thread = spec.shaft_thread_designation.strip().upper()
            tap_diameter = SHAFT_THREAD_SPECS_MM[thread]
            if tap_diameter >= spec.shaft_diameter_mm:
                raise SolidWorksGenerationError(
                    f"{thread} 底孔 Ø{tap_diameter:g} 不小于轴径 "
                    f"{spec.shaft_diameter_mm:g} mm，无法在轴端制孔。"
                )
            tap_radius = tap_diameter / 2.0
            point_depth = tap_radius / math.tan(math.radians(59.0))
            outer = axis_x + direction * 1.0
            bottom = axis_x - direction * SHAFT_THREAD_DEPTH_MM
            tip = bottom - direction * point_depth
            hole_profile = (
                (outer, 0.0),
                (outer, tap_radius),
                (bottom, tap_radius),
                (tip, 0.0),
            )
            hole_sketch = create_closed_sketch(
                (hole_profile,),
                -tip_half,
                tip_half,
                label,
            )
            revolve_sketch(hole_sketch, cut=True, label=label)

        if layout.sprocket_rows_mm:
            create_sprocket_cut()
        thread_label = spec.shaft_thread_designation.strip().upper()
        create_shaft_hole(
            tip_half,
            1.0,
            f"轴端 {thread_label} 螺纹底孔（链轮端）",
        )
        create_shaft_hole(
            -tip_half,
            -1.0,
            f"轴端 {thread_label} 螺纹底孔（挡圈端）",
        )

        raw_bodies = part.GetBodies2(SW_BODY_TYPE_SOLID, False) or ()
        if len(raw_bodies) != 1:
            raise SolidWorksGenerationError(
                f"滚筒应为单一实体，SolidWorks 实际生成了 {len(raw_bodies)} 个实体。"
            )
        bounds_m = _body_bounds(part, type_library)
        dimensions = sorted(
            (
                (bounds_m[3] - bounds_m[0]) * 1000.0,
                (bounds_m[4] - bounds_m[1]) * 1000.0,
                (bounds_m[5] - bounds_m[2]) * 1000.0,
            )
        )
        maximum_diameter = (
            layout.sprocket_outer_diameter_mm
            if layout.sprocket_outer_diameter_mm is not None
            else spec.outer_diameter_mm
        )
        minimum_diameter = (
            layout.sprocket_root_diameter_mm
            if layout.sprocket_root_diameter_mm is not None
            else spec.outer_diameter_mm
        )
        # 轴长必须精确；链轮端两个方向的外包尺寸受齿数影响，落在齿根圆与
        # 齿顶圆之间即为正常，其中最大方向应等于齿顶圆直径。
        # 无动力图纸主长度是筒身端面距，实体端到端 = 筒身 + 2×轴头台阶。
        expected_length = tip_half * 2.0
        dimension_ok = (
            math.isclose(
                dimensions[2],
                expected_length,
                rel_tol=1e-4,
                abs_tol=0.05,
            )
            and math.isclose(
                dimensions[1],
                maximum_diameter,
                rel_tol=1e-4,
                abs_tol=0.05,
            )
            and minimum_diameter - 0.05
            <= dimensions[0]
            <= maximum_diameter + 0.05
        )
        if not dimension_ok:
            raise SolidWorksGenerationError(
                "SolidWorks 滚筒实体尺寸与输入不符："
                f"实际 {tuple(round(value, 3) for value in dimensions)} mm，"
                f"预期长度 {expected_length:g} mm、"
                f"链轮外径 {maximum_diameter:g} mm"
                f"（齿根圆 {minimum_diameter:g} mm 至齿顶圆之间）。"
            )
        bounds = (
            bounds_m[0] * 1000.0,
            bounds_m[1] * 1000.0,
            bounds_m[2] * 1000.0,
            bounds_m[3] * 1000.0,
            bounds_m[4] * 1000.0,
            bounds_m[5] * 1000.0,
        )

        custom_properties = model.Extension.CustomPropertyManager("")
        exposed_property = (
            ""
            if spec.shaft_exposed_mm is None
            else f"{spec.shaft_exposed_mm:g}"
        )
        thread_property = spec.shaft_thread_designation.strip().upper()
        properties = (
            ("RollerType", spec.roller_type),
            ("OverallLength_mm", f"{spec.overall_length_mm:g}"),
            ("BarrelLength_mm", f"{barrel_length:g}"),
            ("OuterDiameter_mm", f"{spec.outer_diameter_mm:g}"),
            ("WallThickness_mm", f"{spec.wall_thickness_mm:g}"),
            ("ShaftDiameter_mm", f"{spec.shaft_diameter_mm:g}"),
            ("ShaftProjection_mm", f"{spec.shaft_projection_mm:g}"),
            ("ShaftExposed_mm", exposed_property),
            (
                "SprocketTeeth",
                "" if spec.sprocket_teeth is None else str(spec.sprocket_teeth),
            ),
            (
                "ChainPitch_mm",
                (
                    f"{spec.chain_pitch_mm:g}"
                    if spec.chain_pitch_mm is not None
                    else f"{DEFAULT_CHAIN_PITCH_MM:g}"
                ),
            ),
            (
                "SprocketOuterDiameter_mm",
                (
                    ""
                    if layout.sprocket_outer_diameter_mm is None
                    else f"{layout.sprocket_outer_diameter_mm:g}"
                ),
            ),
            (
                "SprocketRootDiameter_mm",
                (
                    ""
                    if layout.sprocket_root_diameter_mm is None
                    else f"{layout.sprocket_root_diameter_mm:g}"
                ),
            ),
            (
                "SprocketGeometry",
                (
                    "Double-row sprocket; roller seat arc + tangent flanks; "
                    "tooth pockets cut"
                ),
            ),
            (
                "ModelDetail",
                (
                    "Hollow barrel, reduced hub, double sprocket rows, "
                    "shaft journals, retaining grooves and "
                    f"{thread_property} threaded holes"
                ),
            ),
            ("TubeLength_mm", f"{layout.tube_length_mm:g}"),
            (
                "HubDiameter_mm",
                (
                    ""
                    if layout.hub_diameter_mm is None
                    else f"{layout.hub_diameter_mm:g}"
                ),
            ),
            (
                "SprocketCutSpan_mm",
                (
                    ""
                    if layout.sprocket_cut_span_mm is None
                    else "-".join(
                        f"{value:g}" for value in layout.sprocket_cut_span_mm
                    )
                ),
            ),
            ("ShaftThread", thread_property),
            (
                "RetainingGroove",
                "Axial retaining-ring groove at each shaft end",
            ),
        )
        for name, value in properties:
            # DeleteAndAdd，避免模板里同名属性残留旧值。
            result = custom_properties.Add3(name, 30, value, 1)
            if result not in (0, 1):
                raise SolidWorksGenerationError(
                    f"无法保存滚筒参数自定义属性：{name}（代码 {result}）。"
                )
            set_result = custom_properties.Set2(name, value)
            if set_result is False:
                raise SolidWorksGenerationError(
                    f"无法写入滚筒参数自定义属性：{name}。"
                )

        output.parent.mkdir(parents=True, exist_ok=True)
        if output.exists():
            raise FileExistsError(f"输出文件已存在：{output}")
        require_model_write(lease)
        save_errors = model.SaveAs3(str(output), 0, 1)
        if save_errors != 0 or not output.is_file() or output.stat().st_size == 0:
            raise SolidWorksGenerationError(
                f"SolidWorks 未能保存有效的 SLDPRT 文件（错误代码：{save_errors}）。"
            )
        saved = True
        logger.info("滚筒零件已保存：%s", output)
        return RollerGenerationResult(
            output,
            spec.roller_type,
            spec.overall_length_mm,
            barrel_length,
            bounds,
            layout.tube_length_mm,
            layout.sprocket_outer_diameter_mm,
        )
    except (SolidWorksGenerationError, ValueError, FileExistsError, SessionOwnershipError):
        raise
    except Exception as error:
        logger.exception("SolidWorks 创建滚筒零件时出错")
        raise SolidWorksGenerationError(
            f"SolidWorks 创建滚筒零件时出错：{error}"
        ) from error
    finally:
        try:
            _release_generation_session(
                lease,
                solidworks,
                typed_solidworks,
                document_title=document_title,
                close_document=(
                    solidworks is not None
                    and document_title is not None
                    and (not saved or started_solidworks)
                ),
                saved=saved,
                model=model,
            )
        finally:
            if com_initialized:
                pythoncom.CoUninitialize()


