"""Apply a dimension plan through the mock adapter.

The Windows COM backend is a separate module and is not imported here.
"""

from __future__ import annotations

from pathlib import Path

from . import assignments_from_plan
from .mock import MockAssemblyAdapter

UNMAPPED_TEMPLATE = "simulated://A01/unmapped-template"


def dry_run_apply(
    plan: dict,
    destination: Path,
    *,
    source: str | Path | None = None,
    adapter: MockAssemblyAdapter | None = None,
) -> dict:
    adapter = adapter or MockAssemblyAdapter()
    source_label = str(source) if source is not None else UNMAPPED_TEMPLATE
    opened = adapter.open_assembly(source_label)
    variables = assignments_from_plan(plan)
    adapter.set_equations(variables)
    rebuild = adapter.rebuild()
    written = adapter.save_as_copy(
        source_label,
        Path(destination),
        {
            "plan_status": plan["status"],
            "variables_set": variables,
            "variables_skipped_unresolved": [
                name for name, value in plan["values_mm"].items() if value is None
            ],
            "pending_mapping": [row["mapping_id"] for row in plan["pending_mapping"]],
        },
    )
    return {
        "backend": "mock",
        "sw_live": "not_applicable_on_linux",
        "cad_executed": False,
        "original_overwritten": False,
        "opened": opened,
        "source": source_label,
        "save_as": str(written),
        "rebuild": rebuild,
        "variables_set": sorted(variables),
        "variables_skipped_unresolved": [
            name for name, value in plan["values_mm"].items() if value is None
        ],
    }
