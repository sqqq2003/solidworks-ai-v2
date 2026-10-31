"""基线文件加载与比对。

比对口径（只比通过数，不比总数）：
- match：实测通过数 == 基线期望通过数。
- diff：实测通过数 != 期望（报告中标出差值，不静默放过）。
- no-baseline：基线文件里没有该套件（不判对错，只注明）。
- missing 套件不参与比对：基线存在但检出中缺失时，报告中
  该套件状态就是 missing，基线 verdict 记为 "missing"，绝不
  把缺失写成通过。
"""

import json
import os

from .suites import SUITES


class BaselineError(ValueError):
    """基线文件非法（JSON 坏、格式串不对、计数非整数）。"""


def load_baseline(path):
    """读基线文件，返回 (format_version, {suite_id: entry})。"""
    if not os.path.isfile(path):
        raise BaselineError("baseline file not found: %s" % path)
    with open(path, "r", encoding="utf-8") as fh:
        try:
            data = json.load(fh)
        except json.JSONDecodeError as exc:
            raise BaselineError("baseline file is not valid JSON: %s" % exc)
    if data.get("format") != "offline-verify-baseline/1":
        raise BaselineError(
            "unsupported baseline format: %r (want offline-verify-baseline/1)"
            % data.get("format")
        )
    suites = data.get("suites")
    if not isinstance(suites, dict):
        raise BaselineError("baseline file has no 'suites' mapping")
    for suite_id, entry in suites.items():
        if not isinstance(entry, dict) or not isinstance(
            entry.get("expected_passed"), int
        ):
            raise BaselineError(
                "baseline entry for %r has no integer expected_passed" % suite_id
            )
    known = {s["id"] for s in SUITES}
    unknown = sorted(set(suites) - known)
    if unknown:
        raise BaselineError("baseline lists unknown suites: %s" % ", ".join(unknown))
    return data.get("version", 0), suites


def compare_suite(suite_id, measured_passed, baseline_suites):
    """比对单个套件，返回 verdict 字典。

    measured_passed 为 None 表示套件缺失（未运行），此时 verdict
    为 missing，与基线是否存在无关。
    """
    if measured_passed is None:
        return {"verdict": "missing", "expected": None, "delta": None}
    entry = baseline_suites.get(suite_id)
    if entry is None:
        return {"verdict": "no-baseline", "expected": None, "delta": None}
    expected = entry["expected_passed"]
    return {
        "verdict": "match" if measured_passed == expected else "diff",
        "expected": expected,
        "delta": measured_passed - expected,
    }
