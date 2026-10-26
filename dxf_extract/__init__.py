"""DXF geometry / dimension-relation extraction and feature planning.

Issue #25 expansion module 3 (offline, Linux-safe, standard library only).

This package is intentionally independent of the SolidWorks pipeline:
it never touches SolidWorks, never writes customer CAD, and never
invents a dimension. Anything it cannot read exactly is flagged
``pending`` / ``pending_confirmation`` instead of guessed.

Public entry points:

* :func:`dxf_extract.dxf_parser.extract_dxf` — DXF file -> GeometryDoc.
* :func:`dxf_extract.planner.plan_features` — GeometryDoc -> feature plan.
* :func:`dxf_extract.cli.main` — CLI: DXF file -> geometry.json + plan.json.

Units: all geometry values in the JSON output are millimetres when the
source file declares a known unit ($INSUNITS). When the source unit is
unknown, values are left as-is, ``units`` is ``"unknown"`` and a
``pending_confirmation`` flag is raised — sizes are never silently
asserted in mm.
"""

from dxf_extract.dxf_parser import DxfError, extract_dxf
from dxf_extract.planner import plan_features

__version__ = "1.0.0"
__all__ = ["DxfError", "extract_dxf", "plan_features", "__version__"]
