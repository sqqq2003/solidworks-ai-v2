"""无界面入口：把现有识别 / 建模管线包成命令行，供 SolidWorks 插件调用。

用法::

    python sw_tool_cli.py --mode sheet  --input 图.dxf --out 件.SLDPRT
    python sw_tool_cli.py --mode roller --input 图.dxf --out 件.SLDPRT [--variant N]
    python sw_tool_cli.py --mode sheet  --input 图.dxf --analyze-only

标准输出是「一行一个 JSON」，插件逐行解析::

    {"event": "progress", "message": "..."}
    {"event": "done", "kind": "sheet", "path": "...", "message": "..."}
    {"event": "error", "message": "...", "detail": "..."}

返回码：0 成功，1 业务失败（含 error 事件），2 参数错误，3 仅退化平板/参考线。
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
import logging
import math
import json
import sys
from pathlib import Path

from bend_allowance import resolve_bend_allowance_spec
from cad_analyzer import analyze_cad_file
from logging_setup import configure_logging, log_file_path
from profile_selection import outermost_containing_profile_index, profile_area
from roller_spec import RollerSpecError, spec_from_variant
from solidworks_generator import (
    generate_roller_part,
    generate_sheet_metal,
    generate_sheet_metal_with_relief_retries,
    profile_bend_indices,
)


LOGGER = logging.getLogger("sw_tool_cli")
from sheet_safety import bend_note_warning


def emit(event: str, **payload: object) -> None:
    from app_logging import get_journal
    get_journal().record('cli_'+event,level='ERROR' if event=='error' else 'INFO',**payload)
    payload["event"] = event
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, default=lambda value: sorted(value) if isinstance(value,(set,frozenset)) else str(value)) + "\n")
    sys.stdout.flush()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="钣金 / 滚筒零件一键生成（SolidWorks 插件后端）")
    parser.add_argument("--mode", choices=("sheet", "roller", "turned"), required=True)
    parser.add_argument("--input", required=True, help="DWG / DXF 图纸路径")
    parser.add_argument("--out", help="输出 .SLDPRT 路径；--analyze-only 时可省略")
    parser.add_argument("--plan-only", action="store_true", help="只输出特征计划；DWG 在显式指定 --sw-exe 时允许转换，不生成零件")
    parser.add_argument("--allow-inferred", action="store_true", help="明确允许滚筒通用默认值；这些不是 OEM 实测数据")
    parser.add_argument("--verify-reopen", action="store_true", help="生成后关闭重开并核对实体尺寸")
    parser.add_argument("--inspect-cylinders", action="store_true",
                        help="配合 --verify-reopen 读回原生圆柱面尺寸；不代表孔槽验收")
    parser.add_argument("--analyze-only", action="store_true", help="只识别图纸并汇报，不建模")
    parser.add_argument("--profile", type=int, default=None, help="钣金：轮廓序号（从 1 开始）")
    parser.add_argument("--uniform-scale", type=float, default=None, help="钣金轮廓与孔按比例缩放；板厚不跟随")
    parser.add_argument("--preserve-circle-holes",action='store_true',help="缩放时圆孔大小保持不变，孔心位置随外形缩放")
    parser.add_argument("--thickness", type=float, default=1.2, help="钣金：板厚 mm")
    parser.add_argument("--radius", type=float, default=1.2, help="钣金：折弯半径 mm")
    parser.add_argument("--angle", type=float, default=90.0, help="钣金：折弯角度")
    parser.add_argument("--sw-exe", type=Path, default=None,
                        help="启动此 SLDWORKS.exe 并验证新 PID 的独占任务会话")
    parser.add_argument("--k-factor", type=float, default=None,
                        help="钣金：显式 K 因子 0~1，创建时传入并要求原生读回一致")
    parser.add_argument("--flip", action="store_true", help="钣金：反向折弯")
    parser.add_argument(
        "--no-auto-bend",
        dest="auto_bend",
        action="store_false",
        help="钣金：只出平板 + 折弯线草图（默认直接折弯）",
    )
    parser.add_argument("--variant", type=int, default=0, help="滚筒：规格序号（从 0 开始）")
    parser.add_argument(
        "--batch",
        action="store_true",
        help="钣金：一键批量导出整张图的全部外轮廓零件（串行，单件失败继续）",
    )
    parser.add_argument(
        "--batch-out-dir",
        type=Path,
        default=None,
        help="钣金批量：输出目录（--batch 时必填，新目录）",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="把识别 / 建模的详细日志打到标准错误，便于排查",
    )
    parser.set_defaults(auto_bend=True)
    parser.add_argument('--batch-label', action='append', default=None,
                        help='批量：只导出该标签；可重复指定；未知标签直接拒绝')
    parser.add_argument('--skip-existing', action='store_true',
                        help='批量续跑：仅跳过输入、参数、源码及输出哈希均匹配的完成件')
    return parser


def _largest_closed_profile_index(analysis) -> int:
    best_index = None
    best_area = -1.0
    for index, profile in enumerate(analysis.profiles):
        if not getattr(profile, "closed", False):
            continue
        area = profile_area(profile)
        if area > best_area:
            best_index, best_area = index, area
    if best_index is None:
        raise ValueError("图纸里没有找到闭合轮廓，无法生成钣金。")
    return best_index


def describe_drawing(analysis) -> dict[str, object]:
    from batch_export import part_bend_indices, stamping_target_indices
    from cad_analyzer import primitive_bounds
    from profile_selection import candidate_profile_indices
    located = [(i, primitive_bounds(analysis.profiles[i]))
               for i in candidate_profile_indices(analysis.profiles, include_enclosed=False)]
    stamping_targets = stamping_target_indices(analysis, located)
    profiles = []
    for index, profile in enumerate(analysis.profiles):
        if not getattr(profile, "closed", False):
            continue
        bends = part_bend_indices(analysis, index, stamping_targets=stamping_targets)
        profiles.append(
            {
                "index": index + 1,
                "area_mm2": round(profile_area(profile), 2),
                "bend_count": len(bends),
                "stamping_line": index in stamping_targets,
            }
        )
    profiles.sort(key=lambda item: item["area_mm2"], reverse=True)
    variants = [
        {
            "index": position,
            "roller_type": variant.roller_type,
            "overall_length_mm": variant.overall_length_mm,
            "outer_diameter_mm": variant.outer_diameter_mm,
            "shaft_diameter_mm": variant.shaft_diameter_mm,
            "geometry_inferred": getattr(variant,"geometry_inferred",False),
        }
        for position, variant in enumerate(analysis.roller_variants)
    ]
    return {
        "path": str(analysis.path),
        "profile_count": len(profiles),
        "bend_line_count": len(analysis.bend_lines),
        "stamping_line_count": sum(len(profile_bend_indices(analysis.profiles[i], analysis.bend_lines))
                                   for i in stamping_targets),
        "line_count_scope": "raw_red_line_candidates; per-profile bend counts exclude marking lines",
        "profiles": profiles,
        "roller_variants": variants,
        "warnings": [warning] if (warning := bend_note_warning(analysis)) else [],
    }


def run_sheet(args: argparse.Namespace) -> int:
    emit("progress", message="正在识别图纸…")
    analysis = analyze_cad_file(args.input)

    if args.analyze_only:
        emit("analysis", **describe_drawing(analysis))
        return 0

    warning=bend_note_warning(analysis)
    if warning:
        emit('error',message=warning)
        return 1

    scale=getattr(args,'uniform_scale',None)
    preserve_holes=getattr(args,'preserve_circle_holes',False)
    if preserve_holes and scale is None:raise ValueError('保持孔径需要填写缩放倍数')
    if scale is not None:
        if not math.isfinite(scale) or scale<=0:raise ValueError('缩放比例必须是正的有限数值')
        from cad_analyzer import primitive_bounds
        from profile_edit import resize_profile_dimensions
        index=args.profile-1 if args.profile is not None else _largest_closed_profile_index(analysis)
        if not 0<=index<len(analysis.profiles):raise ValueError('轮廓序号超出范围')
        if outermost_containing_profile_index(analysis.profiles,index)!=index:
            raise ValueError('请选择零件外轮廓，而不是内部孔')
        bounds=primitive_bounds(analysis.profiles[index])
        analysis=resize_profile_dimensions(analysis,index,width_mm=(bounds[2]-bounds[0])*scale,height_mm=(bounds[3]-bounds[1])*scale,preserve_circle_holes=preserve_holes)
        hole_rule='圆孔孔径不变、孔心随外形缩放' if preserve_holes else '孔槽同步缩放'
        emit('progress',message=f'已按 {scale:g} 倍缩放所选轮廓；{hole_rule}；板厚不变，结果待复核。')

    if args.plan_only:
        from sheet_metal_pipeline import build_plan
        index = args.profile - 1 if args.profile is not None else _largest_closed_profile_index(analysis)
        plan = build_plan(analysis, profile_index=index, thickness_mm=args.thickness,
            radius_mm=args.radius, angle_degrees=args.angle, k_factor=args.k_factor,
            flip_direction=args.flip, bends_confirmed=False)
        emit("plan",kind="sheet",plan=plan,cad_executed=False)
        return 3 if plan['pending'] else 0
    if not args.out:
        emit("error", message="缺少 --out 输出路径。")
        return 2

    if args.profile is None:
        profile_index = _largest_closed_profile_index(analysis)
    else:
        profile_index = args.profile - 1
        if not 0 <= profile_index < len(analysis.profiles):
            emit("error", message=f"轮廓序号 {args.profile} 超出范围。")
            return 2
    profile_index = outermost_containing_profile_index(analysis.profiles, profile_index)

    profile = analysis.profiles[profile_index]
    from batch_export import part_bend_indices

    bends = part_bend_indices(analysis, profile_index)
    emit(
        "progress",
        message=f"轮廓 #{profile_index + 1}，折弯线 {len(bends)} 条，开始生成钣金…",
    )

    allowance = None
    if args.k_factor is not None:
        allowance, _ = resolve_bend_allowance_spec(
            thickness_mm=args.thickness, radius_mm=args.radius,
            angle_degrees=args.angle, mode="k_factor", k_factor=args.k_factor)
    result = generate_sheet_metal_with_relief_retries(
        analysis,
        profile_index,
        bends,
        args.thickness,
        args.radius,
        args.angle,
        args.out,
        flip_direction=args.flip,
        auto_bend=args.auto_bend,
        bend_allowance=allowance,
        cad_import=False if scale is not None else None,
    )
    if allowance is not None and (
        not result.bend_allowance_verified
        or result.k_factor_readback is None
        or not math.isclose(result.k_factor_readback, allowance.k_factor, abs_tol=1e-8)
    ):
        raise RuntimeError("requested K factor was not verified; refusing success event")
    verification = None
    if args.verify_reopen and not result.auto_bend_abandoned:
        from part_verification import verify_saved_part
        verification = verify_saved_part(result.path, **({'inspect_cylinders': True}
                                         if getattr(args, 'inspect_cylinders', False) else {}))
    emit(
        "done",
        kind="sheet",
        reopen=verification,
        mechanical_acceptance="unverified",
        status="degraded" if result.auto_bend_abandoned else "passed",
        auto_bend_attempts=result.auto_bend_attempts,
        requested_k_factor=args.k_factor,
        k_factor_readback=result.k_factor_readback,
        bend_allowance_verified=result.bend_allowance_verified,
        relief_step_used=result.relief_step_used,
        bend_attempts=result.bend_attempts,
        auto_bend_failed_count=result.auto_bend_failed_count,
        bend_count=result.bend_count,
        path=str(result.path),
        message=f"钣金零件已生成：{Path(result.path).name}",
    )
    return 3 if result.auto_bend_abandoned else 0


def run_sheet_batch(args: argparse.Namespace) -> int:
    """一键批量导出整张钣金图的全部外轮廓零件（串行，单件失败继续）。

    复用 batch_export.export_all_sheet_parts 的识别与串行安全逻辑，输出一行
    一个 JSON 事件。单件失败只标记该件失败并继续下一件，不中断整批；但未知
    原生失败（会话断连等）仍按现有安全策略停止后续 CAD 写入。
    """
    emit("progress", message="正在识别图纸全部钣金轮廓…")
    analysis = analyze_cad_file(args.input)

    # 折弯线矛盾拦截：图纸说红线是折弯线但识别不到时，禁止批量生成。
    warning = bend_note_warning(analysis)
    if warning:
        emit("error", message=warning)
        return 1

    if not args.batch_out_dir:
        emit("error", message="批量导出需要 --batch-out-dir 指定新输出目录。")
        return 2
    out_root = Path(args.batch_out_dir).expanduser().resolve()
    skip_existing = bool(getattr(args, 'skip_existing', False))
    if out_root.exists() and any(out_root.iterdir()) and not skip_existing:
        emit("error", message=f"输出目录 {out_root} 已存在且非空；请指定新目录或明确选择断点续跑。")
        return 2
    from batch_export import export_all_sheet_parts, discover_sheet_parts

    jobs = discover_sheet_parts(analysis)
    selected = getattr(args, 'batch_label', None)
    available = {job.label for job in jobs if not job.text_frame}
    if selected is not None and (not selected or set(selected) - available):
        raise ValueError('批量选择包含未知零件，请重新识别和确认。')
    chosen = [job for job in jobs if not job.text_frame and (selected is None or job.label in selected)]
    allowance = None
    if any(job.bend_indices for job in chosen) and args.auto_bend:
        if args.k_factor is None:
            raise ValueError('批量折弯必须显式提供本单已确认的 --k-factor，不使用通用默认值。')
        allowance, _ = resolve_bend_allowance_spec(thickness_mm=args.thickness,
            radius_mm=args.radius, angle_degrees=args.angle, mode='k_factor', k_factor=args.k_factor)
    out_root.mkdir(parents=True, exist_ok=True)
    emit(
        "progress",
        message=f"识别到 {len(jobs)} 块候选轮廓，开始串行导出到 {out_root}…",
    )

    results = export_all_sheet_parts(
        analysis,
        thickness_mm=args.thickness,
        radius_mm=args.radius,
        angle_degrees=args.angle,
        flip_direction=args.flip,
        auto_bend=args.auto_bend,
        bend_allowance=allowance,
        uniform_scale=args.uniform_scale,
        preserve_circle_holes=args.preserve_circle_holes,
        jobs=jobs,
        selected_labels=selected,
        skip_existing=skip_existing,
        output_dir=out_root,
        progress=lambda text: emit("progress", message=text),
    )

    ok = sum(1 for item in results if item.ok)
    failed = [item for item in results if not item.ok]
    unattempted = max(0, len(chosen) - len(results))
    # 单件失败不 emit error（否则 execute_job 会把整批判为 failed）；
    # 通过 done 事件的 failed 计数与 status=degraded 表达局部失败。
    emit(
        "done",
        kind="sheet_batch",
        total=len(results),
        ok=ok,
        failed=len(failed),
        unattempted=unattempted,
        output_dir=str(out_root),
        mechanical_acceptance="unverified",
        status="degraded" if failed or unattempted or any(item.status != 'passed' for item in results) else "passed" if results else "review_required",
        parts=[
            {
                "label": item.job.label,
                "quantity": item.job.quantity,
                "quantity_source": item.job.quantity_source,
                "quantity_confirmed": False,
                "thickness_source": item.job.thickness_source,
                "path": str(item.path) if item.path else None,
                "status": item.status,
                "bend_count": item.bend_count,
                "error": item.error if not item.ok else "",
            }
            for item in results
        ],
        message=(
            f"批量导出完成：成功 {ok}/{len(results)}，目录 {out_root}"
            if not failed
            else f"批量导出完成：成功 {ok}/{len(results)}（{len(failed)} 件失败），目录 {out_root}"
        ),
    )
    return 3 if failed or unattempted or not results or any(item.status != 'passed' for item in results) else 0


def run_roller(args: argparse.Namespace) -> int:
    emit("progress", message="正在识别滚筒规格…")
    analysis = analyze_cad_file(args.input)

    if args.analyze_only:
        emit("analysis", **describe_drawing(analysis))
        return 0

    if not args.out and not args.plan_only:
        emit("error", message="缺少 --out 输出路径。")
        return 2
    if not analysis.roller_variants:
        emit("error", message="这张图里没识别到滚筒规格，无法生成滚筒零件。")
        return 1
    if not 0 <= args.variant < len(analysis.roller_variants):
        emit("error", message=f"规格序号 {args.variant} 超出范围。")
        return 2

    variant = analysis.roller_variants[args.variant]
    if getattr(variant,'geometry_inferred',False) and not args.plan_only:
        emit('error',message='滚筒规格仅由几何推测，可能是其他零件；请先核对并使用明确标注的滚筒规格，不能直接生成。')
        return 1
    missing = [name for name in ('overall_length_mm','outer_diameter_mm','wall_thickness_mm',
        'shaft_diameter_mm','shaft_projection_mm','shaft_thread_designation') if getattr(variant,name) is None]
    if variant.is_powered:
        missing.extend(name for name in ('sprocket_teeth','chain_pitch_mm') if getattr(variant,name) is None)
    elif variant.shaft_step_diameter_mm is None:
        missing.append('shaft_step_diameter_mm')
    missing = sorted(set(missing) | set(variant.inferred_fields))
    if missing and not args.allow_inferred:
        emit("plan",kind="roller",status="review_required",pending=missing,
             source_variant=asdict(variant),cad_executed=False,
             message="缺少确认尺寸；核对计划后才可显式允许通用默认值")
        return 3
    try:
        spec = spec_from_variant(variant)
    except RollerSpecError as error:
        emit("error", message=str(error))
        return 1
    if args.plan_only:
        emit("plan",kind="roller",plan=asdict(spec),pending=missing,
             inferred_fields=sorted(variant.inferred_fields),cad_executed=False)
        return 3 if missing or variant.inferred_fields else 0
    emit(
        "progress",
        message=f"{variant.roller_type} 总长 {spec.overall_length_mm:g}，开始生成…",
    )
    result = generate_roller_part(spec, args.out)
    verification = None
    if args.verify_reopen:
        from part_verification import verify_saved_part
        # result.bounds historically measures the first body only; it is not
        # an independent full-part target. Do not use it as an oracle.
        verification = verify_saved_part(result.path, **({'inspect_cylinders': True}
                                         if getattr(args, 'inspect_cylinders', False) else {}))
    emit(
        "done",
        kind="roller", reopen=verification, mechanical_acceptance="unverified",
        status=verification['status'] if verification else "generated_unverified",
        inferred_fields=missing,dimensions_source="explicitly_allowed_generic_defaults" if missing else "drawing",
        path=str(result.path),
        message=f"滚筒零件已生成：{Path(result.path).name}",
    )
    return 0


def run_turned(args: argparse.Namespace) -> int:
    from turned_part import discover_turned_parts, generate_turned_part
    from turned_generate import build_turned
    analysis = analyze_cad_file(args.input)
    plans = discover_turned_parts(analysis)
    if args.analyze_only:
        emit("analysis",kind="turned",parts=[{'index':i,'label':p.label,'stock':p.stock,
            'length_mm':p.length_mm,'max_radius_mm':p.max_radius_mm} for i,p in enumerate(plans)])
        return 0
    if not 0 <= args.variant < len(plans):
        raise ValueError('车件 --variant 超出范围（从 0 开始）')
    plan = plans[args.variant]
    build = build_turned(plan)
    if args.plan_only:
        emit("plan",kind="turned",plan=asdict(plan),feature_plan=asdict(build),
             pending=list(build.warnings),cad_executed=False,threads="cosmetic_or_pending_not_certified")
        return 3 if build.warnings else 0
    if not args.out:
        raise ValueError('车件生成需要 --out 新零件路径')
    path = generate_turned_part(plan,args.out)
    from part_verification import KEPT_AFTER_SAVE_STATUSES, execution_exit_code
    from sw_session import current_lease
    lease = current_lease()
    outcome = getattr(lease, "post_save_outcome", None)
    if outcome in KEPT_AFTER_SAVE_STATUSES:
        emit(
            "done",
            kind="turned",
            path=path,
            status=outcome,
            exit_code=execution_exit_code(outcome),
            passed=False,
            sw_live_verified=False,
            native_acceptance="pending_windows_validation",
            file_on_disk=True,
            exit_app=False,
            mechanical_acceptance="unverified",
            warnings=list(build.warnings),
            threads="cosmetic_or_pending_not_certified",
            message=(
                "saved part kept; post-save COM failure is not a hard failure; "
                "ExitApp was not called"
            ),
        )
        return execution_exit_code(outcome)
    verification = None
    if args.verify_reopen:
        from part_verification import verify_saved_part
        verification = verify_saved_part(path,expected_dims_mm=build.expected_dims_mm,
            **({'inspect_cylinders': True} if getattr(args, 'inspect_cylinders', False) else {}))
    emit("done",kind="turned",path=path,reopen=verification,mechanical_acceptance="unverified",
         status=verification['status'] if verification else "generated_unverified",
         warnings=list(build.warnings),threads="cosmetic_or_pending_not_certified")
    return 3 if build.warnings or verification is None else 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configured = configure_logging()
    if args.verbose:
        stream = logging.StreamHandler(sys.stderr)
        stream.setFormatter(logging.Formatter("%(levelname)-7s %(name)s: %(message)s"))
        logging.getLogger().addHandler(stream)
    # 详细日志落到文件，插件出错时能回看；事件流仍只走标准输出。
    LOGGER.debug("详细日志：%s", configured or log_file_path())
    try:
        if args.inspect_cylinders and not args.verify_reopen:
            raise ValueError('--inspect-cylinders requires --verify-reopen')
        if args.inspect_cylinders and (args.batch or args.analyze_only or args.plan_only):
            raise ValueError('--inspect-cylinders currently requires single-part generation')
        if args.mode == "sheet" and args.batch:
            runner = run_sheet_batch
        else:
            runner = {"sheet": run_sheet, "roller": run_roller, "turned": run_turned}[args.mode]
        needs_conversion = Path(args.input).suffix.casefold() == '.dwg'
        if args.sw_exe is not None and (needs_conversion or (not args.analyze_only and not args.plan_only)):
            from sw_owned_launch import owned_solidworks
            from sw_session import run_on_task_sta
            def owned_job():
                from part_verification import kept_after_save_exit
                from sw_session import current_lease
                with owned_solidworks(args.sw_exe) as binding:
                    emit("session", **binding.evidence())
                    rc = runner(args)
                evidence = binding.evidence()
                emit("session_end", **evidence)
                lease = current_lease()
                rc = kept_after_save_exit(
                    rc,
                    generation_saved=bool(getattr(lease, "generation_saved", False)),
                    cleanup_status=evidence.get("cleanup_status"),
                    post_save_outcome=getattr(lease, "post_save_outcome", None),
                )
                if evidence.get("cleanup_status") in {
                    "partial_com_disconnect",
                    "saved_com_disconnected_after_generation",
                }:
                    emit(
                        "partial",
                        status="partial_com_disconnect",
                        path=getattr(lease, "generation_path", None),
                        exit_code=0,
                        passed=False,
                        sw_live_verified=False,
                        native_acceptance="pending_windows_validation",
                        file_on_disk=True,
                        exit_app=False,
                        cleanup_status=evidence.get("cleanup_status"),
                        cleanup_disconnect=evidence.get("cleanup_disconnect"),
                        message=(
                            "saved part kept; cleanup/inventory COM disconnect is not a hard failure; "
                            "ExitApp was not called"
                        ),
                    )
                return rc
            return run_on_task_sta(owned_job, timeout=300, task_name="owned-cad-cli")
        return runner(args)
    except Exception as error:  # 插件按 error 事件提示用户
        LOGGER.exception("生成失败")
        emit("error", message=str(error), detail=type(error).__name__)
        return 1


if __name__ == "__main__":
    from app_logging import bootstrap
    bootstrap(Path(__file__).resolve().parents[1],'model-cli')
    sys.exit(main())


