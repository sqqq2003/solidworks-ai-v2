"""命令行入口（Issue #25 扩展模块 ⑥）。

用法（在仓库检出根运行，检出根即 --root）：

    # 离线验证：跑已注册套件，写报告
    python -m offline_verify.cli verify --root . --out-dir out
    # 只跑指定套件
    python -m offline_verify.cli verify --root . --out-dir out \\
        --only bridge-wiring,pipeline
    # 缺失套件不影响退出码（仅当在场套件全过且基线一致时返回 0）
    python -m offline_verify.cli verify --root . --out-dir out --allow-missing
    # 只生成未来 Windows 实机测试包文档（不跑任何测试）
    python -m offline_verify.cli windows-pack --out-dir out

退出码（verify）：
- 0：全部在场套件通过、基线一致，且无缺失套件
  （或 --allow-missing 且在场套件全过、基线一致）。
- 1：有套件失败/出错、基线差异，或有缺失套件（未加 --allow-missing）。
- 2：输入错误（检出根不存在、基线文件非法、套件 id 未知）。
"""

import argparse
import json
import os
import sys

from .baseline import BaselineError, load_baseline
from .report import render_markdown
from .runner import run_all
from .suites import SUITES
from .windows_pack import render_windows_pack

DEFAULT_BASELINE = os.path.join(os.path.dirname(__file__), "baseline.json")


def _build_parser():
    parser = argparse.ArgumentParser(
        prog="offline_verify",
        description="Issue #25 module 6: offline verification runner "
                    "and Windows acceptance pack generator.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    verify = sub.add_parser("verify", help="run registered suites, write report")
    verify.add_argument("--root", default=".",
                        help="checkout root to verify (default: .)")
    verify.add_argument("--out-dir", default="out",
                        help="output directory for report.json/report.md")
    verify.add_argument("--baseline", default=DEFAULT_BASELINE,
                        help="baseline JSON file (default: packaged baseline)")
    verify.add_argument("--only", default="",
                        help="comma-separated suite ids to run (default: all)")
    verify.add_argument("--allow-missing", action="store_true",
                        help="missing suites do not affect the exit code")
    verify.add_argument("--timeout", type=int, default=600,
                        help="per-suite timeout in seconds (default: 600)")

    pack = sub.add_parser(
        "windows-pack",
        help="generate the unified Windows acceptance pack document",
    )
    pack.add_argument("--out-dir", default="out",
                      help="output directory for WINDOWS_ACCEPTANCE_PACK.md")
    return parser


def cmd_verify(args):
    root = os.path.abspath(args.root)
    if not os.path.isdir(root):
        print("error: checkout root not found: %s" % args.root, file=sys.stderr)
        return 2
    try:
        _version, baseline_suites = load_baseline(args.baseline)
    except BaselineError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2
    only = [s for s in args.only.split(",") if s] or None
    try:
        report = run_all(
            root,
            baseline_suites,
            suites=SUITES,
            only=only,
            allow_missing=args.allow_missing,
            timeout=args.timeout,
        )
    except ValueError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2
    os.makedirs(args.out_dir, exist_ok=True)
    json_path = os.path.join(args.out_dir, "report.json")
    md_path = os.path.join(args.out_dir, "report.md")
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write(render_markdown(report))
    summary = report["summary"]
    print(
        "suites: %d total, %d passed, %d failed, %d missing; "
        "tests: %d ran, %d passed, %d failed, %d errored, %d skipped; "
        "baseline: %d match, %d diff; exit=%d"
        % (
            summary["suites_total"],
            summary["suites_passed"],
            summary["suites_failed"],
            summary["suites_missing"],
            summary["tests_ran"],
            summary["tests_passed"],
            summary["tests_failed"],
            summary["tests_errored"],
            summary["tests_skipped"],
            summary["baseline_match"],
            summary["baseline_diff"],
            report["exit_code"],
        )
    )
    if report["exit_reasons"]:
        print("reasons: %s" % "; ".join(report["exit_reasons"]))
    print("report: %s, %s" % (json_path, md_path))
    return report["exit_code"]


def cmd_windows_pack(args):
    os.makedirs(args.out_dir, exist_ok=True)
    path = os.path.join(args.out_dir, "WINDOWS_ACCEPTANCE_PACK.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(render_windows_pack())
    from .windows_pack import ITEMS

    print("windows acceptance pack: %d items -> %s" % (len(ITEMS), path))
    return 0


def main(argv=None):
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "verify":
        return cmd_verify(args)
    if args.command == "windows-pack":
        return cmd_windows_pack(args)
    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    sys.exit(main())
