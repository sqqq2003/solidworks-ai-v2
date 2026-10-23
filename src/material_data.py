"""Material property lookups with provenance: density and bend K-factor.

Both lookups follow the same honesty rule as the parametric specs: a value is
only usable when its row is confirmed; a measured override must carry
provenance; and a missing row stays unresolved instead of borrowing a
default. The shipped K-factor table has no confirmed rows because K depends
on the shop's press brake and tooling, not on generic material physics.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

MODULE = "issue6-material-data"

_SRC = Path(__file__).resolve().parent
ROOT = _SRC.parent
MATERIAL_TABLE_PATH = ROOT / "data" / "material_properties.json"
K_FACTOR_TABLE_PATH = ROOT / "data" / "k_factor_table.json"

# Physical sanity range for a bend K-factor (neutral-axis position / thickness).
K_MIN, K_MAX = 0.0, 0.5


class MaterialDataError(ValueError):
    """Raised when a table or a lookup row is structurally invalid."""


def _load_table(path: Path, expected_version: int = 1) -> dict:
    try:
        table = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise MaterialDataError(f"table not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise MaterialDataError(f"table is not valid JSON: {path}: {exc}") from exc
    if table.get("table_version") != expected_version:
        raise MaterialDataError(f"unsupported table_version in {path}")
    return table


def _validate_row(row: dict, path: Path) -> None:
    for field in ("material", "confirmed", "source"):
        if field not in row:
            raise MaterialDataError(f"row in {path} missing field: {field}")
    if row.get("confirmed") is not True and not row.get("source"):
        raise MaterialDataError(f"row in {path} has no source: {row}")


def density_for(material: str, *, path: Path | None = None) -> dict:
    """Return the confirmed density row for ``material`` or an unresolved row."""
    table_path = Path(path) if path is not None else MATERIAL_TABLE_PATH
    table = _load_table(table_path)
    rows = [row for row in table.get("densities", []) if row.get("material") == material]
    if not rows:
        return {
            "material": material,
            "status": "unresolved",
            "reason": "material is not in the density table; no default density is assumed",
        }
    row = rows[0]
    _validate_row(row, table_path)
    density = row.get("density_g_per_cm3")
    if row.get("confirmed") is not True or not isinstance(density, (int, float)) or not math.isfinite(density) or density <= 0:
        return {
            "material": material,
            "status": "unresolved",
            "reason": "row is not a confirmed usable density",
            "source": row.get("source"),
        }
    return {
        "material": material,
        "status": "resolved",
        "density_g_per_cm3": float(density),
        "confirmed": True,
        "source": row.get("source"),
        "provenance": row.get("provenance"),
    }


def k_factor_for(material: str, thickness_mm: float, *, path: Path | None = None) -> dict:
    """Return the confirmed K-factor row or an unresolved row; never a default K."""
    table_path = Path(path) if path is not None else K_FACTOR_TABLE_PATH
    table = _load_table(table_path)
    thickness = float(thickness_mm)
    if not math.isfinite(thickness) or thickness <= 0:
        raise MaterialDataError("thickness_mm must be finite and positive")
    rows = [
        row
        for row in table.get("k_factors", [])
        if row.get("material") == material and float(row.get("thickness_mm", -1)) == thickness
    ]
    if not rows:
        return {
            "material": material,
            "thickness_mm": thickness,
            "status": "unresolved",
            "reason": "no K-factor row for this material/thickness; K is process-dependent and is not defaulted",
        }
    row = rows[0]
    _validate_row(row, table_path)
    k = row.get("k_factor")
    usable = (
        row.get("confirmed") is True
        and isinstance(k, (int, float))
        and math.isfinite(k)
        and K_MIN < k < K_MAX
    )
    if not usable:
        return {
            "material": material,
            "thickness_mm": thickness,
            "status": "unresolved",
            "reason": "row is not a confirmed usable K-factor",
            "source": row.get("source"),
        }
    return {
        "material": material,
        "thickness_mm": thickness,
        "status": "resolved",
        "k_factor": float(k),
        "confirmed": True,
        "source": row.get("source"),
        "provenance": row.get("provenance"),
    }
