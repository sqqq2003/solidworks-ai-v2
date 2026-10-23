"""Issue #6 module 3: mate / DOF / motion / interference pre-check interfaces.

Offline framework only. None of these helpers solves SolidWorks mates, runs a
motion study, or performs a native interference check:

* ``dof_report`` applies a documented **simplified DOF table** (a teaching
  model, not the SolidWorks mate solver);
* ``motion_check`` validates sweep *parameters* only — no motion is simulated;
* ``interference_check`` is an axis-aligned bounding-box prefilter, not an
  exact solid intersection;
* ``MockMechanicalCheckPort`` implements the ``MechanicalCheckPort`` protocol
  from ``sw_api.transaction`` for tests and offline planning.

Every report carries ``mates_solved=False`` / ``sw_live=not_applicable_on_linux``
so a caller cannot mistake a mock result for a native pass.
"""

from __future__ import annotations

from typing import Iterable, Sequence

MODULE = "issue6-module3-assembly-precheck"

# Simplified DOF-removal table (total constraints per mate type).
# This is a textbook approximation for planning screens; it is NOT the
# SolidWorks mate solver and must never be quoted as one.
SIMPLIFIED_MATE_DOF: dict[str, int] = {
    "coincident": 3,  # point-point: 3 translations; plane-plane variant: 1T+2R
    "concentric": 4,
    "perpendicular": 1,
    "parallel": 2,
    "distance": 1,
    "angle": 1,
    "width": 2,
    "symmetric": 3,
    "revolute": 5,  # leaves 1 rotation
    "prismatic": 5,  # leaves 1 translation
    "cylindrical": 4,  # leaves 1T + 1R
    "planar": 3,  # leaves 1T + 2R
    "lock": 6,  # fully fixed
}

# Mate types the simplified model does not represent at all.
UNMODELED_MATE_TYPES = ("cam", "slot", "gear", "path", "linearcoupler")

BOUNDS_TOLERANCE_MM = 1e-9


def _validate_mate(mate: dict) -> str:
    if not isinstance(mate, dict):
        raise ValueError("each mate must be a dict")
    mate_type = mate.get("type")
    if not isinstance(mate_type, str) or not mate_type:
        raise ValueError("mate requires a non-empty type string")
    return mate_type.strip().lower()


def dof_report(
    *,
    components: int,
    mates: Sequence[dict],
    grounded_component: str | None = None,
) -> dict:
    """Simplified自由度 (DOF) accounting for a mate list.

    ``mates`` items look like ``{"type": "coincident", "between": ["a", "b"]}``.
    The first component is treated as grounded unless ``grounded_component``
    says otherwise. Unknown mate types contribute zero DOF and are flagged as
    ``not_modeled`` instead of being silently dropped.
    """

    if isinstance(components, bool) or not isinstance(components, int) or components < 1:
        raise ValueError("components must be a positive integer")
    mobile = components - 1
    total_dof = 6 * mobile
    rows: list[dict] = []
    removed = 0
    demanded = 0
    for index, mate in enumerate(mates):
        mate_type = _validate_mate(mate)
        if mate_type in UNMODELED_MATE_TYPES:
            rows.append(
                {
                    "index": index,
                    "type": mate_type,
                    "between": list(mate.get("between", [])),
                    "dof_removed": 0,
                    "status": "not_modeled",
                    "reason": "mate type is outside the simplified mock table",
                }
            )
            continue
        if mate_type not in SIMPLIFIED_MATE_DOF:
            raise ValueError(f"unknown mate type: {mate_type}")
        contribution = SIMPLIFIED_MATE_DOF[mate_type]
        demanded += contribution
        remaining_before = total_dof - removed
        status = "counted"
        if contribution > remaining_before:
            status = "redundant"
            contribution = remaining_before
        removed += contribution
        rows.append(
            {
                "index": index,
                "type": mate_type,
                "between": list(mate.get("between", [])),
                "dof_removed": contribution,
                "status": status,
                "reason": "" if status == "counted" else "mock hint: mate may be redundant",
            }
        )
    return {
        "module": MODULE,
        "backend": "mock",
        "model": "simplified_dof_table_not_a_solver",
        "mates_solved": False,
        "cad_executed": False,
        "sw_live": "not_applicable_on_linux",
        "components": components,
        "grounded_component": grounded_component or "first-component",
        "mobile_components": mobile,
        "dof_before": total_dof,
        "dof_removed": removed,
        "dof": max(total_dof - removed, 0),
        "dof_demanded": demanded,
        "over_constrained": demanded > total_dof,
        "rows": rows,
        "note": (
            "Simplified DOF table for planning only. SolidWorks mate solving "
            "was not run and mates are not verified."
        ),
    }


def motion_check(report: dict, *, sweep_degrees: float = 360.0) -> dict:
    """Validate motion *parameters* against a DOF report. Simulates nothing."""

    if isinstance(sweep_degrees, bool) or not isinstance(sweep_degrees, (int, float)):
        raise ValueError("sweep_degrees must be numeric")
    if not 0.0 < float(sweep_degrees) <= 360.0:
        raise ValueError("sweep_degrees must be within (0, 360]")
    dof = report.get("dof")
    if not isinstance(dof, int):
        raise ValueError("motion_check needs a dof_report result")
    return {
        "module": MODULE,
        "backend": "mock",
        "status": "not_checked",
        "motion_verified": False,
        "cad_executed": False,
        "sw_live": "not_applicable_on_linux",
        "requested_sweep_degrees": float(sweep_degrees),
        "free_dof": dof,
        "reason": (
            "mock scaffold; SolidWorks motion study was not run"
            if dof
            else "no free DOF in the simplified model; nothing to sweep"
        ),
    }


def _bounds(value) -> tuple[float, float, float, float, float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 6:
        raise ValueError("bounds must be (xmin, ymin, zmin, xmax, ymax, zmax)")
    numbers = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise ValueError("bounds must be numeric")
        numbers.append(float(item))
    xmin, ymin, zmin, xmax, ymax, zmax = numbers
    if xmin > xmax or ymin > ymax or zmin > zmax:
        raise ValueError("bounds minima must not exceed maxima")
    return (xmin, ymin, zmin, xmax, ymax, zmax)


def interference_check(parts: Sequence[dict]) -> dict:
    """Axis-aligned bounding-box interference prefilter.

    ``parts`` items look like ``{"name": "frame", "bounds": (0, 0, 0, 100, 50, 50)}``.
    Overlap volume above tolerance is reported; exact solid interference still
    requires the native check this framework does not perform.
    """

    if not isinstance(parts, (list, tuple)) or len(parts) < 2:
        raise ValueError("interference_check needs at least two parts")
    named: list[tuple[str, tuple[float, ...]]] = []
    for part in parts:
        if not isinstance(part, dict) or not part.get("name"):
            raise ValueError("each part needs a non-empty name")
        named.append((str(part["name"]), _bounds(part.get("bounds"))))
    pairs: list[dict] = []
    overlapping: list[str] = []
    for i in range(len(named)):
        for j in range(i + 1, len(named)):
            name_a, a = named[i]
            name_b, b = named[j]
            dx = min(a[3], b[3]) - max(a[0], b[0])
            dy = min(a[4], b[4]) - max(a[1], b[1])
            dz = min(a[5], b[5]) - max(a[2], b[2])
            volume = 0.0
            if dx > BOUNDS_TOLERANCE_MM and dy > BOUNDS_TOLERANCE_MM and dz > BOUNDS_TOLERANCE_MM:
                volume = dx * dy * dz
            if volume > BOUNDS_TOLERANCE_MM:
                pairs.append(
                    {
                        "parts": [name_a, name_b],
                        "overlap_volume_mm3": round(volume, 6),
                        "status": "overlap",
                    }
                )
                overlapping.extend([name_a, name_b])
            else:
                pairs.append({"parts": [name_a, name_b], "overlap_volume_mm3": 0.0, "status": "clear"})
    return {
        "module": MODULE,
        "backend": "mock_aabb",
        "exact_interference": False,
        "cad_executed": False,
        "sw_live": "not_applicable_on_linux",
        "parts": [name for name, _ in named],
        "pairs": pairs,
        "overlapping": sorted(set(overlapping)),
        "note": (
            "AABB overlap is a coarse prefilter, not a native interference "
            "check; touching faces and curved gaps are not resolved."
        ),
    }


class MockMechanicalCheckPort:
    """MechanicalCheckPort implementation for offline tests and planning.

    It answers with mock reports and never claims native evidence.
    """

    simulated = True

    def __init__(
        self,
        *,
        components: int,
        mates: Sequence[dict],
        parts: Sequence[dict],
    ) -> None:
        self.components = components
        self.mates = list(mates)
        self.parts = list(parts)

    def check_mates(self) -> dict:
        return dof_report(components=self.components, mates=self.mates)

    def check_interference(self) -> dict:
        return interference_check(self.parts)

    def check_motion(self) -> dict:
        return motion_check(self.check_mates())


def iter_mate_types(mates: Iterable[dict]) -> list[str]:
    return [_validate_mate(mate) for mate in mates]
