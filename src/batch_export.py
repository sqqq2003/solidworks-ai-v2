# -*- coding: utf-8 -*-
"""一键识别全部钣金件并导出 SolidWorks 零件。"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Callable, Sequence

from bend_allowance import BendAllowanceSpec
from cad_analyzer import DrawingAnalysis, primitive_bounds
from drawing_notes import annotate_sheet_parts, reading_order
from paths_local import ensure_dirs, export_dir_for
from profile_selection import candidate_profile_indices, contained_hole_indices, profile_area
from solidworks_generator import (
    GenerationResult,
    generate_sheet_metal_with_relief_retries,
    profile_bend_indices,
)
from sw_session import SessionOwnershipError, recycle_exclusive_session
from resume_manifest import fingerprint, verified_output, write_record

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[str], None]


@dataclass(frozen=True)
class SheetPartJob:
    profile_index: int
    bend_indices: tuple[int, ...]
    area_mm2: float
    label: str
    quantity: int = 1
    thickness_mm: float | None = None
    thickness_source: str = ""
    quantity_source: str = ""
    # 清单里显示的尺寸文字，例如 420×180。只用于界面展示。
    size_hint: str = ""


def format_sheet_part_name(sequence: int, quantity: int, thickness_mm: float) -> str:
    """排序后的零件文件名，例如 ``01×2 2mm.SLDPRT``。"""

    if sequence < 1:
        raise ValueError("序号必须从 1 开始。")
    count = max(int(quantity), 1)
    return f"{sequence:02d}×{count} {thickness_mm:g}mm.SLDPRT"


def resolved_part_thickness(job: SheetPartJob, default_mm: float) -> float:
    """分区大字厚度优先；没有则用界面默认，并写明来源。"""

    if job.thickness_mm is not None:
        logger.info(
            "%s 厚度 %.3g mm 来自分区大字「%s」",
            job.label,
            job.thickness_mm,
            job.thickness_source or "（未记录原文）",
        )
        return job.thickness_mm
    logger.info(
        "%s 未找到所在行/区顶部大字厚度，使用界面默认 %.3g mm",
        job.label,
        default_mm,
    )
    return default_mm


def _unique_part_path(out_root: Path, filename: str) -> Path:
    """主名保持 ``01×2 2mm``，撞名时只在后面加短后缀。"""

    path = out_root / filename
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    number = 2
    while True:
        candidate = out_root / f"{stem}_{number}{suffix}"
        if not candidate.exists():
            return candidate
        number += 1


@dataclass
class SheetPartResult:
    job: SheetPartJob
    ok: bool
    path: Path | None = None
    auto_bent: bool = False
    # 自动折弯试满上限仍失败，已改为平板 + 折弯线草图（等人手折）。
    auto_bend_abandoned: bool = False
    auto_bend_attempts: int = 0
    bend_count: int = 0
    # 自动折弯里没折上的条数（>0 表示折了一部分，其余留折弯线手折）。
    bend_failed_count: int = 0
    error: str = ""
    elapsed_sec: float = 0.0
    cad_imported: bool = False
    bend_sketch_line_count: int = 0
    skipped: bool = False
    resume_verified: bool = False

    @property
    def status(self) -> str:
        if not self.ok:
            return "failed"
        if self.skipped:
            return "passed" if self.resume_verified else "unverified_existing"
        if self.auto_bend_abandoned or self.bend_failed_count:
            return "degraded"
        return "passed"



# SolidWorks 连续建很多零件会持续吃内存。超过阈值时只允许回收本任务
# 已经证明独占的会话；证明不了就拒绝，不关闭、不退出用户正在用的实例。
SW_RECYCLE_PRIVATE_MB = 3000
SW_RECYCLE_MIN_COMMIT_FREE_MB = 1500


def _solidworks_memory_mb() -> tuple[float | None, float | None]:
    """(SLDWORKS 私有内存 MB, 系统可用提交内存 MB)；读不到返回 None。"""

    import subprocess

    script = (
        "$p=Get-Process SLDWORKS -ErrorAction SilentlyContinue | Select -First 1;"
        "$o=Get-CimInstance Win32_OperatingSystem;"
        "if($p){[int]($p.PrivateMemorySize64/1MB)}else{-1};"
        "[int]($o.FreeVirtualMemory/1024)"
    )
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout.split()
        private = float(out[0])
        return (private if private >= 0 else None), float(out[1])
    except Exception:  # noqa: BLE001
        return None, None


def _recycle_solidworks_if_heavy(progress: ProgressCallback | None = None) -> bool:
    """Refuse to restart SolidWorks unless this task proved an exclusive session.

    The memory reading is diagnostic only. It is not a process id, and it is
    not permission to close documents or stop an instance this task did not spawn.
    """

    private, commit_free = _solidworks_memory_mb()
    if private is None:
        return False
    if private < SW_RECYCLE_PRIVATE_MB and (
        commit_free is None or commit_free >= SW_RECYCLE_MIN_COMMIT_FREE_MB
    ):
        return False
    logger.warning(
        "SolidWorks 内存过高（私有 %.0f MB，系统可用提交 %s MB）。"
        "仅当本任务已证明独占会话时才回收。",
        private,
        commit_free,
    )
    if progress:
        progress(f"SolidWorks 内存 {private:.0f} MB，检查是否可以安全回收会话…")
    return recycle_exclusive_session(
        private_mb=private,
        commit_free_mb=commit_free,
        progress=progress,
    )


def part_bend_indices(analysis: DrawingAnalysis, profile_index: int) -> tuple[int, ...]:
    """该件的折弯线（并集规则；剔除内孔中心十字线）。单件生成与批量共用。"""

    profile = analysis.profiles[profile_index]
    holes = [
        analysis.profiles[i]
        for i in contained_hole_indices(analysis.profiles, profile_index)
    ]
    return profile_bend_indices(profile, analysis.bend_lines, holes)


def discover_sheet_parts(analysis: DrawingAnalysis) -> tuple[SheetPartJob, ...]:
    """外轮廓候选。顺序从上到下、从左到右；厚度和件数从图纸文字读取。"""

    located: list[tuple[int, tuple[float, float, float, float]]] = []
    pending: dict[int, tuple[tuple[int, ...], float]] = {}
    for profile_index in candidate_profile_indices(
        analysis.profiles, include_enclosed=False
    ):
        profile = analysis.profiles[profile_index]
        bounds = primitive_bounds(profile)
        located.append((profile_index, bounds))
        pending[profile_index] = (
            part_bend_indices(analysis, profile_index),
            profile_area(profile),
        )
    annotations = annotate_sheet_parts(located, list(analysis.text_entities))
    jobs: list[SheetPartJob] = []
    for sequence, profile_index in enumerate(reading_order(located), start=1):
        bends, area = pending[profile_index]
        note = annotations.get(profile_index)
        bounds = next(b for i, b in located if i == profile_index)
        size_hint = f"{bounds[2] - bounds[0]:.0f}×{bounds[3] - bounds[1]:.0f}"
        jobs.append(
            SheetPartJob(
                profile_index=profile_index,
                bend_indices=bends,
                area_mm2=area,
                label=f"件{sequence:02d}_#{profile_index + 1}",
                quantity=1 if note is None else note.quantity,
                thickness_mm=None if note is None else note.thickness_mm,
                thickness_source="" if note is None else note.thickness_source,
                quantity_source="" if note is None else note.quantity_source,
                size_hint=size_hint,
            )
        )
    return tuple(jobs)


def export_all_sheet_parts(
    analysis: DrawingAnalysis,
    *,
    thickness_mm: float,
    radius_mm: float,
    angle_degrees: float = 90.0,
    flip_direction: bool = False,
    bend_allowance: BendAllowanceSpec | None = None,
    auto_bend: bool = True,
    output_dir: Path | None = None,
    progress: ProgressCallback | None = None,
    skip_existing: bool = False,
    on_result: Callable[[SheetPartResult], None] | None = None,
    selected_labels: Sequence[str] | None = None,
    jobs: Sequence[SheetPartJob] | None = None,
) -> list[SheetPartResult]:
    """对图上每块外轮廓导出一个 SLDPRT；单件失败跳过并继续。

    skip_existing=True：输出文件已存在的件视为已完成直接跳过（断点续跑）。
    on_result：每件完成后立即回调（用于逐件落盘进度日志）。
    selected_labels：只导这些编号（确认窗里勾选的）；None 表示全导。
    jobs：复用调用方已经识别好的清单，省一次重复识别。
    """

    ensure_dirs()
    out_root = output_dir or export_dir_for(analysis.path.stem)
    out_root.mkdir(parents=True, exist_ok=True)
    all_jobs = tuple(jobs) if jobs is not None else discover_sheet_parts(analysis)
    # 编号按整张图排好序的序号算，勾掉一件不影响其余件的文件名，
    # 否则中途重开一次、勾选变了，已导出的文件就对不上号了。
    numbered = list(enumerate(all_jobs, start=1))
    if selected_labels is not None:
        wanted = set(selected_labels)
        numbered = [entry for entry in numbered if entry[1].label in wanted]
        dropped = len(all_jobs) - len(numbered)
        if dropped:
            logger.info("一键全部导出：确认窗里取消了 %d 件，实际导出 %d 件", dropped, len(numbered))
            if progress:
                progress(f"已取消 {dropped} 件，只导出勾选的 {len(numbered)} 件")
    if not numbered:
        if progress:
            progress("没有勾选任何件，未导出。")
        return []
    if progress:
        progress(f"识别到 {len(all_jobs)} 块钣金件，本次导出 {len(numbered)} 件，输出目录 {out_root}")
    logger.info(
        "一键全部导出：图纸=%s 件数=%d（导出 %d）折弯线总数=%d 输出=%s",
        analysis.path.name,
        len(all_jobs),
        len(numbered),
        len(analysis.bend_lines),
        out_root,
    )
    import solidworks_generator as _swg

    previous_close = _swg.CLOSE_SAVED_DOCS
    _swg.CLOSE_SAVED_DOCS = True
    try:
        return _export_jobs(
            analysis, numbered, out_root, thickness_mm, radius_mm, angle_degrees,
            flip_direction, bend_allowance, auto_bend, progress,
            skip_existing, on_result,
        )
    finally:
        _swg.CLOSE_SAVED_DOCS = previous_close


def _export_jobs(
    analysis, numbered_jobs, out_root, thickness_mm, radius_mm, angle_degrees,
    flip_direction, bend_allowance, auto_bend, progress,
    skip_existing=False, on_result=None,
) -> list[SheetPartResult]:
    results: list[SheetPartResult] = []
    for sequence, job in numbered_jobs:
        part_thickness = resolved_part_thickness(job, thickness_mm)
        filename = format_sheet_part_name(sequence, job.quantity, part_thickness)
        canonical = out_root / filename
        resume_key = fingerprint(Path(analysis.path), dict(
            job=asdict(job), thickness_mm=part_thickness, radius_mm=radius_mm,
            angle_degrees=angle_degrees, flip_direction=flip_direction,
            bend_allowance=asdict(bend_allowance) if bend_allowance else None,
            auto_bend=auto_bend, primitives=[asdict(p) for p in analysis.primitives],
            profiles=[asdict(p) for p in analysis.profiles],
            bend_lines=[asdict(p) for p in analysis.bend_lines],
        ), Path(__file__).resolve().parent)
        existing = verified_output(canonical, resume_key) if skip_existing else None
        if existing is not None:
            item = SheetPartResult(job=job, ok=True, path=existing, skipped=True,
                                   resume_verified=True,
                                   auto_bent=auto_bend and bool(job.bend_indices),
                                   bend_count=len(job.bend_indices) if auto_bend else 0)
            logger.info("已存在，跳过 %s：%s", job.label, canonical)
            if progress:
                progress(f"{job.label} 已存在，跳过")
            results.append(item)
            if on_result:
                try:
                    on_result(item)
                except Exception:
                    logger.exception("on_result callback failed for resumed artifact")
            continue
        try:
            _recycle_solidworks_if_heavy(progress)
        except SessionOwnershipError as error:
            logger.error(
                "拒绝回收 SolidWorks 会话（不关闭、不退出、不结束未知实例）：%s",
                error,
            )
            if progress:
                progress(f"拒绝重启 SolidWorks：{error}")
        except Exception:  # noqa: BLE001
            logger.exception("SolidWorks 内存检查失败，已跳过会话回收")
        output = _unique_part_path(out_root, filename)
        if progress:
            progress(
                f"导出 {filename}（轮廓 #{job.profile_index + 1}，"
                f"折弯 {len(job.bend_indices)} 条，板厚 {part_thickness:g} mm）…"
            )
        t0 = time.monotonic()
        try:
            result: GenerationResult = generate_sheet_metal_with_relief_retries(
                analysis,
                job.profile_index,
                job.bend_indices,
                part_thickness,
                radius_mm,
                angle_degrees,
                output,
                flip_direction=flip_direction,
                bend_allowance=bend_allowance,
                auto_bend=auto_bend and bool(job.bend_indices),
                progress=(
                    (lambda text, label=job.label: progress(f"{label}：{text}"))
                    if progress
                    else None
                ),
            )
            item = SheetPartResult(
                job=job,
                ok=True,
                path=result.path,
                auto_bent=result.auto_bent,
                auto_bend_abandoned=result.auto_bend_abandoned,
                auto_bend_attempts=result.auto_bend_attempts,
                bend_count=result.bend_count,
                bend_failed_count=result.auto_bend_failed_count,
                elapsed_sec=time.monotonic() - t0,
                cad_imported=result.cad_imported,
                bend_sketch_line_count=result.bend_sketch_line_count,
            )
            write_record(canonical, Path(result.path), resume_key, item.status)
            logger.info(
                "导出成功 %s path=%s auto_bent=%s bends=%d 原样导入=%s 折弯线草图=%d/%d %.1fs",
                job.label,
                result.path,
                result.auto_bent,
                result.bend_count,
                result.cad_imported,
                result.bend_sketch_line_count,
                len(job.bend_indices),
                item.elapsed_sec,
            )
            if (
                job.bend_indices
                and not result.auto_bent
                and result.bend_sketch_line_count != len(job.bend_indices)
            ):
                logger.warning(
                    "%s 平板件折弯线草图 %d 条 ≠ 识别 %d 条",
                    job.label,
                    result.bend_sketch_line_count,
                    len(job.bend_indices),
                )
        except Exception as error:  # noqa: BLE001 - 单件失败不中断整批
            item = SheetPartResult(
                job=job,
                ok=False,
                error=str(error),
                elapsed_sec=time.monotonic() - t0,
            )
            logger.exception("导出失败 %s：%s", job.label, error)
            if progress:
                progress(f"{job.label} 失败：{error}")
        results.append(item)
        if on_result:
            try:
                on_result(item)
            except Exception:  # noqa: BLE001
                logger.exception("on_result 回调失败")
    ok = sum(1 for item in results if item.ok)
    manual = [item for item in results if item.ok and item.auto_bend_abandoned]
    partial = [
        item
        for item in results
        if item.ok and item.bend_failed_count and not item.auto_bend_abandoned
    ]
    if progress:
        if manual or partial:
            parts = [f"完成：成功 {ok}/{len(results)}"]
            if manual:
                parts.append(
                    f"其中 {len(manual)} 件自动折弯失败已改手折（折弯线草图已留）"
                )
            if partial:
                parts.append(
                    f"{len(partial)} 件部分折弯未成（折弯线已留）"
                )
            parts.append(f"目录 {out_root}")
            progress("；".join(parts[:-1]) + "，" + parts[-1])
        else:
            progress(f"完成：成功 {ok}/{len(results)}，目录 {out_root}")
    if manual:
        logger.warning(
            "自动折弯放弃，已改手折的件：%s",
            "、".join(item.job.label for item in manual),
        )
    if partial:
        logger.warning(
            "部分折弯未成的件：%s",
            "、".join(
                f"{item.job.label}({item.bend_failed_count}条)"
                for item in partial
            ),
        )
    return results
