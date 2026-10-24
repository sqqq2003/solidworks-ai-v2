"""Convert a module 3 plan (dxf-extract/1) into a feature-tree/1 tree.

Compatibility contract with module 3 (branch feat/issue25-dxf-extract,
Draft PR #35). The plan shapes consumed here are exactly the ones
module 3's README documents:

* contour      -> sketch node   (params.points)
* hole         -> hole node     (params.center, params.diameter_mm;
                                  depth comes from the caller's job
                                  params, never a default)
* bend_line_candidate -> bend node (params.start/end/length_mm plus
                                  thickness/radius/angle/K from the
                                  caller's job params; missing job
                                  params -> pending_confirmation node)
* flat_pattern -> sheetmetal group node (params.outline,
                                  params.bend_lines; depends on the
                                  sketch + bend nodes it references)
* dimension_check -> check node (params.dimension/circle/value_mm;
                                  plan-level check, recorded by the
                                  mock executor, not re-measured)

Dependency wiring for converted trees (structural, not guessed
geometry): holes and bends depend on the sketch; the sheetmetal group
depends on the sketch and its bends; a dimension_check depends on the
hole derived from its circle entity when one exists. A plan feature
type this converter does not know is refused (ConverterError), never
silently dropped: dropping a feature would change the part.

Job params are an explicit per-job input dict, e.g.:
{"thickness_mm": 2.0, "radius_mm": 1.5, "angle_degrees": 90.0,
 "k_factor": 0.38, "hole_depth_spec": {"mode": "through_all"}}
Every value shown here is an example input, not a default. Missing
job params do not fail conversion; they turn the affected nodes into
pending_confirmation nodes, exactly like module 3 does.
"""

from __future__ import annotations

from .tree import FeatureNode, FeatureTree

PLAN_VERSION = "dxf-extract/1"

_JOB_KEYS = ("thickness_mm", "radius_mm", "angle_degrees", "k_factor")


class ConverterError(ValueError):
    """The plan cannot be converted (unknown type, bad shape)."""


def _job_bend_params(job_params: dict | None) -> tuple[dict, list]:
    """Split job params into bend values + missing-key reasons."""
    job_params = job_params or {}
    values = {}
    missing = []
    for key in _JOB_KEYS:
        value = job_params.get(key)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
        ):
            missing.append("job_params_missing:%s" % key)
        else:
            values[key] = float(value)
    return values, missing


def _strip_job_reasons(reasons: list) -> list:
    """Drop stale job_params_missing reasons from plan time.

    A plan built without job params carries job_params_missing reasons.
    When the caller supplies those job params at conversion time, the
    stale reasons must not survive: only the *current* missing keys
    (computed from the supplied job params) are re-attached by the
    caller below. Non-job reasons are always preserved.
    """
    return [
        r for r in reasons
        if not (isinstance(r, str) and r.startswith("job_params_missing:"))
    ]


def convert_plan(plan: dict, job_params: dict | None = None) -> FeatureTree:
    """Convert one dxf-extract/1 plan document into a FeatureTree."""
    if not isinstance(plan, dict):
        raise ConverterError("plan document must be an object")
    if plan.get("plan_version") != PLAN_VERSION:
        raise ConverterError(
            "unsupported plan_version: %r (expected %r)"
            % (plan.get("plan_version"), PLAN_VERSION)
        )
    if plan.get("units") != "mm":
        raise ConverterError(
            "plan units must be explicitly 'mm', got %r" % (plan.get("units"),)
        )
    raw_features = plan.get("features")
    if not isinstance(raw_features, list):
        raise ConverterError("plan needs a 'features' list")
    bend_values, bend_missing = _job_bend_params(job_params)
    hole_depth_spec = None
    if job_params and isinstance(job_params.get("hole_depth_spec"), dict):
        hole_depth_spec = job_params["hole_depth_spec"]

    nodes: list = []
    # plan feature id -> converted node id (same id, keeps traceability)
    entity_to_node: dict = {}
    sketch_ids: list = []

    for feature in raw_features:
        if not isinstance(feature, dict):
            raise ConverterError("plan feature must be an object")
        fid = feature.get("id")
        ftype = feature.get("type")
        params = feature.get("params", {})
        sources = feature.get("sources", [])
        plan_status = feature.get("status", "confirmed")
        plan_reasons = list(feature.get("pending_reasons", []))
        if not isinstance(params, dict):
            raise ConverterError("plan feature %s: params must be an object" % fid)

        if ftype == "contour":
            node = FeatureNode(
                id=fid, type="sketch",
                params={"points": params.get("points")},
                depends_on=[],
                sources=list(sources),
                status=plan_status, pending_reasons=plan_reasons,
            )
            sketch_ids.append(fid)
        elif ftype == "hole":
            reasons = list(plan_reasons)
            if hole_depth_spec is None:
                reasons.append("job_params_missing:hole_depth_spec")
            node = FeatureNode(
                id=fid, type="hole",
                params={
                    "center": params.get("center"),
                    "diameter_mm": params.get("diameter_mm"),
                    "depth": hole_depth_spec,
                },
                depends_on=list(sketch_ids),
                sources=list(sources),
                status=("pending_confirmation"
                        if reasons else "confirmed"),
                pending_reasons=reasons,
            )
        elif ftype == "bend_line_candidate":
            reasons = _strip_job_reasons(plan_reasons) + list(bend_missing)
            node = FeatureNode(
                id=fid, type="bend",
                params={
                    "line": {
                        "start": params.get("start"),
                        "end": params.get("end"),
                    },
                    "length_mm": params.get("length_mm"),
                    **bend_values,
                },
                depends_on=list(sketch_ids),
                sources=list(sources),
                status=("pending_confirmation"
                        if reasons else "confirmed"),
                pending_reasons=reasons,
            )
        elif ftype == "flat_pattern":
            # Group node; dependencies are wired after all nodes exist
            # (outline/bend references are plan feature ids, kept as-is
            # here and resolved in the second pass below).
            reasons = _strip_job_reasons(plan_reasons) + list(bend_missing)
            node = FeatureNode(
                id=fid, type="sheetmetal",
                params={
                    "outline_ref": params.get("outline"),
                    "bend_refs": list(params.get("bend_lines", [])),
                    "note": params.get("note", ""),
                },
                depends_on=[],
                sources=list(sources),
                status=("pending_confirmation"
                        if reasons else "confirmed"),
                pending_reasons=reasons,
            )
        elif ftype == "dimension_check":
            node = FeatureNode(
                id=fid, type="check",
                params={
                    "dimension": params.get("dimension"),
                    "circle": params.get("circle"),
                    "value_mm": params.get("value_mm"),
                },
                depends_on=[],
                sources=list(sources),
                status=plan_status, pending_reasons=plan_reasons,
            )
        else:
            raise ConverterError(
                "unknown plan feature type: %r (feature %s)"
                % (ftype, fid)
            )
        nodes.append(node)
        for entity in sources:
            entity_to_node.setdefault(entity, fid)

    # Second pass: wire flat_pattern dependencies and dimension_check
    # dependencies from the plan's own references.
    by_id = {node.id: node for node in nodes}
    for node in nodes:
        if node.type == "sheetmetal":
            deps = []
            outline = node.params.get("outline_ref")
            if outline in by_id:
                deps.append(outline)
            for bend_ref in node.params.get("bend_refs", []):
                if bend_ref in by_id:
                    deps.append(bend_ref)
            node.depends_on = deps
        elif node.type == "check":
            circle = node.params.get("circle")
            target = entity_to_node.get(circle)
            if target is not None and target != node.id:
                node.depends_on = [target]

    relations = plan.get("relations", [])
    if not isinstance(relations, list):
        relations = []
    return FeatureTree(
        name="converted from %s" % plan.get("source_file", "plan"),
        units="mm",
        features=nodes,
        source_plan={
            "format": PLAN_VERSION,
            "source_file": plan.get("source_file"),
        },
        relations=relations,
    )
