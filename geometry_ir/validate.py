"""Geometry-IR validator (geometry-ir-validation/1).

The validator is the IR's gatekeeper for the build side. It judges an
IR document on its own, without the original tree: the C# side must be
able to trust the same verdict from the message alone.

Two severities, never mixed:

* ``errors`` -- the IR is malformed and must be refused outright:
  wrong format, undeclared or non-mm units, duplicate ids, unknown
  feature types, dangling or cyclic dependencies, malformed sketch
  geometry, out-of-range per-job values.
* ``pending`` -- the IR is well-formed but not buildable yet: a node
  is marked pending_confirmation, a per-job value is missing, a
  placeholder fillet / chamfer cannot execute, a sketch has too few
  points, an unfold input is missing. Pending is reported, never
  papered over with a substituted number.

The ``derived`` section is ignored entirely: deleting it must not
change the verdict, because derived values are cross-checks, not
inputs.
"""

from __future__ import annotations

from .ir import BEND_PARAM_KEYS, IR_VERSION, SUPPORTED_FEATURE_TYPES

VALIDATION_VERSION = "geometry-ir-validation/1"


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _topo_ok(features: list) -> str | None:
    """Return an error string if the dependency graph is cyclic."""
    indegree = {f["id"]: 0 for f in features}
    followers = {f["id"]: [] for f in features}
    for feature in features:
        for dep in feature["depends_on"]:
            followers[dep].append(feature["id"])
            indegree[feature["id"]] += 1
    ready = [f["id"] for f in features if indegree[f["id"]] == 0]
    placed = 0
    while ready:
        node_id = ready.pop(0)
        placed += 1
        for follower in followers[node_id]:
            indegree[follower] -= 1
            if indegree[follower] == 0:
                ready.append(follower)
    if placed != len(features):
        return "dependency cycle in features"
    return None


def validate_ir(ir: dict) -> dict:
    """Validate a geometry-ir/1 document. Never raises on content."""
    errors: list[str] = []
    pending: list[dict] = []

    def pend(node_id, reason):
        pending.append({"node_id": node_id, "reason": reason})

    if not isinstance(ir, dict):
        return {
            "validation_version": VALIDATION_VERSION,
            "ok": False,
            "errors": ["ir document must be an object"],
            "pending": [],
            "feature_count": 0,
            "bend_count": 0,
        }
    if ir.get("format") != IR_VERSION:
        errors.append(
            "unsupported format: %r (expected %r)"
            % (ir.get("format"), IR_VERSION)
        )
    if ir.get("units") != "mm":
        errors.append(
            "units must be explicitly 'mm', got %r" % (ir.get("units"),)
        )
    if ir.get("angles_unit") != "degrees":
        errors.append(
            "angles_unit must be explicitly 'degrees', got %r"
            % (ir.get("angles_unit"),)
        )
    features = ir.get("features")
    if not isinstance(features, list) or not features:
        errors.append("ir needs a non-empty 'features' list")
        return {
            "validation_version": VALIDATION_VERSION,
            "ok": False,
            "errors": errors,
            "pending": pending,
            "feature_count": 0,
            "bend_count": 0,
        }
    seen = set()
    by_id = {}
    for feature in features:
        if not isinstance(feature, dict):
            errors.append("feature entry must be an object")
            continue
        node_id = feature.get("id")
        if not isinstance(node_id, str) or not node_id:
            errors.append("feature needs a non-empty string id")
            continue
        if node_id in seen:
            errors.append("duplicate feature id: %s" % node_id)
            continue
        seen.add(node_id)
        by_id[node_id] = feature
        node_type = feature.get("type")
        if node_type not in SUPPORTED_FEATURE_TYPES:
            errors.append(
                "node %s: unknown feature type: %r" % (node_id, node_type)
            )
            continue
        depends_on = feature.get("depends_on", [])
        if not isinstance(depends_on, list) or not all(
            isinstance(d, str) for d in depends_on
        ):
            errors.append(
                "node %s: depends_on must be a list of ids" % node_id
            )
        params = feature.get("params", {})
        if not isinstance(params, dict):
            errors.append("node %s: params must be an object" % node_id)
            params = {}
        if feature.get("status") == "pending_confirmation":
            for reason in feature.get("pending_reasons", []):
                pend(node_id, str(reason))
            if not feature.get("pending_reasons"):
                pend(node_id, "pending_confirmation")
        if node_type in ("fillet", "chamfer"):
            pend(node_id, "placeholder_not_executable:%s" % node_type)
        if node_type == "sketch":
            points = params.get("points")
            if (
                not isinstance(points, list)
                or any(
                    not isinstance(p, (list, tuple)) or len(p) != 2
                    or not _is_number(p[0]) or not _is_number(p[1])
                    for p in points
                )
            ):
                errors.append(
                    "node %s: sketch points must be a list of [x, y] numbers"
                    % node_id
                )
            elif len(points) < 3:
                pend(node_id, "sketch_too_few_points")
        elif node_type == "bend":
            for key in BEND_PARAM_KEYS:
                if not _is_number(params.get(key)):
                    pend(node_id, "missing_param:%s" % key)
            t = params.get("thickness_mm")
            r = params.get("radius_mm")
            a = params.get("angle_degrees")
            k = params.get("k_factor")
            if _is_number(t) and t <= 0:
                errors.append("node %s: thickness_mm must be > 0" % node_id)
            if _is_number(r) and r < 0:
                errors.append("node %s: radius_mm must be >= 0" % node_id)
            if _is_number(a) and not (0.0 < a < 180.0):
                errors.append(
                    "node %s: angle_degrees must be in (0, 180)" % node_id
                )
            if _is_number(k) and not (0.0 <= k <= 1.0):
                errors.append(
                    "node %s: k_factor must be in [0, 1]" % node_id
                )
        elif node_type == "revolve":
            profile_id = params.get("profile_sketch")
            if not isinstance(profile_id, str) or not profile_id:
                pend(node_id, "missing_param:profile_sketch")
            elif profile_id not in by_id and profile_id not in [
                f.get("id") for f in features
            ]:
                errors.append(
                    "node %s: profile_sketch references unknown id %s"
                    % (node_id, profile_id)
                )
            elif profile_id not in feature.get("depends_on", []):
                pend(node_id, "profile_not_wired_in_depends_on")
            angle = params.get("angle_degrees")
            if not _is_number(angle):
                pend(node_id, "missing_param:angle_degrees")
            elif not (0.0 < angle <= 360.0):
                errors.append(
                    "node %s: angle_degrees must be in (0, 360]" % node_id
                )
            axis = params.get("axis")
            if not isinstance(axis, dict):
                pend(node_id, "missing_param:axis")
            else:
                try:
                    dx = float(axis["direction"][0])
                    dy = float(axis["direction"][1])
                    if dx == 0.0 and dy == 0.0:
                        errors.append(
                            "node %s: axis direction must be non-zero"
                            % node_id
                        )
                except (KeyError, TypeError, ValueError, IndexError):
                    pend(node_id, "missing_param:axis")
        elif node_type == "hole":
            diameter = params.get("diameter_mm")
            if not _is_number(diameter):
                pend(node_id, "missing_param:diameter_mm")
            elif diameter <= 0:
                errors.append(
                    "node %s: diameter_mm must be > 0" % node_id
                )
        elif node_type == "extrude":
            depth = params.get("depth_mm")
            if not _is_number(depth):
                pend(node_id, "missing_param:depth_mm")
            elif depth <= 0:
                errors.append(
                    "node %s: depth_mm must be > 0" % node_id
                )
        elif node_type == "sheetmetal":
            for ref in params.get("bend_refs", []):
                if ref not in [f.get("id") for f in features]:
                    errors.append(
                        "node %s: bend_ref references unknown id %s"
                        % (node_id, ref)
                    )
            outline = params.get("outline_ref")
            if outline is not None and outline not in [
                f.get("id") for f in features
            ]:
                errors.append(
                    "node %s: outline_ref references unknown id %s"
                    % (node_id, outline)
                )
    for feature in features:
        if not isinstance(feature, dict):
            continue
        for dep in feature.get("depends_on", []):
            if isinstance(dep, str) and dep not in seen:
                errors.append(
                    "node %s depends on missing id %s"
                    % (feature.get("id"), dep)
                )
            if dep == feature.get("id"):
                errors.append(
                    "node %s depends on itself" % feature.get("id")
                )
    cycle = _topo_ok(
        [f for f in features if isinstance(f, dict) and "id" in f]
    ) if not errors else None
    if cycle is not None:
        errors.append(cycle)
    bend_count = sum(
        1
        for f in features
        if isinstance(f, dict) and f.get("type") == "bend"
    )
    return {
        "validation_version": VALIDATION_VERSION,
        "ok": not errors and not pending,
        "errors": errors,
        "pending": pending,
        "feature_count": len(features),
        "bend_count": bend_count,
    }
