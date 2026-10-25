"""Drawing template + mock render (phase 1, F1).

Input document (drawing-gen input, plain JSON):

    {
      "part_name": "...",
      "bounding_box_mm": {"length": L, "width": W, "height": H},
      "sheet_size": "A4",
      "scale": "1:2",
      "title_block": {
        "drawing_no": "...", "part_name": "...", "material": "...",
        "scale": "1:2", "sheet_size": "A4", "designer": "...",
        "date": "...", "revision": "..."
      },
      "dimensions": [
        {"name": "overall_length", "value_mm": 120.0,
         "source": "explicit"}
      ]
    }

Output document (drawing-gen/1): the same fields echoed, plus
``views`` (name, size, position on the sheet), ``dimensions``
(only the ones with known values), ``status`` and ``pending``.
Malformed shapes raise DrawingError (CLI exit 2); missing values
are pending (CLI exit 1).
"""

from __future__ import annotations

DRAWING_VERSION = "drawing-gen/1"

TITLE_BLOCK_FIELDS = (
    "drawing_no",
    "part_name",
    "material",
    "scale",
    "sheet_size",
    "designer",
    "date",
    "revision",
)

SHEET_SIZES_MM = {
    "A4": (297.0, 210.0),
    "A3": (420.0, 297.0),
}

_MARGIN_MM = 20.0
_GAP_MM = 10.0

MOCK_NOTE = (
    "MOCK_RENDER: cloud-side template only, not a SolidWorks "
    "drawing. Real drawing generation pending_windows_validation."
)


class DrawingError(ValueError):
    """Malformed input document."""


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _parse_scale(scale) -> float:
    if not isinstance(scale, str) or ":" not in scale:
        raise DrawingError("scale must be a string like '1:2'")
    left, right = scale.split(":", 1)
    try:
        a, b = int(left), int(right)
    except ValueError:
        raise DrawingError("scale must be a string like '1:2'") from None
    if a <= 0 or b <= 0:
        raise DrawingError("scale parts must be > 0")
    return a / b


def _layout_views(bbox: dict, factor: float, sheet: str) -> tuple:
    """View sizes/positions, or the pending reasons they overflow."""
    sheet_w, sheet_h = SHEET_SIZES_MM[sheet]
    usable_w = sheet_w - 2 * _MARGIN_MM
    usable_h = sheet_h - 2 * _MARGIN_MM
    front = (bbox["length"] * factor, bbox["height"] * factor)
    top = (bbox["length"] * factor, bbox["width"] * factor)
    side = (bbox["width"] * factor, bbox["height"] * factor)
    pending = []
    if front[0] + _GAP_MM + side[0] > usable_w:
        pending.append("view_layout_overflow:front_plus_side_exceeds_width")
    if front[1] + _GAP_MM + top[1] > usable_h:
        pending.append("view_layout_overflow:front_plus_top_exceeds_height")
    views = [
        {
            "name": "front",
            "size_mm": [front[0], front[1]],
            "position_mm": [_MARGIN_MM, _MARGIN_MM],
        },
        {
            "name": "top",
            "size_mm": [top[0], top[1]],
            "position_mm": [
                _MARGIN_MM,
                _MARGIN_MM + front[1] + _GAP_MM,
            ],
        },
        {
            "name": "side",
            "size_mm": [side[0], side[1]],
            "position_mm": [
                _MARGIN_MM + front[0] + _GAP_MM,
                _MARGIN_MM,
            ],
        },
    ]
    return views, pending


def build_drawing(document: dict) -> dict:
    """Build the drawing template document (or a pending one)."""
    if not isinstance(document, dict):
        raise DrawingError("document must be a JSON object")
    pending = []
    bbox = document.get("bounding_box_mm")
    if not isinstance(bbox, dict):
        raise DrawingError("bounding_box_mm must be an object")
    for key in ("length", "width", "height"):
        if not _is_number(bbox.get(key)) or bbox[key] <= 0:
            raise DrawingError(
                "bounding_box_mm.%s must be a number > 0" % key
            )
    sheet = document.get("sheet_size")
    if sheet not in SHEET_SIZES_MM:
        raise DrawingError("sheet_size must be one of A4, A3")
    factor = _parse_scale(document.get("scale"))
    title = document.get("title_block")
    if not isinstance(title, dict):
        raise DrawingError("title_block must be an object")
    title_out = {}
    for field in TITLE_BLOCK_FIELDS:
        value = title.get(field)
        if not isinstance(value, str) or not value:
            pending.append("missing_title_field:%s" % field)
        else:
            title_out[field] = value
    if title_out.get("scale") != document.get("scale"):
        pending.append("title_block_scale_mismatch")
    if title_out.get("sheet_size") != sheet:
        pending.append("title_block_sheet_mismatch")
    views, layout_pending = _layout_views(bbox, factor, sheet)
    pending.extend(layout_pending)
    dims_out = []
    dims = document.get("dimensions", [])
    if not isinstance(dims, list):
        raise DrawingError("dimensions must be a list")
    for dim in dims:
        if not isinstance(dim, dict) or not dim.get("name"):
            raise DrawingError("each dimension needs a name")
        value = dim.get("value_mm")
        source = dim.get("source")
        if not _is_number(value):
            pending.append("dimension_pending:%s" % dim["name"])
            continue
        if not isinstance(source, str) or not source:
            pending.append("dimension_pending:%s" % dim["name"])
            continue
        dims_out.append(
            {
                "name": dim["name"],
                "value_mm": value,
                "unit": "mm",
                "source": source,
            }
        )
    return {
        "drawing_version": DRAWING_VERSION,
        "part_name": document.get("part_name"),
        "sheet_size": sheet,
        "scale": document.get("scale"),
        "views": views,
        "title_block": title_out,
        "dimensions": dims_out,
        "notes": [MOCK_NOTE],
        "status": "pending" if pending else "ok",
        "pending": pending,
    }
