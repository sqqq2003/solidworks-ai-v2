"""Flat-pattern DXF for laser cutting (phase 1, F2).

Input is a feature_tree unfold report (status ok) plus one explicit
per-job bend record per bend. Output is a minimal ASCII DXF (R12)
with three layers: CUT (flat outline), BEND (bend lines across the
blank width), NOTES (direction / angle / sequence labels). The DXF
is plain text and directly usable by laser-cutting CAM; the bend
sequence card is emitted alongside as JSON.

Per-job discipline (iron rule): thickness, inner radius, angle,
K-factor, die V-opening and process are required inputs for every
bend. Anything missing or out of range makes the whole job pending
with a listed reason -- never a substituted number. The unfold
length from the report is only a derived cross-check: the DXF strip
is laid out from the report's straight lengths and the recomputed
bend allowances, and the two totals must agree to 1e-9; a mismatch
is pending, never silently resolved in favour of either side.

This module never talks to SolidWorks and never claims the DXF was
cut or folded on a real machine. Real cutting / folding behaviour
is pending_windows_validation.
"""

from .dxf import (
    DXF_VERSION,
    REQUIRED_BEND_KEYS,
    FlatDxfError,
    build_flat_dxf,
)

__all__ = [
    "DXF_VERSION",
    "REQUIRED_BEND_KEYS",
    "FlatDxfError",
    "build_flat_dxf",
]
