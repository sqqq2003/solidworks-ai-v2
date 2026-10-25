"""Drawing generation, cloud-side part (phase 1, F1).

This module builds a drawing *template document*: sheet size, scale,
three-view layout positions, title-block fields and dimension
rules, plus a mock render (drawing JSON). It deliberately does NOT
generate a real SolidWorks drawing: that step needs the Windows
SolidWorks session and belongs to Gork. Any consumer that presents
this output as a finished drawing is misrepresenting it; the output
itself carries a mock disclaimer and a pending_windows_validation
note on every page of its README.

Layout rules (explicit, never auto-adjusted):

* sheet sizes are explicit (A4 297x210, A3 420x297, landscape, mm);
* scale is explicit ("1:2", "1:1", "2:1", ...); a layout that does
  not fit is pending, never silently re-scaled;
* margin is 20 mm on every side; front view sits bottom-left,
  top view above it, side view to its right, 10 mm gaps;
* every title-block field and every dimension value must be
  supplied explicitly. Missing values are pending with a listed
  reason, never invented from the part name or the bounding box.
"""

from .drawing import (
    DRAWING_VERSION,
    TITLE_BLOCK_FIELDS,
    DrawingError,
    build_drawing,
)

__all__ = [
    "DRAWING_VERSION",
    "TITLE_BLOCK_FIELDS",
    "DrawingError",
    "build_drawing",
]
