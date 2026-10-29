"""Feature-tree IR (feature-tree/1) and dependency-order validation.

A feature tree is an ordered, dependency-linked list of editable features.
This module only defines the data shape and validates it; it never talks
to SolidWorks. Execution lives in executor.py, backends in mock_backend.py
(real) and real_backend.py (stub).

Design notes (why this shape, not a silent fork of #16):

* #16's feature IR (ql5050px.cad_features, branch feat/issue15-cad-features)
  exists only on the #16 branch, not on dev/cloud-ai, and its execution
  requires host create_editable_feature / verify_feature_tree
  implementations that are not present. This module is therefore an
  independent implementation of the *same stated concepts* (ordered
  editable features, source references, pending states, cycle rejection),
  aligned field-by-field where #16's handoff documents them. When #16
  merges, an adapter layer (NOT built here) maps #16 IR <-> feature-tree/1.
* Units are always explicit millimetres / degrees. There is no default
  thickness, radius, angle or K factor anywhere in this module: every
  per-job value is a required input, and a missing value is
  pending_confirmation, never a substituted number.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

TREE_VERSION = "feature-tree/1"

# Feature types the IR accepts. "fillet" and "chamfer" are placeholders:
# they are valid IR nodes but the mock backend cannot execute them, so
# execution stops at them with pending_confirmation (never guessed).
# "revolve" was added by the feature-tree completion batch (after #36):
# a revolved solid from a closed profile sketch around an axis. Its
# validation rules (closed profile, no axis crossing, explicit angle)
# are enforced by the mock backend, not guessed.
SUPPORTED_TYPES = frozenset(
    ["sketch", "extrude", "hole", "bend", "sheetmetal", "check", "fillet", "chamfer",
     "revolve"]
)

# Types the mock backend can actually execute (sheetmetal is a group
# completion step, check is a verification-record step).
EXECUTABLE_TYPES = frozenset(
    ["sketch", "extrude", "hole", "bend", "sheetmetal", "check", "revolve"]
)


class TreeError(ValueError):
    """Tree-level input error: execution is refused before it starts."""


class CycleError(TreeError):
    """Dependency graph contains a cycle; no order is guessed."""


class MissingDependencyError(TreeError):
    """A node depends on an id that is not in the tree."""


class DuplicateIdError(TreeError):
    """Two nodes share one id."""


class UnknownTypeError(TreeError):
    """A node type is not in SUPPORTED_TYPES."""


@dataclass
class FeatureNode:
    """One editable feature.

    id: stable node id, unique within the tree.
    type: one of SUPPORTED_TYPES.
    params: type-specific parameters (see README for each type's schema).
    depends_on: ids that must execute before this node.
    sources: references back to the originating plan (module 3 feature
        ids / DXF entity ids). Informational only, never used for order.
    status: "confirmed" or "pending_confirmation".
    pending_reasons: why this node cannot execute yet (empty if confirmed).
    """

    id: str
    type: str
    params: dict = field(default_factory=dict)
    depends_on: list = field(default_factory=list)
    sources: list = field(default_factory=list)
    status: str = "confirmed"
    pending_reasons: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "params": self.params,
            "depends_on": list(self.depends_on),
            "sources": list(self.sources),
            "status": self.status,
            "pending_reasons": list(self.pending_reasons),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "FeatureNode":
        if not isinstance(data, dict):
            raise TreeError("feature node must be an object")
        node_id = data.get("id")
        if not isinstance(node_id, str) or not node_id:
            raise TreeError("feature node needs a non-empty string id")
        node_type = data.get("type")
        if node_type not in SUPPORTED_TYPES:
            raise UnknownTypeError("unknown feature type: %r" % (node_type,))
        depends_on = data.get("depends_on", [])
        if not isinstance(depends_on, list) or not all(
            isinstance(d, str) for d in depends_on
        ):
            raise TreeError("node %s: depends_on must be a list of ids" % node_id)
        params = data.get("params", {})
        if not isinstance(params, dict):
            raise TreeError("node %s: params must be an object" % node_id)
        status = data.get("status", "confirmed")
        if status not in ("confirmed", "pending_confirmation"):
            raise TreeError("node %s: unknown status %r" % (node_id, status))
        pending_reasons = data.get("pending_reasons", [])
        if not isinstance(pending_reasons, list):
            raise TreeError("node %s: pending_reasons must be a list" % node_id)
        sources = data.get("sources", [])
        if not isinstance(sources, list):
            raise TreeError("node %s: sources must be a list" % node_id)
        return cls(
            id=node_id,
            type=node_type,
            params=params,
            depends_on=depends_on,
            sources=sources,
            status=status,
            pending_reasons=pending_reasons,
        )


@dataclass
class FeatureTree:
    """A validated feature tree."""

    name: str
    units: str
    features: list
    source_plan: dict | None = None
    relations: list = field(default_factory=list)

    def to_dict(self) -> dict:
        data = {
            "tree_version": TREE_VERSION,
            "name": self.name,
            "units": self.units,
            "features": [f.to_dict() for f in self.features],
        }
        if self.source_plan is not None:
            data["source_plan"] = self.source_plan
        if self.relations:
            data["relations"] = self.relations
        return data


def parse_tree(data: dict) -> FeatureTree:
    """Parse and validate a feature-tree/1 document.

    Raises TreeError (or a subclass) on any structural problem. No order
    is guessed: duplicates, unknown types, missing dependencies and
    cycles are all hard input errors, reported before execution starts.
    """
    if not isinstance(data, dict):
        raise TreeError("tree document must be an object")
    if data.get("tree_version") != TREE_VERSION:
        raise TreeError(
            "unsupported tree_version: %r (expected %r)"
            % (data.get("tree_version"), TREE_VERSION)
        )
    if data.get("units") != "mm":
        raise TreeError(
            "units must be explicitly 'mm', got %r" % (data.get("units"),)
        )
    raw_features = data.get("features")
    if not isinstance(raw_features, list) or not raw_features:
        raise TreeError("tree needs a non-empty 'features' list")
    nodes = [FeatureNode.from_dict(item) for item in raw_features]
    seen = set()
    for node in nodes:
        if node.id in seen:
            raise DuplicateIdError("duplicate feature id: %s" % node.id)
        seen.add(node.id)
    for node in nodes:
        for dep in node.depends_on:
            if dep not in seen:
                raise MissingDependencyError(
                    "node %s depends on missing id %s" % (node.id, dep)
                )
            if dep == node.id:
                raise CycleError("node %s depends on itself" % node.id)
    relations = data.get("relations", [])
    if not isinstance(relations, list):
        raise TreeError("'relations' must be a list")
    tree = FeatureTree(
        name=data.get("name", ""),
        units="mm",
        features=nodes,
        source_plan=data.get("source_plan"),
        relations=relations,
    )
    # Cycle check runs now so a cyclic tree can never reach the executor.
    execution_order(tree)
    return tree


def execution_order(tree: FeatureTree) -> list:
    """Topological order of node ids (Kahn's algorithm, input-order stable).

    Raises CycleError listing the nodes left unplaced when the graph has
    a cycle. Dependency order is the only order used; a cyclic graph is
    never executed in a guessed order.
    """
    nodes = {node.id: node for node in tree.features}
    indegree = {node.id: 0 for node in tree.features}
    followers: dict[str, list] = {node.id: [] for node in tree.features}
    for node in tree.features:
        for dep in node.depends_on:
            followers[dep].append(node.id)
            indegree[node.id] += 1
    ready = [node.id for node in tree.features if indegree[node.id] == 0]
    order = []
    while ready:
        current = ready.pop(0)
        order.append(current)
        for nxt in followers[current]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                ready.append(nxt)
    if len(order) != len(tree.features):
        remaining = [nid for nid in nodes if nid not in order]
        raise CycleError(
            "dependency cycle involving: %s" % ", ".join(sorted(remaining))
        )
    return order


def polygon_bounds_and_area(points) -> dict:
    """Bounds + shoelace area of a 2D point list (mock readback helper).

    Points need not repeat the first point at the end; the polygon is
    treated as closed. Returns bounds and the absolute area.
    """
    xs = [float(p[0]) for p in points]
    ys = [float(p[1]) for p in points]
    area2 = 0.0
    for i in range(len(points)):
        x1, y1 = float(points[i][0]), float(points[i][1])
        x2, y2 = float(points[(i + 1) % len(points)][0]), float(
            points[(i + 1) % len(points)][1]
        )
        area2 += x1 * y2 - x2 * y1
    return {
        "min_x": min(xs),
        "min_y": min(ys),
        "max_x": max(xs),
        "max_y": max(ys),
        "area_mm2": abs(area2) / 2.0,
    }


def polygon_centroid(points) -> dict:
    """Signed-area centroid of a 2D point list (shoelace formula).

    The polygon is treated as closed, same convention as
    polygon_bounds_and_area. Returns the signed area and the centroid;
    a zero-area (degenerate) polygon has no meaningful centroid, so its
    centroid is reported as None and callers must refuse it.
    """
    area2 = 0.0
    cx2 = 0.0
    cy2 = 0.0
    for i in range(len(points)):
        x1, y1 = float(points[i][0]), float(points[i][1])
        x2, y2 = float(points[(i + 1) % len(points)][0]), float(
            points[(i + 1) % len(points)][1]
        )
        cross = x1 * y2 - x2 * y1
        area2 += cross
        cx2 += (x1 + x2) * cross
        cy2 += (y1 + y2) * cross
    if abs(area2) < 1e-12:
        return {"area_mm2": 0.0, "centroid": None}
    area = area2 / 2.0
    return {
        "area_mm2": abs(area),
        "centroid": [cx2 / (6.0 * area), cy2 / (6.0 * area)],
    }


def axis_side_distances(points, origin, direction) -> list:
    """Signed distances of points from an axis line (sketch plane).

    Positive = one side, negative = the other, zero = on the axis.
    A revolve profile must lie on one side only: points strictly on
    both sides mean the profile crosses the axis. Points exactly on
    the axis are allowed (a profile edge on the axis is normal).
    """
    dx, dy = float(direction[0]), float(direction[1])
    norm = math.hypot(dx, dy)
    ox, oy = float(origin[0]), float(origin[1])
    out = []
    for p in points:
        x, y = float(p[0]), float(p[1])
        out.append(((x - ox) * dy - (y - oy) * dx) / norm)
    return out


def bend_allowance_mm(angle_degrees: float, radius_mm: float, k_factor: float,
                       thickness_mm: float) -> dict:
    """Per-bend BA / BD from explicit per-job parameters.

    BA = theta_rad * (R + K*t); BD = 2*(R+t)*tan(theta/2) - BA.
    Same formulas as csharp-bridge/SHEET_METAL_RULES.md. No value here
    is a default: every argument is required by the caller.
    """
    theta = math.radians(float(angle_degrees))
    ba = theta * (float(radius_mm) + float(k_factor) * float(thickness_mm))
    bd = 2.0 * (float(radius_mm) + float(thickness_mm)) * math.tan(theta / 2.0) - ba
    return {"bend_allowance_mm": ba, "bend_deduction_mm": bd}
