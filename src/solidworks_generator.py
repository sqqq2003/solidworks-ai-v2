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
from roller_geometry import (  # noqa: F401  re-exported
    SW_ARC_DIRECTION_CLOCKWISE,
    SW_ARC_DIRECTION_COUNTERCLOCKWISE,
    DEFAULT_CHAIN_PITCH_MM,
    CHAIN_ROLLER_DIAMETER_RATIO,
    SPROCKET_SEAT_HALF_ANGLE_DEG,
    SPROCKET_SEAT_RADIUS_FACTOR,
    SPROCKET_SEAT_RADIUS_OFFSET,
    SPROCKET_TIP_EXTRA_RATIO,
    SPROCKET_PITCH_RADIUS_REF_MM,
    SPROCKET_SEAT_RADIUS_REF_MM,
    SPROCKET_TIP_RADIUS_REF_MM,
    SPROCKET_ROOT_LAND_RADIUS_REF_MM,
    SPROCKET_ROW_WIDTH_REF_MM,
    SPROCKET_TOOTH_BEVEL_REF_MM,
    SPROCKET_ROW_BASE_GAP_REF_MM,
    SPROCKET_HUB_LEAD_REF_MM,
    SPROCKET_HUB_TRANSITION_REF_MM,
    SPROCKET_CUT_OVERSHOOT_REF_MM,
    SPROCKET_ROOT_CLEARANCE_MM,
    HUB_DIAMETER_RATIO,
    HUB_MIN_RADIAL_WALL_MM,
    HUB_RADIUS_REF_MM,
    SHAFT_JOURNAL_DIAMETER_EXTRA_MM,
    SHAFT_IDLE_STEP_RADIUS_REF_MM,
    SHAFT_IDLE_STEP_LENGTH_REF_MM,
    SHAFT_IDLE_FILLET_REF_MM,
    SHAFT_IDLE_CORNER_RADIUS_REF_MM,
    SHAFT_IDLE_EXPOSED_REF_MM,
    TRANSITION_ARC_SEGMENTS,
    UNPOWERED_BARREL_FILLET_REF_MM,
    UNPOWERED_STEP_DIAMETER_EXTRA_MM,
    DEFAULT_SHAFT_THREAD_DESIGNATION,
    SHAFT_THREAD_DEPTH_MM,
    SHAFT_THREAD_SPECS_MM,
    RollerSpec,
    RollerLayout,
    _add_point,
    _scale_point,
    _rotate_point,
    _mirror_point,
    _ray_circle_far_hit,
    sprocket_geometry,
    _pitch_scale,
    sprocket_tooth_pockets,
    sprocket_pocket_area,
    _mm,
    _journal_radius,
    unpowered_end_layout,
    roller_axial_extents,
    roller_revolve_segments,
    roller_revolve_profile,
    validate_roller_spec,
    compute_roller_layout,
)
from sheet_metal_geometry import (  # noqa: F401  re-exported
    RECT_RELIEF_FIRST_EXPAND_MM,
    RECT_RELIEF_EXPAND_MM,
    rect_relief_extra_mm,
    ReliefCutout,
    _line_intersection,
    _segment_intersection,
    _bend_profile_intersections,
    _ray_profile_hit,
    _bend_outline_ends,
    _bend_feature_outline_span,
    _profile_ring_points,
    _polyline_from_ring,
    _is_axis_aligned_pair,
    axis_aligned_rect_bounds,
    expand_axis_aligned_rect_profile,
    _distance_point_to_segment,
    _panel_sign_from_bends,
    _one_sided_panel_sign,
    expand_rectangular_relief_notches,
    is_small_rectangular_relief_hole,
    expand_rect_hole_one_side,
    _rect_hole_growth_signs,
    apply_rectangular_relief_expansion,
    RELIEF_FLANGE_BITE_MM,
    relief_cut_extents_mm,
    minimal_relief_width_mm,
    minimal_relief_depth_past_centerline_mm,
    _interior_run_mm,
    _panel_axis_signs,
    _rectangle_hole,
    ensure_intersection_reliefs,
    suggest_relief_cutouts,
    _point_in_profile,
    profile_bend_indices,
    _bends_are_roughly_parallel,
    _bends_are_collinear,
    collapse_collinear_bend_indices,
    _partition_bend_groups,
    BEND_FEATURE_PIERCE_MM,
    _extended_bend_segment,
    _bend_feature_segment,
    _same_feature_span,
    ARTIFACT_LOOP_MAX_EDGE_MM,
    ARTIFACT_LOOP_MAX_AREA_MM2,
    _closed_loop_metrics,
    _is_drawing_artifact_loop,
    BORDER_NOTCH_MIN_COVERAGE,
    BORDER_NOTCH_MAX_GAP_MM,
    BORDER_NOTCH_EDGE_TOL_MM,
    BORDER_RELIEF_MAX_DISTANCE_MM,
    _ring_orientation_ccw,
    _border_edge_candidates,
    _cut_border_notch,
    convert_border_hole_to_notch,
    _border_intersection_notch,
)
from sw_session import (
    SW_SESSION_CALL_TIMEOUT_SEC,
    InventoryWalkDisconnected,
    SessionOwnershipError,
    SwCallTimeoutError,
    call_with_watchdog,
    connect_application,
    current_lease,
    on_task_sta,
    is_com_server_disconnect,
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
SW_START_CONDITION_SKETCH_PLANE = 0
SW_START_CONDITION_OFFSET = 3


def _com_read(instance: Any, name: str) -> Any:
    """pywin32 may expose parameterless COM members as properties or methods."""
    value = getattr(instance, name)
    # A returned pywin32 dispatch object can itself be callable; invoking it
    # calls its default COM member instead of reading the requested property.
    if '_oleobj_' in getattr(value, '__dict__', {}):
        return value
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
# step6 累计 +3.5mm，才能让浅槽朝板面越过中心线达到现场约 3.4mm。
MAX_AUTO_BEND_ATTEMPTS = 3
MAX_RELIEF_STEPS = MAX_AUTO_BEND_ATTEMPTS - 1


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


def _is_com_disconnect_error(error: BaseException | None) -> bool:
    """判断是否为 SolidWorks/COM 对象与客户端断开。"""
    return is_com_server_disconnect(error)


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


_INVENTORY_METHOD_FALLBACK = {
    "GetNext": ("IGetNext",),
    "GetFirstDocument": ("IGetFirstDocument2",),
}


def _inventory_walk_error(name: str, cause: BaseException | None = None) -> InventoryWalkDisconnected:
    error = InventoryWalkDisconnected(
        "document inventory walk disconnected during "
        + name
        + "; writes refused; ExitApp was not called"
    )
    if cause is not None:
        raise error from cause
    return error


def _invoke_inventory_member(target: Any, attr: str) -> Any:
    """Read one inventory member. Propget first; do not call a property result."""
    descriptor = getattr(type(target), attr, None)
    if isinstance(descriptor, property):
        got = descriptor.fget(target)
        if callable(got):
            raise _inventory_walk_error(attr)
        return got
    if not hasattr(target, attr):
        raise AttributeError(attr)
    value = getattr(target, attr)
    if not callable(value):
        return value
    return value()


def _read_inventory_member(target: Any, name: str, *, required: bool) -> Any:
    """Read ``name``, then the method form (``IGetNext``) when the propget is missing.

    ``DISP_E_MEMBERNOTFOUND`` on ``ModelDoc.GetNext`` is the wrong invoke kind
    or a dead document pointer. It is not a foreign document. The caller rebinds
    this PID and walks again. ``GetType`` may be absent.
    """
    from part_verification import is_member_not_found

    last: BaseException | None = None
    for attr in (name,) + _INVENTORY_METHOD_FALLBACK.get(name, ()):
        try:
            return _invoke_inventory_member(target, attr)
        except AttributeError:
            continue
        except InventoryWalkDisconnected:
            raise
        except Exception as exc:
            last = exc
            if is_member_not_found(exc) or is_com_server_disconnect(exc):
                continue
            raise
    if last is not None and (is_member_not_found(last) or is_com_server_disconnect(last)):
        if not required and is_member_not_found(last) and not is_com_server_disconnect(last):
            return None
        raise _inventory_walk_error(name, last)
    if last is not None:
        raise last
    if not required:
        return None
    raise _inventory_walk_error(name)


def _titles_from_document_array(application: Any, count: int) -> list[str] | None:
    """Use ``GetDocuments`` when it returns the full open set. Skip the GetNext chain."""
    has_array = isinstance(getattr(type(application), "GetDocuments", None), property) or hasattr(
        application, "GetDocuments"
    )
    if not has_array:
        return None
    raw = _read_inventory_member(application, "GetDocuments", required=False)
    if not isinstance(raw, (list, tuple)):
        return None
    if len(raw) != count:
        return None
    titles: list[str] = []
    for document in raw:
        title = _read_inventory_member(document, "GetTitle", required=True)
        if not title or str(title) in titles:
            raise SessionOwnershipError("document inventory has empty/ambiguous titles")
        titles.append(str(title))
    return titles


def _list_open_document_titles(application: Any) -> list[str]:
    """Open-document titles. A mid-walk drop is re-raised for a full rewalk.

    A large readonly assembly can fail ``GetNext`` with ``DISP_E_MEMBERNOTFOUND``
    or drop a document proxy. That is not a shorter count and is not a foreign
    document. ``GetDocuments`` or ``IGetNext`` is tried before the caller rebinds
    this task's PID and starts again at ``GetFirstDocument``.
    """

    count = int(_read_inventory_member(application, "GetDocumentCount", required=True))
    if count < 0 or count > 10000:
        raise SessionOwnershipError("invalid document count")
    via_array = _titles_from_document_array(application, count)
    if via_array is not None:
        return via_array
    current = _read_inventory_member(application, "GetFirstDocument", required=True)
    titles: list[str] = []
    for _ in range(count):
        if current is None:
            raise _inventory_walk_error("GetNext")
        title = _read_inventory_member(current, "GetTitle", required=True)
        _read_inventory_member(current, "GetType", required=False)
        if not title or str(title) in titles:
            raise SessionOwnershipError("document inventory has empty/ambiguous titles")
        titles.append(str(title))
        current = _read_inventory_member(current, "GetNext", required=True)
    if current is not None:
        raise SessionOwnershipError("document enumeration longer than count")
    return titles


def _ordered_open_documents(application: Any) -> list[Any]:
    """Document objects in the same order as ``_list_open_document_titles``."""
    count = int(_read_inventory_member(application, "GetDocumentCount", required=True))
    if count < 0 or count > 10000:
        raise SessionOwnershipError("invalid document count")
    has_array = isinstance(getattr(type(application), "GetDocuments", None), property) or hasattr(
        application, "GetDocuments"
    )
    if has_array:
        raw = _read_inventory_member(application, "GetDocuments", required=False)
        if isinstance(raw, (list, tuple)) and len(raw) == count:
            return list(raw)
    current = _read_inventory_member(application, "GetFirstDocument", required=True)
    documents: list[Any] = []
    for _ in range(count):
        if current is None:
            raise _inventory_walk_error("GetNext")
        documents.append(current)
        current = _read_inventory_member(current, "GetNext", required=True)
    if current is not None:
        raise SessionOwnershipError("document enumeration longer than count")
    return documents


def _dependency_strings(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw] if raw.strip() else []
    try:
        values = list(raw)
    except TypeError:
        text = str(raw).strip()
        return [text] if text else []
    found: list[str] = []
    for item in values:
        if item is None:
            continue
        text = str(item).strip()
        if text:
            found.append(text)
    return found


def _fatal_dependency_error(exc: BaseException) -> bool:
    return isinstance(exc, InventoryWalkDisconnected) or is_com_server_disconnect(exc)


def _call_dependency_method(document: Any, name: str, args: tuple[Any, ...]) -> list[str] | None:
    """Call one dependency API. ``None`` means try the next one."""
    from part_verification import is_member_not_found

    member = getattr(document, name, None)
    descriptor = getattr(type(document), name, None)
    if isinstance(descriptor, property):
        try:
            member = descriptor.fget(document)
        except Exception as exc:
            if _fatal_dependency_error(exc):
                raise
            return None
    if not callable(member):
        return None
    try:
        raw = member(*args) if args else member()
    except TypeError:
        try:
            raw = member()
        except Exception as exc:
            if _fatal_dependency_error(exc):
                raise
            return None
    except Exception as exc:
        if _fatal_dependency_error(exc):
            raise
        if is_member_not_found(exc):
            return None
        return None
    return _dependency_strings(raw)


def _component_dependency_strings(document: Any) -> list[str]:
    member = getattr(document, "GetComponents", None)
    if not callable(member):
        return []
    try:
        raw = member(False)
    except TypeError:
        try:
            raw = member()
        except Exception as exc:
            if _fatal_dependency_error(exc):
                raise
            return []
    except Exception as exc:
        if _fatal_dependency_error(exc):
            raise
        return []
    found: list[str] = []
    for component in list(raw or []):
        path = _read_inventory_member(component, "GetPathName", required=False)
        name = _read_inventory_member(component, "Name2", required=False)
        if not name:
            name = _read_inventory_member(component, "GetTitle", required=False)
        if path:
            found.append(str(path))
        if name:
            found.append(str(name))
    return found


def _drawing_view_dependency_strings(document: Any) -> list[str]:
    member = getattr(document, "GetViews", None)
    if not callable(member):
        return []
    try:
        sheets = member()
    except Exception as exc:
        if _fatal_dependency_error(exc):
            raise
        return []
    found: list[str] = []
    for sheet in list(sheets or []):
        views = sheet if isinstance(sheet, (list, tuple)) else (sheet,)
        for view in views:
            if view is None:
                continue
            path = _read_inventory_member(view, "GetReferencedModelName", required=False)
            if path:
                found.append(str(path))
    return found


def _document_dependency_strings(document: Any) -> list[str]:
    for name, args in (
        ("GetDependencies2", (True, True, True)),
        ("GetDependencies", ()),
    ):
        found = _call_dependency_method(document, name, args)
        if found:
            return found
    found = _component_dependency_strings(document)
    found.extend(_drawing_view_dependency_strings(document))
    return found


def open_document_facts(application: Any) -> list[tuple[str, str, tuple[str, ...]]]:
    """Open documents plus the reference tokens each one reports.

    Titles match ``_list_open_document_titles``. Paths and dependencies are
    optional. A disconnect while reading them is the same inventory failure.
    ``DISP_E_MEMBERNOTFOUND`` on a dependency method tries the next method.
    Tokens are the raw ``GetDependencies2`` name/path pairs, component paths,
    or drawing-view model paths. The caller decides which of those belong to
    the leased document.
    """
    documents = _ordered_open_documents(application)
    facts: list[tuple[str, str, tuple[str, ...]]] = []
    seen: list[str] = []
    for document in documents:
        title = _read_inventory_member(document, "GetTitle", required=True)
        if not title or str(title) in seen:
            raise SessionOwnershipError("document inventory has empty/ambiguous titles")
        seen.append(str(title))
        path = _read_inventory_member(document, "GetPathName", required=False)
        facts.append(
            (
                str(title),
                "" if path is None else str(path),
                tuple(_document_dependency_strings(document)),
            )
        )
    return facts


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
    # Set when SaveAs left a file and a later rebind saw a dead proxy.
    post_save_disconnect: str = ""


@dataclass(frozen=True)
class RollerGenerationResult:
    path: Path
    roller_type: str
    overall_length_mm: float
    barrel_length_mm: float
    bounds: tuple[float, float, float, float, float, float]
    tube_length_mm: float = 0.0
    sprocket_outer_diameter_mm: float | None = None


def _as_interface(module: Any, instance: Any, interface: str) -> Any:
    return getattr(module, interface)(instance._oleobj_)


def _feature_count(model: Any) -> int:
    """Normalize GetFeatureCount across SW COM wrappers exposing method or property."""
    value = model.GetFeatureCount
    from sw_compat.com_access import com_int
    return com_int(value() if callable(value) else value)


def _features(model: Any, module: Any) -> list[Any]:
    features: list[Any] = []
    for index in range(_feature_count(model)):
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
                0.0,
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
    """Explicit SAFEARRAY(double) via sw_math_arrays (PR #17). Raw tuples fail on SW2022."""
    from sw_math_arrays import double_array

    try:
        return double_array(point, 3)
    except ValueError as error:
        raise NativeSketchTransformError("invalid native point array") from error


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
    post_save_note = ""
    try:
        lease = current_lease()
        # The task STA already owns the apartment. A nested CoUninitialize
        # drops that count and the next post-save call sees a dead proxy.
        if not getattr(lease, "com_initialized", False):
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
            from sw_feature_calls import sheet_metal_through_cut

            # NormalCut=True only on this sheet-metal hole. Solid cuts use solid_blind_cut.
            hole_cut = sheet_metal_through_cut(feature_manager)
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
        if lease is not None:
            lease.generation_saved = True
        logger.info("钣金零件已保存：%s", output)
        from part_verification import (
            PostSaveComDisconnect,
            PostSaveRebindFailed,
            read_active_document,
            read_com_property,
            rebind_model_after_save,
        )

        def _wrap_model(raw):
            if raw is None:
                return None
            return _as_interface(type_library, raw, "IModelDoc2")

        def _active_model(app):
            # Property only. Calling ActiveDoc on an ISldWorks wrapper is
            # DISP_E_MEMBERNOTFOUND and must not fail the saved part.
            return _wrap_model(read_active_document(app))

        def _open_saved(app):
            from part_verification import is_member_not_found
            saved_path = str(output.resolve())
            found = None
            by_name = getattr(app, "GetOpenDocumentByName", None)
            if callable(by_name):
                try:
                    found = by_name(saved_path)
                except Exception as error:
                    if not is_member_not_found(error):
                        raise
                    found = None
            if found is None:
                opener = getattr(app, "OpenDoc6", None)
                if callable(opener):
                    opened = opener(
                        saved_path, SW_DOCUMENT_TYPE_PART, SW_OPEN_DOC_SILENT, "", 0, 0
                    )
                    found = opened[0] if isinstance(opened, tuple) else opened
            if found is None:
                # Dynamic Dispatch still needs ActiveDoc(). An early-bound
                # wrapper raises DISP_E_MEMBERNOTFOUND here; that is not fatal.
                try:
                    found = read_com_property(app, "ActiveDoc")
                except Exception as error:
                    if not is_member_not_found(error):
                        raise
                    found = None
            return _wrap_model(found)

        def _saved_title(rebound):
            try:
                return read_com_property(rebound, "GetTitle")
            except Exception as error:
                from part_verification import is_member_not_found
                if is_member_not_found(error):
                    return output.name
                raise

        try:
            model, rebound_title = rebind_model_after_save(
                typed_solidworks,
                _active_model,
                _saved_title,
                lease=lease,
                open_saved=_open_saved,
            )
        except (PostSaveComDisconnect, PostSaveRebindFailed) as error:
            if not output.is_file() or output.stat().st_size == 0:
                raise
            post_save_note = str(error)
            logger.warning(
                "post-save rebind failed; keeping %s; ExitApp was not called: %s",
                output,
                error,
            )
        else:
            if (
                lease is not None
                and document_title
                and rebound_title != document_title
                and lease.is_owned_title(document_title)
            ):
                lease.rename_owned(document_title, rebound_title)
            document_title = rebound_title
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
            post_save_disconnect=post_save_note,
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
                model=None if post_save_note else model,
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
            completed = not selected or result.auto_bent
            trace.append(dict(attempt=attempts, relief_step=step,
                relief_extra_mm=rect_relief_extra_mm(step), status="completed" if completed else "degraded",
                completed_bend_count=result.bend_count, relief_slot_count=result.relief_slot_count,
                bend_group_attempts=list(result.bend_group_attempts)))
            return replace(result, auto_bend_attempts=attempts, bend_attempts=tuple(trace),
                           auto_bend_failed_count=max(0, len(selected) - result.bend_count),
                           auto_bend_abandoned=not completed)
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
        if not getattr(lease, "com_initialized", False):
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
                    feature_count = _feature_count(model)
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
                    steps = _feature_count(model) - feature_count
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


# Reused offline recognition/geometry contracts from PR #43/#62.
_COM_DISCONNECT_HRESULTS = frozenset(
    {
        -2147220995,  # CO_E_OBJNOTCONNECTED (Issue39 native evidence)
        -2147417848,  # 0x80010108 RPC_E_DISCONNECTED
        -2147023174,  # 0x800706BA RPC_S_SERVER_UNAVAILABLE
        -2147418111,  # 0x80010001 RPC_E_CALL_REJECTED（偶发，当断连处理）
        -2147467261,  # 0x80004003 E_POINTER（对象已释放）
    }
)


