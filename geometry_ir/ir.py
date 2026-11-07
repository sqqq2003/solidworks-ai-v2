"""Feature-tree -> geometry-IR serializer (geometry-ir/1).

The IR is a faithful, self-contained copy of a feature tree plus
derived cross-check values. Rules that matter:

* Units are explicit: millimetres for lengths, degrees for angles.
  A tree without units == "mm" is refused, never assumed.
* Every per-job value (thickness, radius, angle, K factor) is carried
  verbatim from its feature node. This module defines no default for
  any of them and invents none: a missing value is the validator's
  pending item, never a substituted number.
* The ``derived`` section is computed from the inputs for cross-check
  only (bend BA/BD, unfold length, revolve volume). Derived values
  are never inputs: re-validating an IR with its derived section
  removed must give the same verdict, and the build request never
  reads derived values.
* Structural problems (unknown type, duplicate id, dangling or cyclic
  dependency, malformed sketch geometry) are hard input errors
  (IRError). Per-job gaps are the validator's pending items, not
  serializer errors, so a partial tree still serializes for review.
"""

from __future__ import annotations

import copy
import math

IR_VERSION = "geometry-ir/1"

# Feature types the IR accepts. Mirrors feature_tree SUPPORTED_TYPES so
# the IR can carry every tree #36/#44 can express. "fillet" and
# "chamfer" are placeholders in the tree as well: the IR carries them
# and the validator marks them pending_not_executable.
SUPPORTED_FEATURE_TYPES = frozenset(
    ["sketch", "extrude", "hole", "bend", "sheetmetal", "check", "fillet",
     "chamfer", "revolve"]
)

# Types a CONTRACT.md section 12 build request may cover: a sheet-metal
# part is sketch + holes + bends + the sheetmetal group (+ checks).
# Extrude / revolve solids and placeholder fillet / chamfer cannot go
# through the sheet-metal S1 build as-is; the build step reports them
# as pending instead of silently dropping them.
SHEETMETAL_BUILD_TYPES = frozenset(
    ["sketch", "hole", "bend", "sheetmetal", "check"]
)

BEND_PARAM_KEYS = ("thickness_mm", "radius_mm", "angle_degrees", "k_factor")


class IRError(ValueError):
    """Structural input error: the tree cannot become an IR at all."""


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _bend_numbers(angle_degrees, radius_mm, k_factor, thickness_mm) -> dict:
    """BA / BD from explicit per-job parameters.

    BA = theta_rad * (R + K*t); BD = 2*(R+t)*tan(theta/2) - BA.
    Same formulas as csharp-bridge/SHEET_METAL_RULES.md. Every
    argument is required by the caller; there is no default here.
    """
    theta = math.radians(float(angle_degrees))
    ba = theta * (float(radius_mm) + float(k_factor) * float(thickness_mm))
    bd = (
        2.0 * (float(radius_mm) + float(thickness_mm)) * math.tan(theta / 2.0)
        - ba
    )
    return {"bend_allowance_mm": ba, "bend_deduction_mm": bd}


def _shoelace(points):
    """Return (signed area, centroid) of a polygon, or None if degenerate."""
    area2 = 0.0
    cx = 0.0
    cy = 0.0
    for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1]):
        cross = x1 * y2 - x2 * y1
        area2 += cross
        cx += (x1 + x2) * cross
        cy += (y1 + y2) * cross
    if area2 == 0.0:
        return None
    area = area2 / 2.0
    return area, (cx / (3.0 * area2), cy / (3.0 * area2))


def _sketch_geometry(node: dict) -> dict:
    """Sketch geometry block: points, closed flag, segments.

    Raises IRError on malformed geometry. A sketch with fewer than
    three points is not malformed here (the validator marks it
    pending); it simply yields no closing segment.
    """
    params = node["params"]
    points = params.get("points")
    if (
        not isinstance(points, list)
        or any(
            not isinstance(p, (list, tuple)) or len(p) != 2
            or not _is_number(p[0]) or not _is_number(p[1])
            for p in points
        )
    ):
        raise IRError(
            "node %s: sketch points must be a list of [x, y] numbers"
            % node["id"]
        )
    closed = params.get("closed", True)
    if not isinstance(closed, bool):
        raise IRError("node %s: sketch closed must be a boolean" % node["id"])
    pts = [[float(p[0]), float(p[1])] for p in points]
    segments = [
        {"start": pts[i], "end": pts[i + 1]} for i in range(len(pts) - 1)
    ]
    if closed and len(pts) >= 2:
        segments.append({"start": pts[-1], "end": pts[0]})
    return {"points": pts, "closed": closed, "segments": segments}


def _execution_order(nodes: list) -> list:
    """Topological order (Kahn, input-order stable). Raises on cycles."""
    indegree = {n["id"]: 0 for n in nodes}
    followers = {n["id"]: [] for n in nodes}
    for node in nodes:
        for dep in node["depends_on"]:
            followers[dep].append(node["id"])
            indegree[node["id"]] += 1
    ready = [n["id"] for n in nodes if indegree[n["id"]] == 0]
    order = []
    while ready:
        node_id = ready.pop(0)
        order.append(node_id)
        for follower in followers[node_id]:
            indegree[follower] -= 1
            if indegree[follower] == 0:
                ready.append(follower)
    if len(order) != len(nodes):
        raise IRError("dependency cycle in feature tree")
    return order


def _derived(nodes: list) -> dict:
    """Derived cross-check values. Never inputs, never defaults.

    Bends with missing or out-of-range parameters are listed under
    ``uncomputed_bends`` with a reason instead of being silently
    skipped; the validator reports the same gaps as pending.
    """
    by_id = {n["id"]: n for n in nodes}
    bends = {}
    uncomputed = []
    for node in nodes:
        if node["type"] != "bend":
            continue
        params = node["params"]
        missing = [k for k in BEND_PARAM_KEYS if not _is_number(params.get(k))]
        if missing:
            uncomputed.append(
                {"bend_id": node["id"],
                 "reason": "missing_param:%s" % ",".join(missing)}
            )
            continue
        t = float(params["thickness_mm"])
        r = float(params["radius_mm"])
        a = float(params["angle_degrees"])
        k = float(params["k_factor"])
        if t <= 0 or r < 0 or not (0.0 < a < 180.0) or not (0.0 <= k <= 1.0):
            uncomputed.append(
                {"bend_id": node["id"], "reason": "param_out_of_range"}
            )
            continue
        bends[node["id"]] = _bend_numbers(a, r, k, t)

    groups = [n for n in nodes if n["type"] == "sheetmetal"]
    unfold_reasons = []
    unfold = None
    if len(groups) > 1:
        unfold_reasons.append("multiple_sheetmetal_groups_unsupported")
    elif len(groups) == 1:
        group = groups[0]
        straights = group["params"].get("straight_lengths_mm")
        if (
            not isinstance(straights, list) or not straights
            or any(not _is_number(v) or v < 0 for v in straights)
        ):
            unfold_reasons.append("missing_param:straight_lengths_mm")
        else:
            refs = group["params"].get("bend_refs", [])
            refs_ok = True
            total_ba = 0.0
            for ref in refs:
                if ref not in bends:
                    unfold_reasons.append("unresolved_bend_ref:%s" % ref)
                    refs_ok = False
                else:
                    total_ba += bends[ref]["bend_allowance_mm"]
            if refs_ok and not unfold_reasons:
                unfold = {
                    "unfold_length_mm": sum(float(v) for v in straights)
                    + total_ba,
                    "straight_total_mm": sum(float(v) for v in straights),
                    "total_bend_allowance_mm": total_ba,
                    "bend_ids": list(refs),
                }
    else:
        unfold_reasons.append("no_sheetmetal_group")

    revolves = {}
    uncomputed_revolves = []
    for node in nodes:
        if node["type"] != "revolve":
            continue
        profile_id = node["params"].get("profile_sketch")
        profile = by_id.get(profile_id) if isinstance(profile_id, str) else None
        if profile is None or profile["type"] != "sketch":
            uncomputed_revolves.append(
                {"revolve_id": node["id"],
                 "reason": "profile_sketch_not_found"}
            )
            continue
        try:
            geometry = _sketch_geometry(profile)
        except IRError:
            uncomputed_revolves.append(
                {"revolve_id": node["id"], "reason": "profile_malformed"}
            )
            continue
        points = geometry["points"]
        if len(points) < 3:
            uncomputed_revolves.append(
                {"revolve_id": node["id"], "reason": "profile_degenerate"}
            )
            continue
        area_centroid = _shoelace(points)
        if area_centroid is None:
            uncomputed_revolves.append(
                {"revolve_id": node["id"], "reason": "profile_degenerate"}
            )
            continue
        area, (cx, cy) = area_centroid
        axis = node["params"].get("axis")
        angle = node["params"].get("angle_degrees")
        if (
            not isinstance(axis, dict)
            or not _is_number(angle)
            or not (0.0 < float(angle) <= 360.0)
        ):
            uncomputed_revolves.append(
                {"revolve_id": node["id"],
                 "reason": "missing_or_invalid_param:axis_or_angle"}
            )
            continue
        try:
            ox, oy = float(axis["origin"][0]), float(axis["origin"][1])
            dx, dy = float(axis["direction"][0]), float(axis["direction"][1])
        except (KeyError, TypeError, ValueError, IndexError):
            uncomputed_revolves.append(
                {"revolve_id": node["id"], "reason": "missing_or_invalid_param:axis"}
            )
            continue
        norm = math.hypot(dx, dy)
        if norm == 0.0:
            uncomputed_revolves.append(
                {"revolve_id": node["id"], "reason": "axis_direction_zero"}
            )
            continue
        distance = abs(((cx - ox) * dy - (cy - oy) * dx) / norm)
        revolves[node["id"]] = {
            "profile_area_mm2": abs(area),
            "centroid_distance_mm": distance,
            "volume_mm3": abs(area) * math.radians(float(angle)) * distance,
        }

    return {
        "derived_not_input": True,
        "note": (
            "Derived from the feature inputs for cross-check only; "
            "never feed derived values back as inputs."
        ),
        "bends": bends,
        "uncomputed_bends": uncomputed,
        "unfold": unfold if unfold is not None else {
            "status": "pending", "reasons": unfold_reasons,
        },
        "revolves": revolves,
        "uncomputed_revolves": uncomputed_revolves,
    }


def tree_to_ir(tree: dict, source_ref: str | None = None) -> dict:
    """Serialize a feature-tree/1 document to a geometry-ir/1 document.

    The feature list keeps the tree's input order; ``execution_order``
    is the dependency order the build side must use. Parameters are
    deep-copied verbatim: nothing is defaulted, rounded or renamed.
    Raises IRError on structural problems only.
    """
    if not isinstance(tree, dict):
        raise IRError("tree document must be an object")
    if tree.get("tree_version") != "feature-tree/1":
        raise IRError(
            "unsupported tree_version: %r (expected 'feature-tree/1')"
            % (tree.get("tree_version"),)
        )
    if tree.get("units") != "mm":
        raise IRError(
            "units must be explicitly 'mm', got %r" % (tree.get("units"),)
        )
    raw = tree.get("features")
    if not isinstance(raw, list) or not raw:
        raise IRError("tree needs a non-empty 'features' list")
    nodes = []
    seen = set()
    for item in raw:
        if not isinstance(item, dict):
            raise IRError("feature node must be an object")
        node_id = item.get("id")
        if not isinstance(node_id, str) or not node_id:
            raise IRError("feature node needs a non-empty string id")
        if node_id in seen:
            raise IRError("duplicate feature id: %s" % node_id)
        seen.add(node_id)
        node_type = item.get("type")
        if node_type not in SUPPORTED_FEATURE_TYPES:
            raise IRError("unknown feature type: %r" % (node_type,))
        depends_on = item.get("depends_on", [])
        if not isinstance(depends_on, list) or not all(
            isinstance(d, str) for d in depends_on
        ):
            raise IRError(
                "node %s: depends_on must be a list of ids" % node_id
            )
        params = item.get("params", {})
        if not isinstance(params, dict):
            raise IRError("node %s: params must be an object" % node_id)
        sources = item.get("sources", [])
        if not isinstance(sources, list):
            raise IRError("node %s: sources must be a list" % node_id)
        nodes.append({
            "id": node_id,
            "type": node_type,
            "depends_on": list(depends_on),
            "sources": list(sources),
            "params": copy.deepcopy(params),
            "status": item.get("status", "confirmed"),
            "pending_reasons": list(item.get("pending_reasons", [])),
        })
    for node in nodes:
        for dep in node["depends_on"]:
            if dep not in seen:
                raise IRError(
                    "node %s depends on missing id %s" % (node["id"], dep)
                )
            if dep == node["id"]:
                raise IRError("node %s depends on itself" % node["id"])
    order = _execution_order(nodes)

    features = []
    for node in nodes:
        entry = {
            "id": node["id"],
            "type": node["type"],
            "depends_on": node["depends_on"],
            "sources": node["sources"],
            "params": node["params"],
            "status": node["status"],
            "pending_reasons": node["pending_reasons"],
        }
        if node["type"] == "sketch":
            entry["geometry"] = _sketch_geometry(node)
        features.append(entry)

    source = {
        "tree_name": tree.get("name", ""),
        "tree_version": "feature-tree/1",
        "units": "mm",
    }
    if source_ref is not None:
        source["source_ref"] = source_ref
    return {
        "format": IR_VERSION,
        "units": "mm",
        "angles_unit": "degrees",
        "source": source,
        "features": features,
        "execution_order": order,
        "derived": _derived(nodes),
    }
