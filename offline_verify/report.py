"""统一验证报告的 Markdown 渲染（与 report.json 字段一一对应）。

渲染只做展示，不改数字：报告里的任何数字都来自运行器实测，
渲染层不得四舍五入、不得合并、不得省略失败项。
"""


def render_markdown(report):
    """把 run_all() 的报告字典渲染成 Markdown 文本。"""
    summary = report["summary"]
    lines = []
    lines.append("# 离线验证报告（Issue #25 扩展模块 ⑥）")
    lines.append("")
    lines.append("- 生成时间（UTC）：%s" % report["generated_at_utc"])
    lines.append("- 运行器版本：%s" % report["runner_version"])
    lines.append("- 检出根：`%s`" % report["root"])
    lines.append("- 退出码：%d" % report["exit_code"])
    if report["exit_reasons"]:
        lines.append("- 退出原因：%s" % "; ".join(report["exit_reasons"]))
    lines.append("- 完整（全部套件在场且通过且基线一致）：%s"
                 % ("是" if summary["complete"] else "否"))
    lines.append("")
    lines.append("## 汇总")
    lines.append("")
    lines.append("| 项目 | 数 |")
    lines.append("|---|---|")
    lines.append("| 套件总数 | %d |" % summary["suites_total"])
    lines.append("| 套件在场 | %d |" % summary["suites_present"])
    lines.append("| 套件缺失 | %d |" % summary["suites_missing"])
    lines.append("| 套件通过 | %d |" % summary["suites_passed"])
    lines.append("| 套件失败/出错 | %d |" % summary["suites_failed"])
    lines.append("| 用例执行 | %d |" % summary["tests_ran"])
    lines.append("| 用例通过 | %d |" % summary["tests_passed"])
    lines.append("| 用例失败 | %d |" % summary["tests_failed"])
    lines.append("| 用例出错 | %d |" % summary["tests_errored"])
    lines.append("| 用例跳过 | %d |" % summary["tests_skipped"])
    lines.append("| 基线一致 | %d |" % summary["baseline_match"])
    lines.append("| 基线差异 | %d |" % summary["baseline_diff"])
    lines.append("")
    lines.append("## 各套件")
    lines.append("")
    lines.append("| 套件 | 状态 | 执行/通过/失败/出错/跳过 | 基线 | 来源 |")
    lines.append("|---|---|---|---|---|")
    for suite in report["suites"]:
        base = suite["baseline"]
        if base["verdict"] == "match":
            base_text = "一致（%s）" % base["expected"]
        elif base["verdict"] == "diff":
            base_text = "差异：实测 %s，期望 %s（delta %+d）" % (
                suite["passed"], base["expected"], base["delta"]
            )
        elif base["verdict"] == "missing":
            base_text = "缺失（不比对）"
        else:
            base_text = "无基线"
        lines.append(
            "| %s | %s | %d/%d/%d/%d/%d | %s | PR #%s @ %s |"
            % (
                suite["id"],
                suite["status"],
                suite["ran"],
                suite["passed"],
                suite["failed"],
                suite["errored"],
                suite["skipped"],
                base_text,
                suite["source_pr"],
                suite["source_commit"],
            )
        )
    lines.append("")
    failures = [s for s in report["suites"] if s["failures"]]
    if failures:
        lines.append("## 失败清单")
        lines.append("")
        for suite in failures:
            lines.append("- %s：" % suite["id"])
            for name in suite["failures"]:
                lines.append("  - %s" % name)
            if suite["note"]:
                lines.append("  - 备注：%s" % suite["note"])
        lines.append("")
    if report["missing"]:
        lines.append("## 缺失套件（分支未合并，绝不计入通过）")
        lines.append("")
        for suite_id in report["missing"]:
            lines.append("- %s" % suite_id)
        lines.append("")
    if report["unregistered"]:
        lines.append("## 未注册测试文件（已发现、未运行、未计入）")
        lines.append("")
        for rel in report["unregistered"]:
            lines.append("- %s" % rel)
        lines.append("")
    lines.append("## 原则")
    lines.append("")
    lines.append("- %s" % report["principles"])
    lines.append("- 合并 ≠ 验证通过：本报告只证明离线 mock/回归通过，"
                  "Windows / SolidWorks 实机验收见 WINDOWS_ACCEPTANCE_PACK.md，"
                  "全部标 pending_windows_validation。")
    lines.append("")
    return "\n".join(lines)
