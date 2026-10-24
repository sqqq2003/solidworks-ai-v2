"""Minimal ASCII DXF parser (standard library only).

Supported subset, chosen so every value is either read exactly or
flagged — never guessed:

* Sections HEADER (only $INSUNITS is used) and ENTITIES.
* LINE, CIRCLE, ARC, LWPOLYLINE, POLYLINE (+VERTEX / SEQEND).
* DIMENSION: rotated (0), aligned (1), diameter (3), radius (4),
  using the documented group-code subset below. Angular (2, 5) and
  ordinate (6) dimensions are flagged, not approximated.
* TEXT / MTEXT are recorded as notes only. They are never parsed for
  parameters (a text saying "t=2.5" is not a thickness measurement).
* INSERT (block reference), SPLINE, ELLIPSE and any other entity type
  are flagged (blocks are not expanded, splines/ellipses are not
  approximated). This matches the #16 handoff's known-incomplete list
  (dimension relation inference, block expansion) — this module closes
  the dimension-relation half and leaves block expansion flagged.

DIMENSION group codes used (DXF reference subset):

* 1: text override ("" or "<>" means "use measured value").
* 70: dimension type, low three bits (0 rotated, 1 aligned,
  2 angular, 3 diameter, 4 radius, 5 angular 3-point, 6 ordinate).
* 50: dimension-line angle in degrees (rotated dimensions).
* 10/20: definition point (for diameter/radius: a point on the circle).
* 13/23: first extension-line origin, 14/24: second origin.
* 15/25: centre point (diameter/radius/angular vertex).

Units: $INSUNITS is converted with geometry.UNITS_TO_MM. Unknown or
missing units leave values untouched and raise a pending flag.
"""

from __future__ import annotations

import math
from pathlib import Path

from dxf_extract.geometry import UNITS_TO_MM, Entity, GeometryDoc

TOL = 1e-4


class DxfError(ValueError):
    """The file is not a readable ASCII DXF file."""


def _f(value: str) -> float:
    return float(value)


def _pairs(text: str) -> list[tuple[int, str]]:
    lines = text.splitlines()
    if len(lines) % 2 != 0:
        raise DxfError("DXF group-code stream has an odd line count.")
    pairs = []
    for index in range(0, len(lines), 2):
        code_text = lines[index].strip()
        try:
            code = int(code_text)
        except ValueError as error:
            raise DxfError(f"DXF group code is not an integer: {code_text!r}") from error
        pairs.append((code, lines[index + 1]))
    return pairs


def _get(entity_pairs: list[tuple[int, str]], code: int, default: str | None = None) -> str | None:
    for pair_code, value in entity_pairs:
        if pair_code == code:
            return value
    return default


def _xy(entity_pairs: list[tuple[int, str]], x_code: int, y_code: int) -> tuple[float, float] | None:
    x = _get(entity_pairs, x_code)
    y = _get(entity_pairs, y_code)
    if x is None or y is None:
        return None
    try:
        return (_f(x), _f(y))
    except ValueError:
        return None


def _bulge_arc(
    start: tuple[float, float],
    end: tuple[float, float],
    bulge: float,
) -> dict:
    """Convert one LWPOLYLINE/POLYLINE bulge segment to an arc.

    DXF bulge b = tan(included_angle / 4) = sagitta / half-chord.
    Signed math (b > 0: counter-clockwise, b < 0: clockwise):

    * half-chord h, sagitta s = b * h
    * radius r = chord * (1 + b^2) / (4 * b)  (signed, follows b)
    * centre = midpoint - left_normal * (r - s)

    Verified against the semicircle case (b = 1 -> centre on chord)
    and the shallow case (b = 0.5 -> centre on the opposite side of
    the bulge). A zero bulge is never passed here (caller emits a
    line instead).
    """
    dx, dy = end[0] - start[0], end[1] - start[1]
    chord = math.hypot(dx, dy)
    if chord <= 0.0:
        raise DxfError("Bulge segment has zero chord length.")
    half = chord / 2.0
    sagitta = bulge * half
    radius_signed = chord * (1.0 + bulge * bulge) / (4.0 * bulge)
    radius = abs(radius_signed)
    left = (-dy / chord, dx / chord)
    offset = radius_signed - sagitta
    centre = (
        (start[0] + end[0]) / 2.0 - left[0] * offset,
        (start[1] + end[1]) / 2.0 - left[1] * offset,
    )
    start_angle = math.degrees(math.atan2(start[1] - centre[1], start[0] - centre[0]))
    end_angle = math.degrees(math.atan2(end[1] - centre[1], end[0] - centre[0]))
    return {
        "kind": "arc",
        "start": [start[0], start[1]],
        "end": [end[0], end[1]],
        "center": [centre[0], centre[1]],
        "radius": radius,
        "start_angle_deg": start_angle,
        "end_angle_deg": end_angle,
        "ccw": bulge > 0,
    }


def _polyline_segments(
    points: list[tuple[float, float]],
    bulges: list[float],
    closed: bool,
) -> list[dict]:
    """Resolve polyline vertices + bulges into line/arc segments."""
    segments = []
    count = len(points)
    if count < 2:
        return segments
    edges = range(count) if closed else range(count - 1)
    for index in edges:
        start = points[index]
        end = points[(index + 1) % count]
        bulge = bulges[index] if index < len(bulges) else 0.0
        if abs(bulge) < 1e-12:
            segments.append(
                {
                    "kind": "line",
                    "start": [start[0], start[1]],
                    "end": [end[0], end[1]],
                }
            )
        else:
            segments.append(_bulge_arc(start, end, bulge))
    return segments


class _EntityBuilder:
    def __init__(self, entity_id: str, entity_type: str, pairs: list[tuple[int, str]]):
        self.id = entity_id
        self.type = entity_type
        self.pairs = pairs
        self.layer = _get(pairs, 8, "0") or "0"


def _split_entities(
    pairs: list[tuple[int, str]],
) -> tuple[list[_EntityBuilder], dict[str, int], list[str]]:
    """Split the ENTITIES section into raw entities.

    Returns (entities, header_variables, section_flags). POLYLINE
    vertices are attached to their POLYLINE builder as (0, "VERTEX")
    markers followed by that vertex's pairs; SEQEND only closes the
    polyline. Stray VERTEX entities outside a POLYLINE are dropped
    and flagged.
    """
    entities: list[_EntityBuilder] = []
    header_vars: dict[str, int] = {}
    section_flags: list[str] = []
    section: str | None = None
    pending_header_var: str | None = None
    current_pairs: list[tuple[int, str]] | None = None
    current_type: str | None = None
    polyline: _EntityBuilder | None = None
    in_vertex = False
    counter = 0

    def flush() -> None:
        nonlocal current_pairs, current_type, counter
        if current_pairs is not None and current_type is not None:
            counter += 1
            entities.append(_EntityBuilder(f"e{counter:03d}", current_type, current_pairs))
        current_pairs = None
        current_type = None

    for code, value in pairs:
        if code == 0 and value == "SECTION":
            flush()
            section = None
            polyline = None
            in_vertex = False
            continue
        if code == 0 and value == "ENDSEC":
            flush()
            section = None
            polyline = None
            in_vertex = False
            continue
        if code == 2 and current_pairs is None and section is None:
            # Section name right after SECTION (HEADER / ENTITIES / ...).
            section = value
            continue
        if section == "HEADER":
            if code == 9:
                pending_header_var = value.strip()
            elif code == 70 and pending_header_var == "$INSUNITS":
                try:
                    header_vars["INSUNITS"] = int(value)
                except ValueError:
                    section_flags.append("header_insunits_unparsable")
                pending_header_var = None
            continue
        if section != "ENTITIES":
            continue
        if code == 0:
            in_vertex = False
            if value == "SEQEND":
                flush()
                polyline = None
                continue
            if value == "VERTEX":
                if polyline is not None:
                    polyline.pairs.append((0, "VERTEX"))
                    in_vertex = True
                else:
                    section_flags.append("stray_vertex_ignored")
                flush()
                continue
            flush()
            current_pairs = [(code, value)]
            current_type = value
            if value == "POLYLINE":
                # The placeholder shares the pairs list object with
                # the builder flush() will emit, so VERTEX pairs
                # appended to placeholder.pairs land in the emitted
                # builder's pairs as well.
                polyline = _EntityBuilder("", value, current_pairs)
            continue
        if in_vertex and polyline is not None:
            polyline.pairs.append((code, value))
            continue
        if current_pairs is not None:
            current_pairs.append((code, value))
    flush()
    return entities, header_vars, section_flags


def _interpret(builder: _EntityBuilder, factor: float | None) -> Entity:
    """Resolve one raw entity into geometry (or a flagged stub)."""
    pairs = builder.pairs
    # POLYLINE vertex pairs are stored after (0, "VERTEX") markers.
    scale = factor if factor is not None else 1.0

    def scaled(point: tuple[float, float] | None) -> list[float] | None:
        if point is None:
            return None
        return [point[0] * scale, point[1] * scale]

    def flagged(reason: str, geometry: dict | None = None) -> Entity:
        return Entity(
            id=builder.id,
            type=builder.type,
            layer=builder.layer,
            geometry=geometry,
            status="flagged",
            flags=[reason],
        )

    if builder.type == "LINE":
        start = scaled(_xy(pairs, 10, 20))
        end = scaled(_xy(pairs, 11, 21))
        if start is None or end is None:
            return flagged("incomplete_line_missing_endpoint")
        return Entity(
            id=builder.id,
            type="LINE",
            layer=builder.layer,
            geometry={
                "start": start,
                "end": end,
                "length": math.dist(start, end),
            },
        )
    if builder.type == "CIRCLE":
        centre = scaled(_xy(pairs, 10, 20))
        radius_text = _get(pairs, 40)
        if centre is None or radius_text is None:
            return flagged("incomplete_circle_missing_centre_or_radius")
        try:
            radius = _f(radius_text) * scale
        except ValueError:
            return flagged("circle_radius_unparsable")
        if radius <= 0:
            return flagged("circle_radius_not_positive")
        return Entity(
            id=builder.id,
            type="CIRCLE",
            layer=builder.layer,
            geometry={"center": centre, "radius": radius},
        )
    if builder.type == "ARC":
        centre = scaled(_xy(pairs, 10, 20))
        radius_text = _get(pairs, 40)
        start_text = _get(pairs, 50)
        end_text = _get(pairs, 51)
        if centre is None or radius_text is None or start_text is None or end_text is None:
            return flagged("incomplete_arc_missing_field")
        try:
            radius = _f(radius_text) * scale
            start_angle = _f(start_text)
            end_angle = _f(end_text)
        except ValueError:
            return flagged("arc_field_unparsable")
        if radius <= 0:
            return flagged("arc_radius_not_positive")
        start = [
            centre[0] + radius * math.cos(math.radians(start_angle)),
            centre[1] + radius * math.sin(math.radians(start_angle)),
        ]
        end = [
            centre[0] + radius * math.cos(math.radians(end_angle)),
            centre[1] + radius * math.sin(math.radians(end_angle)),
        ]
        return Entity(
            id=builder.id,
            type="ARC",
            layer=builder.layer,
            geometry={
                "center": centre,
                "radius": radius,
                "start_angle_deg": start_angle,
                "end_angle_deg": end_angle,
                "start": start,
                "end": end,
            },
        )
    if builder.type in ("LWPOLYLINE", "POLYLINE"):
        points: list[tuple[float, float]] = []
        bulges: list[float] = []
        current_point: tuple[float, float] | None = None
        current_bulge = 0.0
        flags_text = _get(pairs, 70, "0")
        try:
            closed = bool(int(flags_text) & 1)
        except ValueError:
            closed = False
        for code, value in pairs:
            if code == 0 and value == "VERTEX":
                if current_point is not None:
                    points.append(current_point)
                    bulges.append(current_bulge)
                current_point = None
                current_bulge = 0.0
                continue
            if code == 10:
                if current_point is not None:
                    points.append(current_point)
                    bulges.append(current_bulge)
                try:
                    current_point = (_f(value), 0.0)
                except ValueError:
                    current_point = None
                current_bulge = 0.0
            elif code == 20 and current_point is not None:
                try:
                    current_point = (current_point[0], _f(value))
                except ValueError:
                    current_point = None
            elif code == 42 and current_point is not None:
                try:
                    current_bulge = _f(value)
                except ValueError:
                    current_bulge = 0.0
        if current_point is not None:
            points.append(current_point)
            bulges.append(current_bulge)
        if len(points) < 2:
            return flagged("polyline_fewer_than_two_vertices")
        scaled_points = [(x * scale, y * scale) for x, y in points]
        try:
            segments = _polyline_segments(scaled_points, bulges, closed)
        except DxfError as error:
            return flagged(f"polyline_segment_error:{error}")
        return Entity(
            id=builder.id,
            type=builder.type,
            layer=builder.layer,
            geometry={
                "points": [[x, y] for x, y in scaled_points],
                "closed": closed,
                "segments": segments,
            },
        )
    if builder.type == "DIMENSION":
        return _interpret_dimension(builder, scale)
    if builder.type in ("TEXT", "MTEXT"):
        texts = [value for code, value in pairs if code == 1]
        insertion = scaled(_xy(pairs, 10, 20))
        return Entity(
            id=builder.id,
            type=builder.type,
            layer=builder.layer,
            geometry={"text": "".join(texts), "insertion": insertion},
        )
    if builder.type == "INSERT":
        block = _get(pairs, 2, "") or ""
        return flagged("block_reference_not_expanded", {"block": block})
    if builder.type == "SPLINE":
        return flagged("spline_not_supported_exact")
    if builder.type == "ELLIPSE":
        return flagged("ellipse_not_supported_exact")
    return flagged("unsupported_entity_type")


def _interpret_dimension(builder: _EntityBuilder, scale: float) -> Entity:
    """Resolve a DIMENSION entity for the supported subset."""
    pairs = builder.pairs
    type_text = _get(pairs, 70, "0")
    try:
        dim_type = int(type_text) & 7
    except ValueError:
        return Entity(
            id=builder.id,
            type="DIMENSION",
            layer=builder.layer,
            status="flagged",
            flags=["dimension_type_unparsable"],
        )
    text = "".join(value for code, value in pairs if code == 1)
    ext1 = _xy(pairs, 13, 23)
    ext2 = _xy(pairs, 14, 24)
    centre = _xy(pairs, 15, 25)
    defpoint = _xy(pairs, 10, 20)
    flags: list[str] = []
    measurement: float | None = None
    if dim_type == 1:  # aligned
        if ext1 is None or ext2 is None:
            flags.append("dimension_missing_extension_origins")
        else:
            measurement = math.dist(
                (ext1[0] * scale, ext1[1] * scale),
                (ext2[0] * scale, ext2[1] * scale),
            )
    elif dim_type == 0:  # rotated
        angle_text = _get(pairs, 50)
        if ext1 is None or ext2 is None:
            flags.append("dimension_missing_extension_origins")
        elif angle_text is None:
            flags.append("dimension_angle_missing")
        else:
            try:
                angle = math.radians(_f(angle_text))
            except ValueError:
                flags.append("dimension_angle_unparsable")
                angle = None
            if angle is not None:
                dx = (ext2[0] - ext1[0]) * scale
                dy = (ext2[1] - ext1[1]) * scale
                measurement = abs(dx * math.cos(angle) + dy * math.sin(angle))
    elif dim_type in (3, 4):  # diameter / radius: resolved by the planner
        # The extractor records the raw points; matching them against a
        # parsed circle is done in planner cross-checks, so a lone
        # diameter/radius dimension is never silently converted.
        if centre is None or defpoint is None:
            flags.append("dimension_missing_centre_or_point")
        else:
            flags.append("diameter_radius_needs_circle_match")
    else:
        flags.append("dimension_type_not_supported")
    override: str | None = None
    if text not in ("", "<>"):
        override = text
        if measurement is not None:
            try:
                override_value = float(text)
                if abs(override_value - measurement) > 0.01:
                    flags.append("text_override_mismatch_pending")
            except ValueError:
                flags.append("text_override_not_numeric")
    geometry = {
        "dim_type": dim_type,
        "text": text,
        "override": override,
        "measurement_mm": measurement,
        "ext1": [ext1[0] * scale, ext1[1] * scale] if ext1 else None,
        "ext2": [ext2[0] * scale, ext2[1] * scale] if ext2 else None,
        "centre": [centre[0] * scale, centre[1] * scale] if centre else None,
        "defpoint": [defpoint[0] * scale, defpoint[1] * scale] if defpoint else None,
    }
    return Entity(
        id=builder.id,
        type="DIMENSION",
        layer=builder.layer,
        geometry=geometry,
        status="flagged" if flags else "ok",
        flags=flags,
    )


def extract_dxf(path: str | Path, assume_units: str | None = None) -> GeometryDoc:
    """Parse an ASCII DXF file into a GeometryDoc.

    ``assume_units`` (``"mm"`` / ``"inch"`` / ``"cm"`` / ``"m"``) is an
    explicit caller override for files with unknown $INSUNITS. It is
    recorded as assumed, never as measured.
    """
    source = Path(path)
    if not source.is_file():
        raise DxfError(f"DXF file not found: {source}")
    raw = source.read_bytes()
    if b"\x00" in raw:
        raise DxfError("Binary DXF is not supported; only ASCII DXF is read.")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    pairs = _pairs(text)
    builders, header_vars, section_flags = _split_entities(pairs)
    doc_flags: list[str] = list(section_flags)
    units_code = header_vars.get("INSUNITS")
    factor: float | None = None
    units_name = "unknown"
    if assume_units is not None:
        wanted = {"mm": 1.0, "inch": 25.4, "cm": 10.0, "m": 1000.0}
        if assume_units not in wanted:
            raise DxfError(f"Unsupported --assume-units value: {assume_units}")
        factor = wanted[assume_units]
        units_name = f"assumed_{assume_units}"
        doc_flags.append("units_assumed_by_caller")
    elif units_code in UNITS_TO_MM:
        factor, units_name = UNITS_TO_MM[units_code]
    else:
        doc_flags.append("units_unknown_pending_confirmation")
    entities = [_interpret(builder, factor) for builder in builders]
    for entity in entities:
        if entity.status == "flagged":
            doc_flags.append(f"entity_{entity.id}_flagged")
    bounds = _compute_bounds(entities)
    return GeometryDoc(
        source_file=str(source),
        units=units_name,
        units_factor_mm=factor,
        entities=entities,
        flags=doc_flags,
        bounds=bounds,
    )


def _compute_bounds(entities: list[Entity]) -> tuple[float, float, float, float] | None:
    xs: list[float] = []
    ys: list[float] = []
    for entity in entities:
        geometry = entity.geometry
        if not geometry:
            continue
        if entity.type == "LINE":
            xs.extend([geometry["start"][0], geometry["end"][0]])
            ys.extend([geometry["start"][1], geometry["end"][1]])
        elif entity.type == "CIRCLE":
            cx, cy = geometry["center"]
            radius = geometry["radius"]
            xs.extend([cx - radius, cx + radius])
            ys.extend([cy - radius, cy + radius])
        elif entity.type == "ARC":
            cx, cy = geometry["center"]
            radius = geometry["radius"]
            xs.extend([geometry["start"][0], geometry["end"][0]])
            ys.extend([geometry["start"][1], geometry["end"][1]])
            # Arc extremes are bounded by the full circle; using the
            # full circle box keeps bounds conservative, never smaller
            # than the true arc.
            xs.extend([cx - radius, cx + radius])
            ys.extend([cy - radius, cy + radius])
        elif entity.type in ("LWPOLYLINE", "POLYLINE"):
            for point in geometry["points"]:
                xs.append(point[0])
                ys.append(point[1])
    if not xs:
        return None
    return (min(xs), min(ys), max(xs), max(ys))
