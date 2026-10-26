"""Shared geometry model for the DXF extractor.

The model is deliberately small and JSON-friendly so it can be compared
against other pipeline outputs (notably ``cad_analyzer`` primitives and
the #16 feature-plan concept) without importing them:

* ``Entity`` mirrors the DXF entity: a type, a layer and resolved
  geometry. ``cad_analyzer.Primitive`` uses the same vocabulary
  (points / closed / kind / layer / circle centre + radius); this
  module keeps its own copy so it stays dependency-free and runnable
  without ezdxf or SolidWorks.
* ``GeometryDoc`` is the whole extraction: entities, flags for
  everything that could not be read exactly, and bounds.
* ``Segment`` is the flattened line/arc piece used by relation
  inference and by the feature planner.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

PLAN_VERSION = "dxf-extract/1"

# $INSUNITS code -> (mm per unit, unit name). Codes not listed here are
# unknown on purpose: the extractor must not guess a unit.
UNITS_TO_MM = {
    1: (25.4, "inch"),
    2: (304.8, "foot"),
    4: (1.0, "mm"),
    5: (10.0, "cm"),
    6: (1000.0, "m"),
}


@dataclass(frozen=True)
class Segment:
    """One straight or arc piece, with its source entity id."""

    source_id: str
    kind: str  # "line" or "arc"
    start: tuple[float, float]
    end: tuple[float, float]
    center: tuple[float, float] | None = None
    radius: float | None = None
    start_angle_deg: float | None = None
    end_angle_deg: float | None = None
    ccw: bool = True


@dataclass
class Entity:
    """A single DXF entity after resolution."""

    id: str
    type: str
    layer: str
    geometry: dict | None = None
    status: str = "ok"  # "ok" or "flagged"
    flags: list[str] = field(default_factory=list)

    def to_json(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "layer": self.layer,
            "status": self.status,
            "flags": list(self.flags),
            "geometry": self.geometry,
        }


@dataclass
class GeometryDoc:
    """Everything extracted from one DXF file."""

    source_file: str
    units: str
    units_factor_mm: float | None
    entities: list[Entity] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    bounds: tuple[float, float, float, float] | None = None

    def to_json(self) -> dict:
        return {
            "format": PLAN_VERSION,
            "source_file": self.source_file,
            "units": self.units,
            "units_factor_mm": self.units_factor_mm,
            "bounds": list(self.bounds) if self.bounds else None,
            "flags": list(self.flags),
            "entities": [entity.to_json() for entity in self.entities],
        }


def flatten_segments(doc: GeometryDoc) -> list[Segment]:
    """Flatten every line/arc piece of every entity into segments."""
    segments: list[Segment] = []
    for entity in doc.entities:
        geometry = entity.geometry
        if not geometry:
            continue
        if entity.type == "LINE":
            segments.append(
                Segment(
                    source_id=entity.id,
                    kind="line",
                    start=tuple(geometry["start"]),
                    end=tuple(geometry["end"]),
                )
            )
        elif entity.type == "ARC":
            segments.append(
                Segment(
                    source_id=entity.id,
                    kind="arc",
                    start=tuple(geometry["start"]),
                    end=tuple(geometry["end"]),
                    center=tuple(geometry["center"]),
                    radius=geometry["radius"],
                    start_angle_deg=geometry["start_angle_deg"],
                    end_angle_deg=geometry["end_angle_deg"],
                    ccw=True,
                )
            )
        elif entity.type in ("LWPOLYLINE", "POLYLINE"):
            for piece in geometry.get("segments", []):
                if piece["kind"] == "line":
                    segments.append(
                        Segment(
                            source_id=entity.id,
                            kind="line",
                            start=tuple(piece["start"]),
                            end=tuple(piece["end"]),
                        )
                    )
                else:
                    segments.append(
                        Segment(
                            source_id=entity.id,
                            kind="arc",
                            start=tuple(piece["start"]),
                            end=tuple(piece["end"]),
                            center=tuple(piece["center"]),
                            radius=piece["radius"],
                            start_angle_deg=piece["start_angle_deg"],
                            end_angle_deg=piece["end_angle_deg"],
                            ccw=piece["ccw"],
                        )
                    )
    return segments


def arc_points(segment: Segment, steps: int = 16) -> list[tuple[float, float]]:
    """Sample points along an arc segment (used for bounds only)."""
    if segment.kind != "arc" or segment.center is None or segment.radius is None:
        return [segment.start, segment.end]
    start = math.radians(segment.start_angle_deg or 0.0)
    end = math.radians(segment.end_angle_deg or 0.0)
    if segment.ccw:
        while end <= start:
            end += 2.0 * math.pi
    else:
        while end >= start:
            end -= 2.0 * math.pi
    points = []
    for step in range(steps + 1):
        angle = start + (end - start) * step / steps
        points.append(
            (
                segment.center[0] + segment.radius * math.cos(angle),
                segment.center[1] + segment.radius * math.sin(angle),
            )
        )
    return points
