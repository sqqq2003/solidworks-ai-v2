"""Backend-neutral, single-writer transaction contract; no mechanical acceptance."""
from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import asdict, dataclass
from math import isclose, isfinite
from typing import Protocol

from .mapping import ParameterMapping, load_mappings


class MechanicalCheckPort(Protocol):
    """Native evidence providers; absence always means unverified."""
    def check_mates(self) -> dict: ...
    def check_interference(self) -> dict: ...
    def check_motion(self) -> dict: ...


class ExecutionPort(Protocol):
    simulated: bool
    def writer(self) -> AbstractContextManager: ...
    def preflight(self, mappings: list[ParameterMapping], destination: str) -> None: ...
    def read(self, mapping: ParameterMapping) -> float: ...
    def write(self, mapping: ParameterMapping, value: float) -> None: ...
    def rebuild(self) -> None: ...
    def checkpoint(self): ...
    def restore(self, checkpoint) -> None: ...
    def save_as(self, destination: str) -> None: ...
    def reopen(self, destination: str) -> None: ...


@dataclass(frozen=True)
class Change:
    mapping: ParameterMapping
    before: float
    after: float


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
        raise ValueError("dimension must be finite numeric")
    return float(value)


def equal(a, b):
    return isclose(number(a), number(b), rel_tol=1e-9, abs_tol=1e-9)


def execute(plan: dict, mapping_payload: dict, port: ExecutionPort, destination: str) -> dict:
    """Preflight before writes; rollback checkpoint on every subsequent failure.

    Port preflight must reject existing destinations, source aliases, dirty or
    foreign documents, and unresolved physical targets. Checkpoint includes the
    output artifact: restore must remove only output created by this transaction.
    Values at this boundary use mapping units (SI conversion belongs to port).
    """
    rows = load_mappings(mapping_payload)
    unknown = set(r.parameter for r in rows) - set(plan["values_mm"])
    if unknown:
        raise ValueError(f"unknown plan parameters: {sorted(unknown)}")
    register = plan.get("parameter_register", {})
    for row in rows:
        plan_unit = register.get(row.parameter, {}).get("unit", "mm")
        if row.unit != plan_unit and {row.unit, plan_unit} != {"mm", "m"}:
            raise ValueError(f"{row.parameter}: incompatible mapping unit")
    eligible = [r for r in rows if r.status == "confirmed" and r.component_kind == "editable" and plan["values_mm"][r.parameter] is not None]
    pending = sorted(set(plan["values_mm"]) - {r.parameter for r in eligible})
    result = {"status": "review_required", "simulated_only": port.simulated,
              "cad_executed": False, "cad_release_approved": False,
              "mechanical_checks": {k: "unverified" for k in ("mates", "interference", "motion")},
              "pending_mapping": pending, "changes": [], "save_as": None}
    with port.writer():
        port.preflight(eligible, destination)
        changes = []
        for row in eligible:
            target = number(plan["values_mm"][row.parameter])
            # Solver values are mm for lengths, while pending counts remain null.
            if row.unit == "m":
                target /= 1000
            lo, hi = row.allowed_range
            if not lo <= target <= hi:
                raise ValueError(f"{row.parameter}: outside allowed range")
            current = number(port.read(row))
            if not equal(current, target):
                changes.append(Change(row, current, target))
        result["changes"] = [asdict(c) for c in changes]
        if not changes:
            result["execution_status"] = "no_changes"
            return result
        checkpoint = port.checkpoint()
        try:
            for change in changes:
                # Detect stale planning state before each write.
                if not equal(port.read(change.mapping), change.before):
                    raise RuntimeError("stale operation plan")
                port.write(change.mapping, change.after)
            port.rebuild()
            for row in eligible:
                expected = number(plan["values_mm"][row.parameter]) / (1000 if row.unit == "m" else 1)
                if not equal(port.read(row), expected):
                    raise RuntimeError("readback mismatch")
            port.save_as(destination)
            port.reopen(destination)
            for row in eligible:
                expected = number(plan["values_mm"][row.parameter]) / (1000 if row.unit == "m" else 1)
                if not equal(port.read(row), expected):
                    raise RuntimeError("reopen readback mismatch")
        except Exception as exc:
            result.update(status="failed", execution_status="failed", error=str(exc))
            try:
                port.restore(checkpoint)
                result["recovery_status"] = "restored"
            except Exception as recovery:
                result.update(recovery_status="recovery_required", recovery_error=str(recovery))
            return result
        result.update(execution_status="simulated_pass" if port.simulated else "readback_verified",
                      cad_executed=not port.simulated, save_as=destination)
        return result
