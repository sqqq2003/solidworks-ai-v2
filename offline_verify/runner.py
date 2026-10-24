"""离线验证运行器：发现、运行、汇总，只读被测代码。

运行器保证：
- 只读：被测检出中的任何文件都不被修改；子进程只跑 unittest，
  报告只写进调用方指定的 out-dir（本模块不写 out-dir 之外的
  任何地方，out-dir 由 CLI 创建）。
- 诚实：缺失套件只报告为 missing，绝不计入通过；基线差异只
  报告为 diff，绝不静默放过；mock/离线通过绝不写成实机通过
  （报告头固定带 pending_windows_validation 声明）。
- 不猜数：t、R、K、角度等每单参数与本包无关；本包不引用
  src/solidworks_generator.py 头部的 DEFAULT_BEND_K_FACTOR
  残留常量（见 README 的已知残留项）。
"""

import os
import re
import subprocess
import sys
from datetime import datetime, timezone

from .baseline import compare_suite
from .suites import SCAN_DIRS, SUITES, suite_command, suite_file_relpath

REPORT_FORMAT = "offline-verify-report/1"

_TEST_START_RE = re.compile(r"^(\S+) \([^)]*\) \.\.\. ?(.*)$")
_VERDICTS = (
    "ok",
    "FAIL",
    "ERROR",
    "skipped",
    "expected failure",
    "unexpected success",
)
_RAN_RE = re.compile(r"^Ran (\d+) tests? in ", re.MULTILINE)

DEFAULT_TIMEOUT_SECONDS = 600


def _present(root, suite):
    """套件在检出中是否存在（文件或 discover 目录）。"""
    rel = suite_file_relpath(suite)
    path = os.path.join(root, rel)
    if suite["kind"] == "module":
        return os.path.isfile(path)
    return os.path.isdir(path)


def discover(root, suites=None):
    """返回 {suite_id: {"present": bool, "relpath": str}}。"""
    suites = SUITES if suites is None else suites
    out = {}
    for suite in suites:
        out[suite["id"]] = {
            "present": _present(root, suite),
            "relpath": suite_file_relpath(suite),
        }
    return out


def scan_unregistered(root, suites=None):
    """列出检出中存在但未注册的 test_*.py 文件（只列出、不运行）。

    扫描范围见 suites.SCAN_DIRS；已注册套件的文件路径不在此列。
    """
    suites = SUITES if suites is None else suites
    registered = set()
    for suite in suites:
        rel = suite_file_relpath(suite)
        if suite["kind"] == "module":
            registered.add(os.path.normpath(rel))
        else:
            # discover 套件跑整目录：该目录下所有 test_*.py 都算已注册。
            discover_dir = os.path.join(root, suite["cwd_rel"], suite["target"])
            if os.path.isdir(discover_dir):
                for name in sorted(os.listdir(discover_dir)):
                    if name.startswith("test_") and name.endswith(".py"):
                        registered.add(os.path.normpath(os.path.join(
                            suite["cwd_rel"], suite["target"], name)))
    found = []
    for scan_dir in SCAN_DIRS:
        base = os.path.join(root, scan_dir)
        if not os.path.isdir(base):
            continue
        for name in sorted(os.listdir(base)):
            if name.startswith("test_") and name.endswith(".py"):
                rel = os.path.normpath(os.path.join(scan_dir, name))
                if rel not in registered:
                    found.append(rel)
    return found


def _record_verdict(counts, failures, name, verdict):
    """把一个 verdict 记入计数（skipped 带原因文本时也算）。"""
    if verdict == "ok" or verdict == "expected failure":
        counts["passed"] += 1
    elif verdict == "FAIL":
        counts["failed"] += 1
        failures.append(name)
    elif verdict == "ERROR" or verdict == "unexpected success":
        counts["errored"] += 1
        failures.append(name)
    elif verdict.startswith("skipped"):
        counts["skipped"] += 1


def _parse_unittest_output(text):
    """解析 unittest -v 输出，返回 (counts, failures, ran)。

    counts: {"passed": n, "failed": n, "errored": n, "skipped": n}。

    两点鲁棒性（实测中都遇到过）：
    - 被测代码在测试中打日志时，verdict 会被挤到下一行单独成行
      （如 "test_x (...) ... <日志>" 后跟一行 "ok"），故用
      “待定测试 + 后续 verdict 行”的状态机解析，而非要求单行。
    - skipped 行带原因文本（"skipped 'reason'"），按前缀判定。
    """
    counts = {"passed": 0, "failed": 0, "errored": 0, "skipped": 0}
    failures = []
    saw_test_line = False
    pending = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        start = _TEST_START_RE.match(line)
        if start:
            saw_test_line = True
            name, rest = start.group(1), start.group(2).strip()
            matched = None
            for verdict in _VERDICTS:
                if rest == verdict or rest.startswith(verdict + " "):
                    matched = verdict
                    break
            if matched is not None:
                _record_verdict(counts, failures, name, matched)
                pending = None
            else:
                # verdict 被日志挤走，下一行 verdict 属于该测试。
                pending = name
            continue
        if pending is not None:
            for verdict in _VERDICTS:
                if line == verdict or line.startswith(verdict + " "):
                    _record_verdict(counts, failures, pending, verdict)
                    pending = None
                    break
    ran_match = _RAN_RE.search(text)
    ran = int(ran_match.group(1)) if ran_match else None
    return counts, failures, ran, saw_test_line


def run_suite(root, suite, timeout=DEFAULT_TIMEOUT_SECONDS):
    """运行单个套件，返回结果字典（不抛错，失败都记在结果里）。"""
    if suite["kind"] == "module":
        cwd = root
    else:
        cwd = os.path.join(root, suite["cwd_rel"])
    cmd = [sys.executable] + suite_command(suite)
    # 仓库测试约定：部分测试文件自设 sys.path 到 src/，个别文件
    # （如 test_recovery_review_guards.py）不设——它假设 src/ 已在
    # 路径上。运行器统一把 <root>/src 前置进 PYTHONPATH，与仓库
    # 惯例一致；不改任何测试文件。
    env = dict(os.environ)
    src_dir = os.path.join(root, "src")
    old_path = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = src_dir + (os.pathsep + old_path if old_path else "")
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return {
            "id": suite["id"],
            "status": "error",
            "ran": 0,
            "passed": 0,
            "failed": 0,
            "errored": 0,
            "skipped": 0,
            "failures": [],
            "note": "timeout after %ss" % timeout,
        }
    except OSError as exc:
        return {
            "id": suite["id"],
            "status": "error",
            "ran": 0,
            "passed": 0,
            "failed": 0,
            "errored": 0,
            "skipped": 0,
            "failures": [],
            "note": "cannot launch suite: %s" % exc,
        }
    text = proc.stdout + proc.stderr
    counts, failures, ran, saw_test_line = _parse_unittest_output(text)
    if not saw_test_line:
        if proc.returncode == 0 and "OK" in text:
            ran = ran if ran is not None else 0
            counts["passed"] = ran
            status = "pass"
        else:
            status = "error"
            tail = "\n".join(text.splitlines()[-15:])
            return {
                "id": suite["id"],
                "status": status,
                "ran": 0,
                "passed": 0,
                "failed": 0,
                "errored": 0,
                "skipped": 0,
                "failures": [],
                "note": "unparsable output (exit %s):\n%s"
                % (proc.returncode, tail),
            }
    else:
        if ran is None:
            ran = (
                counts["passed"]
                + counts["failed"]
                + counts["errored"]
                + counts["skipped"]
            )
        status = "pass" if (counts["failed"] == 0 and counts["errored"] == 0) else "fail"
    return {
        "id": suite["id"],
        "status": status,
        "ran": ran,
        "passed": counts["passed"],
        "failed": counts["failed"],
        "errored": counts["errored"],
        "skipped": counts["skipped"],
        "failures": failures,
        "note": "",
    }


def run_all(root, baseline_suites, suites=None, only=None,
            allow_missing=False, timeout=DEFAULT_TIMEOUT_SECONDS):
    """跑全部（或 --only 指定的）套件，返回统一报告字典。"""
    from . import __version__

    suites = SUITES if suites is None else suites
    if only:
        wanted = set(only)
        suites = [s for s in suites if s["id"] in wanted]
        unknown = sorted(wanted - {s["id"] for s in suites})
        if unknown:
            raise ValueError("unknown suite id(s): %s" % ", ".join(unknown))
    presence = discover(root, suites)
    results = []
    for suite in suites:
        info = presence[suite["id"]]
        if not info["present"]:
            results.append({
                "id": suite["id"],
                "title": suite["title"],
                "status": "missing",
                "ran": 0,
                "passed": 0,
                "failed": 0,
                "errored": 0,
                "skipped": 0,
                "failures": [],
                "note": "suite not present in this checkout "
                        "(branch unmerged or file absent); "
                        "never counted as passed",
                "baseline": compare_suite(suite["id"], None, baseline_suites),
                "source_pr": suite["source_pr"],
                "source_commit": suite["source_commit"],
                "relpath": info["relpath"],
            })
            continue
        res = run_suite(root, suite, timeout=timeout)
        res["title"] = suite["title"]
        res["baseline"] = compare_suite(
            suite["id"], res["passed"], baseline_suites
        )
        res["source_pr"] = suite["source_pr"]
        res["source_commit"] = suite["source_commit"]
        res["relpath"] = info["relpath"]
        results.append(res)

    missing = [r["id"] for r in results if r["status"] == "missing"]
    failed = [r["id"] for r in results if r["status"] in ("fail", "error")]
    diffed = [
        r["id"] for r in results
        if r["baseline"]["verdict"] == "diff"
    ]
    reasons = []
    if failed:
        reasons.append("suites failed/errored: %s" % ", ".join(failed))
    if diffed:
        reasons.append("baseline diffs: %s" % ", ".join(diffed))
    if missing and not allow_missing:
        reasons.append("suites missing: %s" % ", ".join(missing))
    summary = {
        "suites_total": len(results),
        "suites_present": len(results) - len(missing),
        "suites_missing": len(missing),
        "suites_passed": sum(1 for r in results if r["status"] == "pass"),
        "suites_failed": len(failed),
        "tests_ran": sum(r["ran"] for r in results),
        "tests_passed": sum(r["passed"] for r in results),
        "tests_failed": sum(r["failed"] for r in results),
        "tests_errored": sum(r["errored"] for r in results),
        "tests_skipped": sum(r["skipped"] for r in results),
        "baseline_match": sum(
            1 for r in results if r["baseline"]["verdict"] == "match"
        ),
        "baseline_diff": len(diffed),
        "complete": not missing and not failed and not diffed,
    }
    return {
        "format": REPORT_FORMAT,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "runner_version": __version__,
        "root": root,
        "allow_missing": allow_missing,
        "suites": results,
        "missing": missing,
        "unregistered": scan_unregistered(root, suites),
        "summary": summary,
        "exit_code": 1 if reasons else 0,
        "exit_reasons": reasons,
        "principles": (
            "merge != validation: every Windows / SolidWorks item is "
            "pending_windows_validation. Mock/offline passes are never "
            "native acceptance; a missing suite is never a pass."
        ),
    }
