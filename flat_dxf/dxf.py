"""Flat-pattern DXF builder (phase 1, F2).

Strip layout (one flat blank, bends in sequence order):

    leg0 | zone0 | leg1 | zone1 | ... | legN

where each leg is one straight length from the unfold report and
each zone is one bend allowance. A bend line is drawn at the centre
of its zone, across the full blank width. The strip has exactly
len(bends) + 1 legs; anything else is pending, never padded.

Bend allowance (same formula as feature_tree/unfold and
csharp-bridge/SHEET_METAL_RULES.md):

    BA = theta_rad * (R + K * t)

V-opening and process do not enter the BA formula, but they are
still required per-job inputs: they are recorded on the bend card
and a bend missing either one is pending. That is the per-job
discipline -- a job record without its die and process is not a
complete job, even if its BA happens to be computable.
"""

from __future__ import annotations

import math

DXF_VERSION = "flat-dxf/1"

REQUIRED_BEND_KEYS = (
    "thickness_mm",
    "radius_mm",
    "angle_degrees",
    "k_factor",
    "v_opening_mm",
    "process",
    "direction",
    "sequence",
)

_TOL = 1e-9


class FlatDxfError(ValueError):
    """Malformed input (wrong shape, wrong types, cyclic nothing)."""


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _bend_allowance(angle_deg, radius, k_factor, thickness) -> float:
    return math.radians(angle_deg) * (radius + k_factor * thickness)


def _validate_bend(bend: dict) -> list:
    """Pending reasons for one bend record (empty = usable)."""
    reasons = []
    if not isinstance(bend, dict):
        return ["bend_not_an_object"]
    for key in REQUIRED_BEND_KEYS:
        if key not in bend:
            reasons.append("missing_param:%s" % key)
    if reasons:
        return reasons
    t = bend["thickness_mm"]
    r = bend["radius_mm"]
    angle = bend["angle_degrees"]
    k = bend["k_factor"]
    v = bend["v_opening_mm"]
    if not _is_number(t) or t <= 0:
        reasons.append("invalid_param:thickness_mm must be > 0")
    if not _is_number(r) or r < 0:
        reasons.append("invalid_param:radius_mm must be >= 0")
    if not _is_number(angle) or not 0 < angle < 180:
        reasons.append("invalid_param:angle_degrees must be in (0, 180)")
    if not _is_number(k) or not 0 <= k <= 1:
        reasons.append("invalid_param:k_factor must be in [0, 1]")
    if not _is_number(v) or v <= 0:
        reasons.append("invalid_param:v_opening_mm must be > 0")
    if not isinstance(bend["process"], str) or not bend["process"]:
        reasons.append("invalid_param:process must be a non-empty string")
    if bend["direction"] not in ("up", "down"):
        reasons.append("invalid_param:direction must be 'up' or 'down'")
    seq = bend["sequence"]
    if isinstance(seq, bool) or not isinstance(seq, int):
        reasons.append("invalid_param:sequence must be an integer")
    return reasons


def _fmt(value: float) -> str:
    return "%.4f" % value


def _pair(code: int, value: str) -> str:
    return "%3d\n%s\n" % (code, value)


def _line(layer: str, x1: float, y1: float, x2: float, y2: float) -> str:
    out = _pair(0, "LINE")
    out += _pair(8, layer)
    out += _pair(10, _fmt(x1)) + _pair(20, _fmt(y1)) + _pair(30, "0.0")
    out += _pair(11, _fmt(x2)) + _pair(21, _fmt(y2)) + _pair(31, "0.0")
    return out


def _text(layer: str, x: float, y: float, string: str) -> str:
    out = _pair(0, "TEXT")
    out += _pair(8, layer)
    out += _pair(10, _fmt(x)) + _pair(20, _fmt(y)) + _pair(30, "0.0")
    out += _pair(40, "3.5")
    out += _pair(1, string)
    return out


def _dxf_document(entities: str) -> str:
    header = (
        _pair(0, "SECTION") + _pair(2, "HEADER")
        + _pair(9, "$ACADVER") + _pair(1, "AC1009")
        + _pair(9, "$INSUNITS") + _pair(70, "4")
        + _pair(0, "ENDSEC")
    )
    layers = ""
    for name, color in (("CUT", 7), ("BEND", 1), ("NOTES", 3)):
        layers += _pair(0, "LAYER") + _pair(2, name)
        layers += _pair(70, "0") + _pair(62, str(color))
        layers += _pair(6, "Continuous")
    tables = (
        _pair(0, "SECTION") + _pair(2, "TABLES")
        + _pair(0, "TABLE") + _pair(2, "LTYPE") + _pair(70, "1")
        + _pair(0, "LTYPE") + _pair(2, "Continuous") + _pair(70, "0")
        + _pair(3, "Solid line") + _pair(72, "65") + _pair(73, "0")
        + _pair(40, "0.0") + _pair(0, "ENDTAB")
        + _pair(0, "TABLE") + _pair(2, "LAYER") + _pair(70, "3")
        + layers + _pair(0, "ENDTAB")
        + _pair(0, "TABLE") + _pair(2, "STYLE") + _pair(70, "1")
        + _pair(0, "STYLE") + _pair(2, "Standard") + _pair(70, "0")
        + _pair(40, "0.0") + _pair(41, "1.0") + _pair(50, "0.0")
        + _pair(71, "0") + _pair(42, "0.2") + _pair(3, "txt")
        + _pair(4, "") + _pair(0, "ENDTAB")
        + _pair(0, "ENDSEC")
    )
    body = (
        _pair(0, "SECTION") + _pair(2, "ENTITIES")
        + entities + _pair(0, "ENDSEC")
    )
    return header + tables + body + _pair(0, "EOF")


def build_flat_dxf(unfold_report: dict, bends: list,
                   blank_width_mm) -> dict:
    """Build the flat-pattern DXF + bend card, or a pending report.

    ``unfold_report`` is a feature_tree unfold report (status ok).
    ``bends`` is the per-job bend list (see REQUIRED_BEND_KEYS).
    ``blank_width_mm`` is the explicit flat-blank width in mm.

    Raises FlatDxfError on malformed input shape. Missing values
    and cross-check mismatches are pending, never substituted.
    """
    if not isinstance(unfold_report, dict):
        raise FlatDxfError("unfold_report must be a JSON object")
    if not isinstance(bends, list):
        raise FlatDxfError("bends must be a list")
    if not _is_number(blank_width_mm) or blank_width_mm <= 0:
        raise FlatDxfError("blank_width_mm must be a number > 0")
    pending = []
    if unfold_report.get("status") != "ok":
        pending.append("unfold_report_not_ok")
        pending.extend(
            "unfold_pending:%s" % r
            for r in unfold_report.get("pending", [])
        )
    straight = unfold_report.get("straight_lengths_mm")
    if (
        not isinstance(straight, list)
        or not straight
        or any(not _is_number(v) or v < 0 for v in straight)
    ):
        pending.append("invalid_param:straight_lengths_mm")
        straight = None
    report_bends = {}
    for entry in unfold_report.get("bends", []):
        if isinstance(entry, dict) and "bend_id" in entry:
            report_bends[entry["bend_id"]] = entry
    validated = []
    sequences = []
    for bend in bends:
        reasons = _validate_bend(bend)
        if reasons:
            pending.append(
                "bend_pending:%s:%s"
                % (bend.get("bend_id", "?"), ";".join(reasons))
            )
        else:
            validated.append(bend)
            sequences.append(bend["sequence"])
    if len(set(sequences)) != len(sequences):
        pending.append("duplicate_sequence")
    if straight is not None and len(straight) != len(bends) + 1:
        pending.append("straight_bend_count_mismatch")
    job_ids = {b.get("bend_id") for b in bends if isinstance(b, dict)}
    if set(report_bends) != job_ids:
        pending.append("bend_set_mismatch")
    if pending:
        return {
            "flat_dxf_version": DXF_VERSION,
            "status": "pending",
            "dxf_text": None,
            "bend_card": None,
            "flat_length_mm": None,
            "pending": pending,
        }
    ordered = sorted(validated, key=lambda b: b["sequence"])
    card_bends = []
    total_ba = 0.0
    cursor = 0.0
    bend_lines = []
    for index, bend in enumerate(ordered):
        ba = _bend_allowance(
            bend["angle_degrees"], bend["radius_mm"],
            bend["k_factor"], bend["thickness_mm"],
        )
        report_ba = report_bends[bend["bend_id"]].get("bend_allowance_mm")
        if not _is_number(report_ba) or abs(report_ba - ba) > _TOL:
            pending.append(
                "bend_allowance_mismatch:%s" % bend["bend_id"]
            )
            continue
        leg = float(straight[index])
        centre = cursor + leg + ba / 2.0
        bend_lines.append(centre)
        card_bends.append(
            {
                "bend_id": bend["bend_id"],
                "sequence": bend["sequence"],
                "direction": bend["direction"],
                "angle_degrees": bend["angle_degrees"],
                "thickness_mm": bend["thickness_mm"],
                "radius_mm": bend["radius_mm"],
                "k_factor": bend["k_factor"],
                "v_opening_mm": bend["v_opening_mm"],
                "process": bend["process"],
                "bend_allowance_mm": ba,
                "bend_line_x_mm": centre,
            }
        )
        total_ba += ba
        cursor += leg + ba
    if pending:
        return {
            "flat_dxf_version": DXF_VERSION,
            "status": "pending",
            "dxf_text": None,
            "bend_card": None,
            "flat_length_mm": None,
            "pending": pending,
        }
    flat_length = cursor + float(straight[-1])
    report_length = unfold_report.get("unfold_length_mm")
    if not _is_number(report_length) or abs(report_length - flat_length) > _TOL:
        return {
            "flat_dxf_version": DXF_VERSION,
            "status": "pending",
            "dxf_text": None,
            "bend_card": None,
            "flat_length_mm": None,
            "pending": ["unfold_length_mismatch"],
        }
    width = float(blank_width_mm)
    entities = ""
    entities += _line("CUT", 0.0, 0.0, flat_length, 0.0)
    entities += _line("CUT", flat_length, 0.0, flat_length, width)
    entities += _line("CUT", flat_length, width, 0.0, width)
    entities += _line("CUT", 0.0, width, 0.0, 0.0)
    for bend, centre in zip(ordered, bend_lines):
        entities += _line("BEND", centre, 0.0, centre, width)
        label = "B%s %s %sdeg" % (
            bend["sequence"], bend["direction"].upper(),
            bend["angle_degrees"],
        )
        entities += _text("NOTES", centre, width + 5.0, label)
    entities += _text(
        "NOTES", 0.0, -8.0,
        "FLAT LENGTH %.4f MM" % flat_length,
    )
    return {
        "flat_dxf_version": DXF_VERSION,
        "status": "ok",
        "dxf_text": _dxf_document(entities),
        "bend_card": {
            "flat_length_mm": flat_length,
            "blank_width_mm": width,
            "bends": card_bends,
        },
        "flat_length_mm": flat_length,
        "pending": [],
    }
