"""Offline graph/DOF and axis-aligned box checks, not native SW evidence."""
from itertools import combinations
from math import isfinite


def _box(box):
    if len(box) != 6 or not all(isinstance(x, (int, float)) and not isinstance(x, bool) and isfinite(x) for x in box):
        raise ValueError("AABB requires six finite mm coordinates")
    if any(box[i] >= box[i+3] for i in range(3)):
        raise ValueError("invalid AABB extents")
    return tuple(box)


def interference(components, clearance_mm=0):
    if not isfinite(clearance_mm) or clearance_mm < 0:
        raise ValueError("nonnegative finite clearance required")
    hits, missing = [], []
    boxes = {}
    for c in components:
        if c.get("bbox_mm") is None:
            missing.append(c["id"])
        else:
            boxes[c["id"]] = _box(c["bbox_mm"])
    for a,b in combinations(boxes, 2):
        x,y = boxes[a], boxes[b]
        overlap = [min(x[i+3], y[i+3])-max(x[i],y[i]) for i in range(3)]
        if all(v > -clearance_mm for v in overlap):
            hits.append({"components": [a,b], "overlap_mm": overlap,
                         "kind": "aabb_overlap" if all(v > 0 for v in overlap) else "clearance_risk"})
    return {"candidates": hits, "missing_geometry": missing, "native_status": "unverified"}


def inspect_assembly(components, mates, transmissions=()):
    nodes = {c["id"]: c for c in components}
    if len(nodes) != len(components):
        raise ValueError("duplicate component id")
    adjacency = {k: set() for k in nodes}
    removed = dict.fromkeys(nodes, 0)
    issues = []
    # Scalar DOF accounting is a conservative heuristic; no Jacobian rank claim.
    rank = {"fixed": 6, "coincident": 1, "parallel": 2, "concentric": 4, "distance": 1, "angle": 1}
    for m in mates:
        a,b = m["a"],m["b"]
        if a not in nodes or b not in nodes or a == b:
            issues.append({"kind": "invalid_reference", "mate": m})
            continue
        if m.get("suppressed"):
            continue
        if m["type"] not in rank:
            issues.append({"kind": "unsupported_mate", "mate": m})
            continue
        # Assign heuristic removal to the explicitly nominated moving component.
        moving = m.get("moving", b)
        if moving not in (a,b):
            issues.append({"kind": "invalid_moving_component", "mate": m})
            continue
        adjacency[a].add(b)
        adjacency[b].add(a)
        removed[moving] += rank[m["type"]]
    anchored = {k for k,c in nodes.items() if c.get("fixed")}
    reachable = set(anchored)
    frontier = list(anchored)
    while frontier:
        for other in adjacency[frontier.pop()] - reachable:
            reachable.add(other)
            frontier.append(other)
    dof = {}
    for k,c in nodes.items():
        dof[k] = 0 if c.get("fixed") else max(0,6-removed[k])
        if removed[k] > 6 and not c.get("fixed"):
            issues.append({"kind": "possible_redundancy", "component": k})
        if k not in reachable:
            issues.append({"kind": "unanchored", "component": k})
        if "expected_dof" in c and dof[k] != c["expected_dof"]:
            issues.append({"kind": "dof_mismatch", "component": k, "estimated": dof[k]})
    edges = {}
    for t in transmissions:
        a,b = t["driver"],t["driven"]
        ratio = t.get("ratio")
        if a not in nodes or b not in nodes or isinstance(ratio,bool) or not isinstance(ratio,(int,float)) or not isfinite(ratio) or ratio == 0:
            issues.append({"kind": "invalid_transmission", "transmission": t})
            continue
        if b in edges:
            issues.append({"kind": "multiple_drivers", "component": b})
        edges[b] = (a,ratio)
    def resolve(k, stack):
        if k in stack:
            raise ValueError("transmission cycle: " + " -> ".join(stack+[k]))
        if k not in edges:
            return (k,1.0)
        parent,r = edges[k]
        root,factor = resolve(parent,stack+[k])
        return root,factor*r
    speeds = {}
    for k in edges:
        try:
            root,factor = resolve(k,[])
            speeds[k] = {"root": root, "speed_ratio": factor}
        except ValueError as exc:
            issues.append({"kind": "transmission_cycle", "detail": str(exc)})
    return {"mode": "offline_heuristic", "estimated_dof": dof, "transmissions": speeds,
            "issues": issues, "interference": interference(components),
            "native_checks": {k: "unverified" for k in ("mates","motion","interference")}}


def sample_motion(components, trajectories, times, clearance_mm=0):
    """trajectories[id](time) -> world translation (mm); samples are not a sweep proof."""
    frames = []
    for time in times:
        if not isinstance(time,(int,float)) or not isfinite(time):
            raise ValueError("finite sample time required")
        moved = []
        for c in components:
            row = dict(c)
            if c["id"] in trajectories and c.get("bbox_mm") is not None:
                delta = trajectories[c["id"]](time)
                if len(delta) != 3 or not all(isfinite(v) for v in delta):
                    raise ValueError("finite xyz translation required")
                row["bbox_mm"] = [v+delta[i%3] for i,v in enumerate(_box(c["bbox_mm"]))]
            moved.append(row)
        frames.append({"time_s": time, **interference(moved,clearance_mm)})
    return {"mode": "sampled_translation_aabb", "frames": frames, "native_status": "unverified"}

