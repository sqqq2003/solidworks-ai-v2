"""Mock execution backend: records every step, touches no SolidWorks.

MockSwApp executes a feature tree against an in-memory part record. All
"readback" values are computed from the node's own input parameters (or
from earlier executed nodes in the same run) and are labelled
``mock_readback: True`` wherever they appear, so a mock record can never
be mistaken for a SolidWorks measurement.

Parameter discipline (mirrors the #25 sheet-metal review and the #32
build contract): thickness, radius, angle and K factor are required
per-job inputs. A missing or out-of-range value is a pending/failed
step, never a substituted number.
"""

from __future__ import annotations

from .tree import bend_allowance_mm, polygon_bounds_and_area


class StepPending(Exception):
    """A node cannot execute yet; carries pending_confirmation reasons."""

    def __init__(self, reasons):
        super().__init__("; ".join(reasons))
        self.reasons = list(reasons)


class StepFailed(Exception):
    """A node failed validation (bad parameter shape or range)."""


def _require_number(params: dict, key: str, node_id: str):
    value = params.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise StepPending(["missing_or_invalid_param:%s" % key])
    return float(value)


def _check_bend_params(params: dict, node_id: str) -> dict:
    """Validate one bend node's per-job parameters, no defaults."""
    missing = [
        key
        for key in ("thickness_mm", "radius_mm", "angle_degrees", "k_factor")
        if key not in params
        or isinstance(params[key], bool)
        or not isinstance(params[key], (int, float))
    ]
    if missing:
        raise StepPending(
            ["missing_param:%s" % key for key in missing]
        )
    thickness = float(params["thickness_mm"])
    radius = float(params["radius_mm"])
    angle = float(params["angle_degrees"])
    k_factor = float(params["k_factor"])
    problems = []
    if thickness <= 0:
        problems.append("thickness_mm must be > 0")
    if radius < 0:
        problems.append("radius_mm must be >= 0")
    if not 0 < angle < 180:
        problems.append("angle_degrees must be in (0, 180)")
    if not 0 <= k_factor <= 1:
        problems.append("k_factor must be in [0, 1]")
    if problems:
        raise StepFailed("; ".join(problems))
    line = params.get("line")
    if not isinstance(line, dict) or "start" not in line or "end" not in line:
        raise StepPending(["missing_param:line.start/end"])
    return {
        "thickness_mm": thickness,
        "radius_mm": radius,
        "angle_degrees": angle,
        "k_factor": k_factor,
        "line": line,
    }


class MockSwApp:
    """In-memory SolidWorks stand-in.

    State kept per run: executed sketches (bounds/area, for extrude
    readback), executed bends (BA/BD, for the sheetmetal group step)
    and the ordered op log. Nothing here opens, saves or closes a real
    document, and no COM object is ever created.
    """

    def __init__(self):
        self.op_log: list = []
        self.sketches: dict = {}
        self.bends: dict = {}
        self.holes: dict = {}

    def execute(self, node) -> dict:
        """Execute one node. Returns {op, result, readback}.

        Raises StepPending (cannot run yet) or StepFailed (bad params).
        """
        handler = getattr(self, "_do_" + node.type, None)
        if handler is None:
            raise StepPending(["unsupported_in_mock:%s" % node.type])
        return handler(node)

    def _record(self, node, op: str, result: dict, readback: dict) -> dict:
        entry = {
            "node_id": node.id,
            "op": op,
            "result": result,
            "readback": dict(readback, mock_readback=True),
        }
        self.op_log.append(entry)
        return entry

    def _do_sketch(self, node) -> dict:
        points = node.params.get("points")
        if (
            not isinstance(points, list)
            or len(points) < 3
            or not all(
                isinstance(p, (list, tuple)) and len(p) == 2 for p in points
            )
        ):
            raise StepPending(["missing_or_invalid_param:points"])
        try:
            shape = polygon_bounds_and_area(points)
        except (TypeError, ValueError):
            raise StepFailed("points must be numeric [x, y] pairs")
        self.sketches[node.id] = shape
        return self._record(
            node,
            "create_sketch",
            {"closed": True, "point_count": len(points)},
            {"bounds": shape, "area_mm2": shape["area_mm2"]},
        )

    def _do_extrude(self, node) -> dict:
        depth = _require_number(node.params, "depth_mm", node.id)
        direction = node.params.get("direction")
        if direction not in ("+z", "-z", "symmetric"):
            raise StepPending(["missing_or_invalid_param:direction"])
        if depth <= 0:
            raise StepFailed("depth_mm must be > 0")
        profile_area = None
        for dep in node.depends_on:
            if dep in self.sketches:
                profile_area = self.sketches[dep]["area_mm2"]
                break
        return self._record(
            node,
            "extrude",
            {"depth_mm": depth, "direction": direction},
            {"depth_mm": depth, "direction": direction,
             "profile_area_mm2": profile_area},
        )

    def _do_hole(self, node) -> dict:
        center = node.params.get("center")
        if (
            not isinstance(center, (list, tuple))
            or len(center) != 2
        ):
            raise StepPending(["missing_or_invalid_param:center"])
        diameter = _require_number(node.params, "diameter_mm", node.id)
        if diameter <= 0:
            raise StepFailed("diameter_mm must be > 0")
        depth = node.params.get("depth")
        if not isinstance(depth, dict) or "mode" not in depth:
            raise StepPending(["missing_param:depth.mode"])
        if depth["mode"] == "blind":
            blind = depth.get("depth_mm")
            if (
                isinstance(blind, bool)
                or not isinstance(blind, (int, float))
                or float(blind) <= 0
            ):
                raise StepPending(["missing_or_invalid_param:depth.depth_mm"])
            depth_readback = {"mode": "blind", "depth_mm": float(blind)}
        elif depth["mode"] == "through_all":
            depth_readback = {"mode": "through_all"}
        else:
            raise StepFailed("unknown hole depth mode: %r" % (depth["mode"],))
        self.holes[node.id] = {
            "center": [float(center[0]), float(center[1])],
            "diameter_mm": diameter,
        }
        return self._record(
            node,
            "cut_hole",
            {"center": [float(center[0]), float(center[1])],
             "diameter_mm": diameter},
            {"center": [float(center[0]), float(center[1])],
             "diameter_mm": diameter, "depth": depth_readback},
        )

    def _do_bend(self, node) -> dict:
        checked = _check_bend_params(node.params, node.id)
        numbers = bend_allowance_mm(
            checked["angle_degrees"],
            checked["radius_mm"],
            checked["k_factor"],
            checked["thickness_mm"],
        )
        self.bends[node.id] = numbers
        return self._record(
            node,
            "make_bend",
            {"line": checked["line"], **numbers},
            {"thickness_mm": checked["thickness_mm"],
             "radius_mm": checked["radius_mm"],
             "angle_degrees": checked["angle_degrees"],
             "k_factor": checked["k_factor"], **numbers},
        )

    def _do_sheetmetal(self, node) -> dict:
        # Group completion step: only reachable when every dependency
        # (sketch + bends) already executed, because the executor is
        # fail-stop and topological order puts dependencies first.
        bend_ids = [
            dep for dep in node.depends_on if dep in self.bends
        ]
        return self._record(
            node,
            "complete_sheetmetal",
            {"bend_count": len(bend_ids),
             "bend_ids": bend_ids},
            {"bend_count": len(bend_ids),
             "total_bend_allowance_mm": sum(
                 self.bends[b]["bend_allowance_mm"] for b in bend_ids
             ),
             "total_bend_deduction_mm": sum(
                 self.bends[b]["bend_deduction_mm"] for b in bend_ids
             )},
        )

    def _do_check(self, node) -> dict:
        # Verification-record step: the dimension-vs-circle match was
        # already established by module 3's plan (dimension_check is a
        # plan-level check). The mock executor records it; it does NOT
        # re-measure anything, and says so in the readback.
        value = node.params.get("value_mm")
        if value is None:
            raise StepPending(["missing_param:value_mm"])
        return self._record(
            node,
            "record_dimension_check",
            {"dimension": node.params.get("dimension"),
             "circle": node.params.get("circle")},
            {"value_mm": value,
             "plan_status": node.status,
             "mock_reverified": False,
             "note": "plan-level check from module 3; not re-measured by mock"},
        )

    def _do_fillet(self, node) -> dict:
        raise StepPending(["unsupported_in_mock:fillet"])

    def _do_chamfer(self, node) -> dict:
        raise StepPending(["unsupported_in_mock:chamfer"])
