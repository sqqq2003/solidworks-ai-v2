"""Feature planning from extracted DXF geometry.

The planner turns geometry + relations into an ordered, sourced
feature plan that a later native builder (module 4) can consume:

* ``contour`` — a closed outline (explicit closed polyline, or a
  chain of segments whose endpoints close a loop).
* ``hole`` — a circle fully inside a contour.
* ``bend_line_candidate`` — an open straight segment that follows
  the manual-bend-candidate rule already used by ``cad_analyzer``
  (open + straight); a BEND/FOLD layer name raises confidence but
  is never the only basis.
* ``flat_pattern`` — one contour plus its bend-line candidates.
  Unfold numbers are NOT computed here without job parameters.

Job parameters (thickness / radius / angle / K factor) are inputs,
never defaults. When they are missing or invalid, bend features are
marked ``pending_confirmation`` with the missing keys listed, and no
BA/BD number is emitted. This is the per-job rule from the
#25 sheet-metal review: t=2.5 / R=1 / K=0.36 is one factory measured
case, not a default, and it appears nowhere in this module.

The plan is JSON-ready. Feature ids are stable (f-001, ...) in
emission order: contours, holes, bend candidates, flat patterns.
"""

from __future__ import annotations

import math

from dxf_extract.geometry import GeometryDoc, Segment, flatten_segments
from dxf_extract.relations import COINCIDENCE_TOL_MM

JOB_PARAM_KEYS = ("thickness_mm", "radius_mm", "angle_degrees", "k_factor")
BEND_LAYER_HINTS = ("BEND", "FOLD", "BENDING", "CREASE")


def _key(point: tuple[float, float]) -> tuple[float, float]:
    return (round(point[0], 4), round(point[1], 4))


def _is_straight(points: list[tuple[float, float]]) -> bool:
    """cad_analyzer's effectively-straight rule for open polylines."""
    if len(points) < 2:
        return False
    start, end = points[0], points[-1]
    length = math.dist(start, end)
    if length <= 1e-9:
        return False
    unit_x = (end[0] - start[0]) / length
    unit_y = (end[1] - start[1]) / length
    tolerance = max(length * 1e-3, 1e-4)
    for point in points[1:-1]:
        lateral = abs(
            (point[0] - start[0]) * unit_y - (point[1] - start[1]) * unit_x
        )
        if lateral > tolerance:
            return False
    return True


def _point_in_polygon(point: tuple[float, float], polygon: list[tuple[float, float]]) -> bool:
    """Even-odd ray casting. Vertices are chord approximations of arcs."""
    inside = False
    count = len(polygon)
    for index in range(count):
        x1, y1 = polygon[index]
        x2, y2 = polygon[(index + 1) % count]
        if (y1 > point[1]) != (y2 > point[1]):
            x_at_y = x1 + (point[1] - y1) * (x2 - x1) / (y2 - y1)
            if point[0] < x_at_y:
                inside = not inside
    return inside


def _distance_point_to_segment(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    dx, dy = end[0] - start[0], end[1] - start[1]
    length_sq = dx * dx + dy * dy
    if length_sq <= 0.0:
        return math.dist(point, start)
    t = max(0.0, min(1.0, ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length_sq))
    return math.dist(point, (start[0] + t * dx, start[1] + t * dy))


def _validate_job_params(job_params: dict | None) -> tuple[dict | None, list[str]]:
    """Return (clean params or None, missing/invalid keys)."""
    if not job_params:
        return None, list(JOB_PARAM_KEYS)
    problems: list[str] = []
    clean: dict[str, float] = {}
    for key in JOB_PARAM_KEYS:
        value = job_params.get(key)
        if value is None:
            problems.append(key)
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            problems.append(key)
            continue
        if not math.isfinite(float(value)):
            problems.append(key)
            continue
        clean[key] = float(value)
    if clean.get("thickness_mm", 0.0) <= 0:
        problems.append("thickness_mm")
    if clean.get("radius_mm", -1.0) < 0:
        problems.append("radius_mm")
    angle = clean.get("angle_degrees", 0.0)
    if not (0.0 < angle < 180.0):
        problems.append("angle_degrees")
    k_factor = clean.get("k_factor", -1.0)
    if not (0.0 <= k_factor <= 1.0):
        problems.append("k_factor")
    if problems:
        return None, sorted(set(problems))
    return clean, []


def _bend_numbers(params: dict) -> dict:
    """BA/BD for one bend from per-job parameters (sheet-metal rules).

    BA = theta_rad * (R + K*t); BD = 2*(R+t)*tan(theta/2) - BA.
    No value here is a default: every input came from job_params.
    """
    thickness = params["thickness_mm"]
    radius = params["radius_mm"]
    angle = params["angle_degrees"]
    k_factor = params["k_factor"]
    theta_rad = math.radians(angle)
    bend_allowance = theta_rad * (radius + k_factor * thickness)
    bend_deduction = 2.0 * (radius + thickness) * math.tan(theta_rad / 2.0) - bend_allowance
    return {
        "thickness_mm": thickness,
        "radius_mm": radius,
        "angle_degrees": angle,
        "k_factor": k_factor,
        "bend_allowance_mm": bend_allowance,
        "bend_deduction_mm": bend_deduction,
    }


def _find_closed_loops(segments: list[Segment]) -> tuple[list[dict], list[str]]:
    """Chain segments into closed loops, in either traversal direction.

    A loop is only emitted when every vertex on the walk has exactly
    one unused continuation. A branching vertex (more than one unused
    continuation) makes the loop ambiguous: no loop is guessed, the
    vertex is reported pending. A dead end (no continuation) simply
    means the segment is not part of a loop — e.g. a bend line
    spanning a flat pattern — and is not flagged.
    """
    by_point: dict[tuple[float, float], list[Segment]] = {}
    for seg in segments:
        by_point.setdefault(_key(seg.start), []).append(seg)
        by_point.setdefault(_key(seg.end), []).append(seg)
    used: set[int] = set()
    loops: list[dict] = []
    pending: list[str] = []
    seg_index = {id(seg): index for index, seg in enumerate(segments)}
    for index, seg in enumerate(segments):
        if index in used:
            continue
        # Walk entries: (segment, from_point, to_point).
        walk: list[tuple[Segment, tuple[float, float], tuple[float, float]]] = [
            (seg, seg.start, seg.end)
        ]
        used.add(index)
        start_key = _key(seg.start)
        current_end = _key(seg.end)
        ambiguous = False
        while current_end != start_key:
            candidates = [
                cand
                for cand in by_point.get(current_end, [])
                if seg_index[id(cand)] not in used
            ]
            if len(candidates) == 0:
                break
            if len(candidates) > 1:
                ambiguous = True
                break
            nxt = candidates[0]
            if _key(nxt.start) == current_end:
                step = (nxt, nxt.start, nxt.end)
                current_end = _key(nxt.end)
            else:
                step = (nxt, nxt.end, nxt.start)
                current_end = _key(nxt.start)
            walk.append(step)
            used.add(seg_index[id(nxt)])
        if not ambiguous and current_end == start_key and len(walk) >= 3:
            points = [walk[0][1]]
            for _, _, to_point in walk:
                points.append(to_point)
            loops.append(
                {
                    "points": [[x, y] for x, y in points],
                    "sources": [piece.source_id for piece, _, _ in walk],
                    "assembled": True,
                }
            )
        elif ambiguous:
            pending.append(
                "ambiguous_loop_vertex_at_"
                + ",".join(f"{current_end[0]:.4f}:{current_end[1]:.4f}")
            )
            # Release the walk: its segments stay available for other
            # walks instead of being consumed by a guessed loop.
            for piece, _, _ in walk:
                used.discard(seg_index[id(piece)])
    return loops, pending


def plan_features(
    doc: GeometryDoc,
    relations: list[dict] | None = None,
    job_params: dict | None = None,
) -> dict:
    """Build the feature plan for an extracted geometry document."""
    params, param_problems = _validate_job_params(job_params)
    features: list[dict] = []
    pending: list[str] = []
    counter = 0

    def next_id() -> str:
        nonlocal counter
        counter += 1
        return f"f-{counter:03d}"

    segments = flatten_segments(doc)
    contours: list[dict] = []

    # 1. Contours from explicit closed polylines.
    for entity in doc.entities:
        if entity.type not in ("LWPOLYLINE", "POLYLINE"):
            continue
        geometry = entity.geometry or {}
        if not geometry.get("closed"):
            continue
        points = [tuple(point) for point in geometry["points"]]
        contours.append(
            {
                "points": [[x, y] for x, y in points],
                "sources": [entity.id],
                "assembled": False,
            }
        )
    # 2. Contours assembled by chaining open segments.
    chained, loop_pending = _find_closed_loops(
        [seg for seg in segments if seg.kind == "line"]
        + [seg for seg in segments if seg.kind == "arc"]
    )
    pending.extend(loop_pending)
    # Do not double-count a closed polyline's own segments as a loop:
    # an assembled loop whose segments all come from one explicit
    # contour entity is the same contour, not a second one.
    explicit_sources = {frozenset(contour["sources"]) for contour in contours}
    for loop in chained:
        if frozenset(loop["sources"]) in explicit_sources:
            continue
        contours.append(loop)

    contour_features: list[dict] = []
    for contour in contours:
        feature = {
            "id": next_id(),
            "type": "contour",
            "params": {
                "points": contour["points"],
                "assembled_from_segments": contour["assembled"],
            },
            "sources": contour["sources"],
            "confidence": "medium" if contour["assembled"] else "high",
            "status": "confirmed",
            "pending_reasons": [],
        }
        contour_features.append(feature)
        features.append(feature)

    # 3. Holes: circles fully inside a contour, clear of its boundary.
    for entity in doc.entities:
        if entity.type != "CIRCLE" or not entity.geometry:
            continue
        centre = tuple(entity.geometry["center"])
        radius = entity.geometry["radius"]
        placed = False
        for contour_feature in contour_features:
            polygon = [tuple(point) for point in contour_feature["params"]["points"]]
            if not _point_in_polygon(centre, polygon):
                continue
            touches = False
            for index in range(len(polygon)):
                start = polygon[index]
                end = polygon[(index + 1) % len(polygon)]
                if _distance_point_to_segment(centre, start, end) <= radius + 1e-3:
                    touches = True
                    break
            if touches:
                pending.append(f"circle_{entity.id}_touches_contour_boundary_pending")
                placed = True
                break
            features.append(
                {
                    "id": next_id(),
                    "type": "hole",
                    "params": {
                        "center": [centre[0], centre[1]],
                        "diameter_mm": 2.0 * radius,
                        "radius_mm": radius,
                        "inside_contour": contour_feature["id"],
                    },
                    "sources": [entity.id],
                    "confidence": "high",
                    "status": "confirmed",
                    "pending_reasons": [],
                }
            )
            placed = True
            break
        if not placed:
            pending.append(f"circle_{entity.id}_outside_any_contour_pending")

    # 4. Bend-line candidates: open straight segments that are NOT
    # already part of a contour. A closed rectangle's four edges are
    # open straight segments too, but they are the outline — emitting
    # them as bend lines would be a false positive. Contour
    # membership wins over bend candidacy.
    contour_sources: set[str] = set()
    for contour_feature in contour_features:
        contour_sources.update(contour_feature["sources"])
    bend_features: list[dict] = []
    for entity in doc.entities:
        if entity.id in contour_sources:
            continue
        geometry = entity.geometry or {}
        candidates: list[tuple[float, float, float, float]] = []
        if entity.type == "LINE":
            candidates.append(
                (
                    geometry["start"][0],
                    geometry["start"][1],
                    geometry["end"][0],
                    geometry["end"][1],
                )
            )
        elif entity.type in ("LWPOLYLINE", "POLYLINE") and not geometry.get("closed"):
            points = [tuple(point) for point in geometry["points"]]
            if _is_straight(points):
                candidates.append(
                    (points[0][0], points[0][1], points[-1][0], points[-1][1])
                )
        for start_x, start_y, end_x, end_y in candidates:
            layer_hint = any(
                hint in entity.layer.upper() for hint in BEND_LAYER_HINTS
            )
            bend_params: dict = {
                "start": [start_x, start_y],
                "end": [end_x, end_y],
                "length_mm": math.dist((start_x, start_y), (end_x, end_y)),
                "layer_hint": layer_hint,
            }
            reasons: list[str] = []
            if params is None:
                reasons.append(f"job_params_missing:{','.join(param_problems)}")
                status = "pending_confirmation"
                confidence = "high" if layer_hint else "medium"
            else:
                bend_params.update(_bend_numbers(params))
                status = "confirmed"
                confidence = "high" if layer_hint else "medium"
            feature = {
                "id": next_id(),
                "type": "bend_line_candidate",
                "params": bend_params,
                "sources": [entity.id],
                "confidence": confidence,
                "status": status,
                "pending_reasons": reasons,
            }
            bend_features.append(feature)
            features.append(feature)

    # 4b. Plan-level pending for missing job parameters, but only when
    # the plan actually contains bend features that need them (a plan
    # without bends has nothing pending on that account).
    if bend_features and params is None:
        pending.append(f"job_params_missing:{','.join(param_problems)}")

    # 5. Flat pattern: one contour + its bend candidates.
    if contour_features and bend_features:
        outline = contour_features[0]
        flat_status = (
            "confirmed"
            if all(feature["status"] == "confirmed" for feature in bend_features)
            else "pending_confirmation"
        )
        flat_reasons = []
        if params is None:
            flat_reasons.append(f"job_params_missing:{','.join(param_problems)}")
        features.append(
            {
                "id": next_id(),
                "type": "flat_pattern",
                "params": {
                    "outline": outline["id"],
                    "bend_lines": [feature["id"] for feature in bend_features],
                    "note": (
                        "Unfold length needs leg measurements from the "
                        "contour geometry; only per-bend BA/BD are computed "
                        "here, and only when job parameters are supplied."
                    ),
                },
                "sources": list(
                    dict.fromkeys(
                        list(outline["sources"])
                        + [
                            source
                            for feature in bend_features
                            for source in feature["sources"]
                        ]
                    )
                ),
                "confidence": "medium",
                "status": flat_status,
                "pending_reasons": flat_reasons,
            }
        )

    # 6. Dimension cross-checks: diameter/radius dimensions vs circles.
    matched_dimensions: set[str] = set()
    for entity in doc.entities:
        if entity.type != "DIMENSION" or not entity.geometry:
            continue
        geometry = entity.geometry
        if geometry["dim_type"] not in (3, 4):
            continue
        centre = geometry["centre"]
        defpoint = geometry["defpoint"]
        matched = False
        if centre is not None and defpoint is not None:
            for other in doc.entities:
                if other.type != "CIRCLE" or not other.geometry:
                    continue
                other_centre = other.geometry["center"]
                other_radius = other.geometry["radius"]
                if math.dist(centre, other_centre) > COINCIDENCE_TOL_MM:
                    continue
                if abs(math.dist(centre, defpoint) - other_radius) > 1e-3:
                    continue
                value = 2.0 * other_radius if geometry["dim_type"] == 3 else other_radius
                features.append(
                    {
                        "id": next_id(),
                        "type": "dimension_check",
                        "params": {
                            "dimension": entity.id,
                            "circle": other.id,
                            "value_mm": value,
                        },
                        "sources": [entity.id, other.id],
                        "confidence": "high",
                        "status": "confirmed",
                        "pending_reasons": [],
                    }
                )
                matched = True
                matched_dimensions.add(entity.id)
                break
        if not matched:
            pending.append(f"dimension_{entity.id}_unmatched_circle_pending")

    # 7. Carry the extractor's own flags into the plan, except the
    # "needs circle match" note of a dimension that was matched.
    for entity in doc.entities:
        if entity.status == "flagged":
            remaining = [
                flag
                for flag in entity.flags
                if not (
                    entity.id in matched_dimensions
                    and flag == "diameter_radius_needs_circle_match"
                )
            ]
            if remaining:
                pending.append(f"entity_{entity.id}_flagged:{','.join(remaining)}")
    for flag in doc.flags:
        if flag.startswith("entity_"):
            continue
        pending.append(flag)

    return {
        "plan_version": "dxf-extract/1",
        "source_file": doc.source_file,
        "units": doc.units,
        "features": features,
        "relations": relations or [],
        "pending": sorted(set(pending)),
        "stats": {
            "entity_count": len(doc.entities),
            "flagged_entity_count": sum(
                1 for entity in doc.entities if entity.status == "flagged"
            ),
            "feature_count": len(features),
            "relation_count": len(relations or []),
        },
    }
