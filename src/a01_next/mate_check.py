"""Assembly mate check scaffold. The default checker does not solve mates."""

from __future__ import annotations

from typing import Callable


def check_mates(plan: dict, checker: Callable[[dict], dict] | None = None) -> dict:
    if checker is not None:
        report = checker(plan)
        report.setdefault("sw_live", "not_applicable_on_linux")
        return report
    rows = []
    for row in plan.get("interface_checks", []):
        rows.append(
            {
                "parameter": row["parameter"],
                "rule": row["rule"],
                "mate_status": "not_checked",
                "reason": "mock scaffold; SolidWorks mate solve was not run",
            }
        )
    return {
        "status": "scaffold",
        "backend": "mock",
        "track": "next",
        "mates_solved": False,
        "cad_executed": False,
        "sw_live": "not_applicable_on_linux",
        "rows": rows,
        "note": "Interface list only. This is not a mate or motion pass.",
    }
