"""Dimension-relation inference over extracted geometry.

Every relation here is computed from the file's own numbers — never
from a textbook table or a guessed parameter:

* coincident endpoints (within tolerance),
* parallel / perpendicular straight segments,
* line-to-circle tangency (distance from centre to the line equals
  the radius, within tolerance, and the tangent point lies on the
  arc span for ARC entities),
* concentric circles/arcs, equal radii.

Tolerances are absolute, in millimetres, and recorded in the output
so a reader can judge each relation. Relations are evidence, not
decisions: the planner turns them into features with confidence
levels, and anything ambiguous stays pending.
"""

from __future__ import annotations

import math

from dxf_extract.geometry import GeometryDoc, Segment, flatten_segments

COINCIDENCE_TOL_MM = 1e-4
ANGLE_TOL_DEG = 0.5
DIST_TOL_MM = 1e-3


def _angle_of(segment: Segment) -> float:
    return math.degrees(
        math.atan2(
            segment.end[1] - segment.start[1],
            segment.end[0] - segment.start[0],
        )
    )


def _angle_diff_deg(a: float, b: float) -> float:
    diff = abs((a - b) % 180.0)
    return min(diff, 180.0 - diff)


def _point_on_arc(segment: Segment, point: tuple[float, float]) -> bool:
    """True when a point lies on an arc segment's span."""
    if segment.kind != "arc" or segment.center is None:
        return True
    angle = math.degrees(math.atan2(point[1] - segment.center[1], point[0] - segment.center[0]))
    start = segment.start_angle_deg or 0.0
    end = segment.end_angle_deg or 0.0
    if segment.ccw:
        span = (end - start) % 360.0 or 360.0
        rel = (angle - start) % 360.0
    else:
        span = (start - end) % 360.0 or 360.0
        rel = (start - angle) % 360.0
    return rel <= span + ANGLE_TOL_DEG


def _line_distance_to_point(segment: Segment, point: tuple[float, float]) -> tuple[float, tuple[float, float]]:
    """Perpendicular distance from a point to a line segment's line."""
    x1, y1 = segment.start
    x2, y2 = segment.end
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy)
    if length <= 0.0:
        return math.dist(segment.start, point), segment.start
    t = ((point[0] - x1) * dx + (point[1] - y1) * dy) / (length * length)
    foot = (x1 + t * dx, y1 + t * dy)
    return abs((point[0] - x1) * dy - (point[1] - y1) * dx) / length, foot


def infer_relations(doc: GeometryDoc) -> list[dict]:
    """Infer pairwise relations. Returns JSON-ready dicts."""
    relations: list[dict] = []
    segments = flatten_segments(doc)
    lines = [seg for seg in segments if seg.kind == "line"]
    circles = [
        entity
        for entity in doc.entities
        if entity.type == "CIRCLE" and entity.geometry
    ]
    arcs = [seg for seg in segments if seg.kind == "arc"]

    # Coincident endpoints (segments, any kind).
    endpoints: list[tuple[str, str, tuple[float, float]]] = []
    for seg in segments:
        endpoints.append((seg.source_id, "start", seg.start))
        endpoints.append((seg.source_id, "end", seg.end))
    for index in range(len(endpoints)):
        for other in range(index + 1, len(endpoints)):
            id_a, _, point_a = endpoints[index]
            id_b, _, point_b = endpoints[other]
            if id_a == id_b:
                continue
            if math.dist(point_a, point_b) <= COINCIDENCE_TOL_MM:
                relations.append(
                    {
                        "kind": "coincident",
                        "entities": sorted({id_a, id_b}),
                        "point": [point_a[0], point_a[1]],
                        "tolerance_mm": COINCIDENCE_TOL_MM,
                    }
                )

    # Parallel / perpendicular straight segments.
    for index in range(len(lines)):
        for other in range(index + 1, len(lines)):
            seg_a, seg_b = lines[index], lines[other]
            diff = _angle_diff_deg(_angle_of(seg_a), _angle_of(seg_b))
            if diff <= ANGLE_TOL_DEG:
                distance, _ = _line_distance_to_point(seg_a, seg_b.start)
                relations.append(
                    {
                        "kind": "parallel",
                        "entities": sorted({seg_a.source_id, seg_b.source_id}),
                        "angle_diff_deg": diff,
                        "distance_mm": distance,
                    }
                )
            elif abs(diff - 90.0) <= ANGLE_TOL_DEG:
                relations.append(
                    {
                        "kind": "perpendicular",
                        "entities": sorted({seg_a.source_id, seg_b.source_id}),
                        "angle_diff_deg": diff,
                    }
                )

    # Line-to-circle tangency (circles and arcs).
    round_entities: list[tuple[str, tuple[float, float], float, Segment | None]] = []
    for entity in circles:
        geometry = entity.geometry or {}
        round_entities.append(
            (entity.id, tuple(geometry["center"]), geometry["radius"], None)
        )
    for seg in arcs:
        if seg.center is not None and seg.radius is not None:
            round_entities.append((seg.source_id, seg.center, seg.radius, seg))
    for line in lines:
        for entity_id, centre, radius, arc_seg in round_entities:
            distance, foot = _line_distance_to_point(line, centre)
            if abs(distance - radius) > DIST_TOL_MM:
                continue
            if arc_seg is not None and not _point_on_arc(arc_seg, foot):
                continue
            relations.append(
                {
                    "kind": "tangent",
                    "entities": sorted({line.source_id, entity_id}),
                    "tangent_point": [foot[0], foot[1]],
                    "distance_minus_radius_mm": distance - radius,
                }
            )

    # Concentric / equal radius (circles and arc segments).
    for index in range(len(round_entities)):
        for other in range(index + 1, len(round_entities)):
            id_a, centre_a, radius_a, _ = round_entities[index]
            id_b, centre_b, radius_b, _ = round_entities[other]
            if id_a == id_b:
                continue
            if math.dist(centre_a, centre_b) <= COINCIDENCE_TOL_MM:
                relations.append(
                    {
                        "kind": "concentric",
                        "entities": sorted({id_a, id_b}),
                        "center": [centre_a[0], centre_a[1]],
                    }
                )
            elif abs(radius_a - radius_b) <= DIST_TOL_MM:
                relations.append(
                    {
                        "kind": "equal_radius",
                        "entities": sorted({id_a, id_b}),
                        "radius_mm": radius_a,
                    }
                )
    return relations
