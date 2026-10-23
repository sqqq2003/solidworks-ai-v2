"""Issue #6 module 2: one controlled-execution entry with explicit refusals.

This is the offline framework entry for Windows SolidWorks execution:

* the default path runs the **mock** adapter and writes a JSON trace — it never
  opens SolidWorks and never writes a CAD product file;
* the live path stays behind explicit refusal conditions (platform, COM,
  operator confirmation, confirmed mappings, installed SLDWORKS.exe, work-copy
  rules) and delegates to ``sw_api.win32com_backend.apply_live``.

Nothing in this module attaches to SolidWorks at import time. A refusal is a
successful, honest answer: the report says why execution did not run.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

from . import assert_distinct_copy
from .mock import MockAssemblyAdapter

MODULE = "issue6-module2-sw-controlled-execution"
LIVE_NOTE = (
    "The live port requires a Windows transaction driver supplied by Windows "
    "integration; it is not part of this offline framework dispatch."
)


@dataclass(frozen=True)
class ExecutionRequest:
    """A controlled execution request.

    ``live=False`` is the offline mock dry-run. ``live=True`` asks for a real
    Windows SolidWorks SaveAs through the existing transaction stack and must
    clear every refusal first.
    """

    source: str
    destination: Path
    plan: dict
    live: bool = False
    confirmed: bool = False
    sw_exe: Path | None = None
    mapping_payload: dict | None = None
    note: str = ""


@dataclass(frozen=True)
class Refusal:
    condition: str
    detail: str

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.condition}: {self.detail}"


def refusals(request: ExecutionRequest) -> list[Refusal]:
    """Every reason this request must not execute. Empty means allowed."""

    rows: list[Refusal] = []
    destination = Path(request.destination)
    try:
        assert_distinct_copy(request.source, destination)
    except ValueError as exc:
        rows.append(Refusal("distinct_copy", str(exc)))
    if destination.exists():
        rows.append(
            Refusal(
                "destination_exists",
                "controlled execution never overwrites an existing destination",
            )
        )
    if not request.live:
        if destination.suffix.lower() != ".json":
            rows.append(
                Refusal(
                    "mock_trace_suffix",
                    "mock dry-run writes a .json trace and refuses CAD or drawing product files",
                )
            )
        return rows
    if sys.platform != "win32":
        rows.append(
            Refusal("platform", "live execution requires Windows; sw_live=not_applicable_on_linux")
        )
        return rows
    from .win32com_backend import com_available

    if not com_available():
        rows.append(Refusal("com_unavailable", "SolidWorks COM (pywin32) is unavailable"))
    if request.confirmed is not True:
        rows.append(
            Refusal("unconfirmed", "operator review must be confirmed before a live write")
        )
    if request.mapping_payload is None:
        rows.append(
            Refusal("mapping_missing", "live writes require a confirmed parameter mapping payload")
        )
    if request.sw_exe is None or not Path(request.sw_exe).is_file():
        rows.append(Refusal("sw_exe_missing", "live execution requires an installed SLDWORKS.exe path"))
    elif Path(request.sw_exe).name.casefold() != "sldworks.exe":
        rows.append(Refusal("sw_exe_name", "the live executable must be SLDWORKS.exe"))
    if destination.suffix.lower() != ".sldasm":
        rows.append(
            Refusal("work_copy_suffix", "live assembly SaveAs requires a .SLDASM work-copy path")
        )
    return rows


def run_controlled_execution(
    request: ExecutionRequest,
    *,
    adapter: MockAssemblyAdapter | None = None,
) -> dict:
    """Run a request through the mock adapter, or refuse with reasons.

    Returns a report dict. A refused or failed report is never re-raised as a
    success: ``cad_executed`` stays False and the refusals / error are listed.
    """

    blocked = refusals(request)
    report: dict = {
        "module": MODULE,
        "status": "refused" if blocked else "not_run",
        "backend": "live" if request.live else "mock",
        "refusals": [vars(row) for row in blocked],
        "cad_executed": False,
        "cad_release_approved": False,
        "mechanical_acceptance": "unverified",
        "sw_live": "requested_but_not_proven" if request.live else "not_applicable_on_linux",
        "source": str(request.source),
        "destination": str(request.destination),
        "note": request.note or LIVE_NOTE,
    }
    if blocked:
        return report
    if not request.live:
        from .apply import dry_run_apply

        trace = dry_run_apply(
            request.plan,
            Path(request.destination),
            source=request.source,
            adapter=adapter or MockAssemblyAdapter(),
        )
        report["status"] = "mock_dry_run"
        report["sw_live"] = "not_applicable_on_linux"
        report["trace"] = trace
        return report
    from .win32com_backend import apply_live

    try:
        live = apply_live(
            request.plan,
            Path(request.source),
            Path(request.destination),
            mapping_payload=request.mapping_payload,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        report["status"] = "failed"
        report["error"] = str(exc)
        return report
    report["status"] = "live_executed_unverified"
    report["live"] = live
    return report
