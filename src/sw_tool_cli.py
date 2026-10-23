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


def emit(event: str, **payload: object) -> None:
    payload["event"] = event
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="钣金 / 滚筒零件一键生成（SolidWorks 插件后端）")
    parser.add_argument("--mode", choices=("sheet", "roller"), required=True)
    parser.add_argument("--input", required=True, help="DWG / DXF 图纸路径")
    parser.add_argument("--out", help="输出 .SLDPRT 路径；--analyze-only 时可省略")
    parser.add_argument("--analyze-only", action="store_true", help="只识别图纸并汇报，不建模")
    parser.add_argument("--profile", type=int, default=None, help="钣金：轮廓序号（从 1 开始）")
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
        "--verbose",
        action="store_true",
        help="把识别 / 建模的详细日志打到标准错误，便于排查",
    )
    parser.set_defaults(auto_bend=True)
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
    profiles = []
    for index, profile in enumerate(analysis.profiles):
        if not getattr(profile, "closed", False):
            continue
        bends = profile_bend_indices(profile, analysis.bend_lines)
        profiles.append(
            {
                "index": index + 1,
                "area_mm2": round(profile_area(profile), 2),
                "bend_count": len(bends),
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
        }
        for position, variant in enumerate(analysis.roller_variants)
    ]
    return {
        "path": str(analysis.path),
        "profile_count": len(profiles),
        "bend_line_count": len(analysis.bend_lines),
        "profiles": profiles,
        "roller_variants": variants,
    }


def run_sheet(args: argparse.Namespace) -> int:
    emit("progress", message="正在识别图纸…")
    analysis = analyze_cad_file(args.input)

    if args.analyze_only:
        emit("analysis", **describe_drawing(analysis))
        return 0

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
    )
    if allowance is not None and (
        not result.bend_allowance_verified
        or result.k_factor_readback is None
        or not math.isclose(result.k_factor_readback, allowance.k_factor, abs_tol=1e-8)
    ):
        raise RuntimeError("requested K factor was not verified; refusing success event")
    emit(
        "done",
        kind="sheet",
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


def run_roller(args: argparse.Namespace) -> int:
    emit("progress", message="正在识别滚筒规格…")
    analysis = analyze_cad_file(args.input)

    if args.analyze_only:
        emit("analysis", **describe_drawing(analysis))
        return 0

    if not args.out:
        emit("error", message="缺少 --out 输出路径。")
        return 2
    if not analysis.roller_variants:
        emit("error", message="这张图里没识别到滚筒规格，无法生成滚筒零件。")
        return 1
    if not 0 <= args.variant < len(analysis.roller_variants):
        emit("error", message=f"规格序号 {args.variant} 超出范围。")
        return 2

    variant = analysis.roller_variants[args.variant]
    try:
        spec = spec_from_variant(variant)
    except RollerSpecError as error:
        emit("error", message=str(error))
        return 1
    emit(
        "progress",
        message=f"{variant.roller_type} 总长 {spec.overall_length_mm:g}，开始生成…",
    )
    result = generate_roller_part(spec, args.out)
    emit(
        "done",
        kind="roller",
        path=str(result.path),
        message=f"滚筒零件已生成：{Path(result.path).name}",
    )
    return 0


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
        runner = run_sheet if args.mode == "sheet" else run_roller
        if args.sw_exe is not None and not args.analyze_only:
            from sw_owned_launch import owned_solidworks
            from sw_session import run_on_task_sta
            def owned_job():
                with owned_solidworks(args.sw_exe) as binding:
                    emit("session", **binding.evidence())
                    rc = runner(args)
                emit("session_end", **binding.evidence())
                return rc
            return run_on_task_sta(owned_job, timeout=300, task_name="owned-sheet-metal-cli")
        return runner(args)
    except Exception as error:  # 插件按 error 事件提示用户
        LOGGER.exception("生成失败")
        emit("error", message=str(error), detail=type(error).__name__)
        return 1


if __name__ == "__main__":
    sys.exit(main())

