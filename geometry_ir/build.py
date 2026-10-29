"""Build-request mapping: geometry IR -> CONTRACT.md section 12 params.

Section 12's build takes one uniform set of per-job sheet-metal
parameters (thickness / radius / angle / K) plus the caller's title,
part path, plan id and flip direction. This module maps an IR to
exactly that shape -- and refuses, with pending reasons, whenever the
IR cannot honestly supply it:

* any validation error or pending item blocks the request;
* a tree with no bends is not a sheet-metal build;
* bends whose per-job parameters differ cannot be squeezed into one
  uniform set -- the request reports bend_params_not_uniform instead
  of picking one bend's values;
* extrude / revolve solids and placeholder fillet / chamfer are not
  sheet-metal S1 work and block the request as non_sheetmetal_feature;
* flip_direction has no source in a feature tree, so the caller must
  supply it explicitly. There is no default: a missing flip direction
  is a caller error (ValueError), not a silent ``false``.

The idempotency key follows section 12.4: sha256 of
``"<plan_id>:S1:build"``. It is derived deterministically from the
caller's plan id, not a default value.
"""

from __future__ import annotations

import hashlib

from .ir import SHEETMETAL_BUILD_TYPES
from .validate import validate_ir

BUILD_REQUEST_KEYS = (
    "plan_id",
    "title",
    "part_path",
    "thickness_mm",
    "radius_mm",
    "angle_degrees",
    "k_factor",
    "flip_direction",
    "bend_count",
    "idempotency_key",
    "units",
)


def _idempotency_key(plan_id: str) -> str:
    return hashlib.sha256(("%s:S1:build" % plan_id).encode("utf-8")).hexdigest()


def to_build_request(ir: dict, *, title, part_path, plan_id,
                     flip_direction) -> tuple:
    """Map a validated IR to a section 12 build request.

    Returns ``(request_or_None, report)`` where report carries
    ``ok``, ``errors`` and ``pending``. Caller arguments are the
    caller's responsibility: a missing title / part_path / plan_id or
    a non-boolean flip_direction raises ValueError immediately.
    """
    if not isinstance(title, str) or not title:
        raise ValueError("title must be a non-empty string")
    if not isinstance(part_path, str) or not part_path:
        raise ValueError("part_path must be a non-empty string")
    if not isinstance(plan_id, str) or not plan_id:
        raise ValueError("plan_id must be a non-empty string")
    if not isinstance(flip_direction, bool):
        raise ValueError("flip_direction must be a boolean (no default)")

    report = validate_ir(ir)
    errors = list(report["errors"])
    pending = [
        "%s:%s" % (item["node_id"], item["reason"])
        for item in report["pending"]
    ]
    if errors or pending:
        return None, {"ok": False, "errors": errors, "pending": pending}

    features = ir["features"]
    non_sheetmetal = sorted(
        {f["type"] for f in features} - SHEETMETAL_BUILD_TYPES
    )
    if non_sheetmetal:
        pending.append(
            "non_sheetmetal_feature:%s" % ",".join(non_sheetmetal)
        )
        return None, {"ok": False, "errors": [], "pending": pending}
    bends = [f for f in features if f["type"] == "bend"]
    if not bends:
        pending.append("no_bends_for_sheetmetal_build")
        return None, {"ok": False, "errors": [], "pending": pending}
    signatures = {
        (
            float(b["params"]["thickness_mm"]),
            float(b["params"]["radius_mm"]),
            float(b["params"]["angle_degrees"]),
            float(b["params"]["k_factor"]),
        )
        for b in bends
    }
    if len(signatures) != 1:
        pending.append(
            "bend_params_not_uniform:%s"
            % ",".join(sorted(b["id"] for b in bends))
        )
        return None, {"ok": False, "errors": [], "pending": pending}
    thickness, radius, angle, k_factor = next(iter(signatures))
    request = {
        "plan_id": plan_id,
        "title": title,
        "part_path": part_path,
        "thickness_mm": thickness,
        "radius_mm": radius,
        "angle_degrees": angle,
        "k_factor": k_factor,
        "flip_direction": flip_direction,
        "bend_count": len(bends),
        "idempotency_key": _idempotency_key(plan_id),
        "units": "mm",
    }
    return request, {"ok": True, "errors": [], "pending": []}
