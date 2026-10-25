"""Bill of materials, one-click from an assembly (phase 1, F3).

Built on the dependency_engine vocabulary: parts carry ids, and the
assembly order is the topological order of each part's ``depends_on``
edges (same direction as dependency_engine's depends_on edges). An
optional dependency_engine precheck report can be cross-checked by
part id: BOM ids absent from the report are pending notes, never
dropped, and an assembly-name mismatch is a pending note, never
an error -- the report may describe a subsystem.

Weight discipline: a row's mass is only computed when the caller
supplies ``mass_kg`` for that part. Missing masses are pending and
the total mass stays unknown; no density, no catalogue mass, no
guess is ever substituted. Quantities are explicit integers.
"""

from .bom import (
    BOM_VERSION,
    BomError,
    build_bom,
    render_csv,
    render_table,
)

__all__ = [
    "BOM_VERSION",
    "BomError",
    "build_bom",
    "render_csv",
    "render_table",
]
