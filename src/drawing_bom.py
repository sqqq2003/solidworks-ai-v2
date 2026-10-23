"""Issue #6 module 5: drawing / DXF / BOM data and export interface.

Data and interfaces only, built on the existing drawing modules:

* sheet-part BOM rows reuse ``batch_export`` (``SheetPartJob``,
  ``format_sheet_part_name``);
* roller rows reuse ``roller_spec`` (``spec_from_variant``, ``variant_label``);
* thickness / material hints reuse ``drawing_notes.read_drawing_hints``;
* the a01_next drawing skeleton stays untouched.

No CAD or drawing product file is written. The mock export backend writes a
JSON trace only, mirroring ``sw_api.mock``; ``bom_csv`` is plain data.
"""

from __future__ import annotations

import csv
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

MODULE = "issue6-module5-drawing-bom"
DRAWING_SUFFIXES = {".dxf", ".dwg", ".slddrw", ".sldprt", ".sldasm"}

_SRC = Path(__file__).resolve().parent


def _load(name: str):
    if str(_SRC) not in sys.path:
        sys.path.insert(0, str(_SRC))
    return __import__(name)


@dataclass(frozen=True)
class BomItem:
    sequence: int
    name: str
    quantity: int
    thickness_mm: float | None
    size_hint: str
    material: str | None
    source: str
    drawing_ref: str | None = None

    def to_dict(self) -> dict:
        return {
            "sequence": self.sequence,
            "name": self.name,
            "quantity": self.quantity,
            "thickness_mm": self.thickness_mm,
            "size_hint": self.size_hint,
            "material": self.material,
            "source": self.source,
            "drawing_ref": self.drawing_ref,
        }


@dataclass(frozen=True)
class BomReport:
    status: str
    items: tuple[BomItem, ...]
    unresolved: tuple[dict, ...] = ()
    backend: str = "offline_python"
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "module": MODULE,
            "status": self.status,
            "backend": self.backend,
            "cad_executed": False,
            "sw_live": "not_applicable_on_linux",
            "items": [item.to_dict() for item in self.items],
            "unresolved": list(self.unresolved),
            "note": self.note,
        }


def bom_from_sheet_jobs(
    jobs: Sequence[object],
    *,
    material: str | None = None,
    drawing_ref: str | None = None,
    default_thickness_mm: float | None = None,
) -> BomReport:
    """BOM rows from ``batch_export.SheetPartJob`` discoveries.

    Thickness comes from the drawing annotation; the interface default is only
    used when explicitly supplied and is recorded as its source. Jobs without
    any thickness stay unresolved instead of silently borrowing a number.
    """

    batch_export = _load("batch_export")
    items: list[BomItem] = []
    unresolved: list[dict] = []
    for sequence, job in enumerate(jobs, start=1):
        thickness = getattr(job, "thickness_mm", None)
        quantity = int(getattr(job, "quantity", 1) or 1)
        size_hint = str(getattr(job, "size_hint", "") or "")
        if thickness is None and default_thickness_mm is not None:
            thickness = float(default_thickness_mm)
            source = "interface default (not a drawing value)"
        elif thickness is not None:
            source = str(getattr(job, "thickness_source", "") or "drawing annotation")
        else:
            source = "unresolved"
            unresolved.append(
                {
                    "label": getattr(job, "label", f"job{sequence}"),
                    "reason": "sheet thickness unresolved; no interface default supplied",
                }
            )
        if thickness is None:
            name = str(getattr(job, "label", f"件{sequence:02d}"))
        else:
            name = batch_export.format_sheet_part_name(sequence, quantity, thickness)
        items.append(
            BomItem(
                sequence=sequence,
                name=name,
                quantity=quantity,
                thickness_mm=None if thickness is None else float(thickness),
                size_hint=size_hint,
                material=material,
                source=source,
                drawing_ref=drawing_ref,
            )
        )
    status = "review_required" if unresolved else "planned"
    return BomReport(
        status=status,
        items=tuple(items),
        unresolved=tuple(unresolved),
        note="Rows from batch_export discoveries; no CAD or drawing file written.",
    )


def bom_from_variants(
    variants: Sequence[object],
    *,
    material: str | None = None,
    drawing_ref: str | None = None,
) -> BomReport:
    """BOM rows from ``roller_drawing.RollerDrawingVariant`` discoveries."""

    roller_spec = _load("roller_spec")
    items: list[BomItem] = []
    unresolved: list[dict] = []
    for sequence, variant in enumerate(variants, start=1):
        label = roller_spec.variant_label(variant)
        quantity = int(getattr(variant, "quantity", 1) or 1)
        try:
            spec = roller_spec.spec_from_variant(variant)
            thickness = float(spec.wall_thickness_mm)
            source = "roller_spec wall thickness"
        except roller_spec.RollerSpecError as exc:
            thickness = None
            source = "unresolved"
            unresolved.append({"label": label, "reason": str(exc)})
        items.append(
            BomItem(
                sequence=sequence,
                name=label,
                quantity=quantity,
                thickness_mm=thickness,
                size_hint="",
                material=material,
                source=source,
                drawing_ref=drawing_ref,
            )
        )
    status = "review_required" if unresolved else "planned"
    return BomReport(
        status=status,
        items=tuple(items),
        unresolved=tuple(unresolved),
        note="Rows from roller_spec; no CAD or drawing file written.",
    )


def bom_from_parametric_plan(plan: dict, *, drawing_ref: str | None = None) -> BomReport:
    """Mock BOM from a parametric plan when no model exists yet.

    One row per subsystem with resolved values; every unmapped OEM dimension
    stays unresolved. The envelope is reported as a placeholder, never as a
    confirmed part size.
    """

    values = plan.get("values_mm", {})
    register = plan.get("parameter_register", {})
    envelope = plan.get("target_envelope_mm", {})
    size_hint = "x".join(
        f"{envelope.get(axis):g}" for axis in ("length", "width", "height") if envelope.get(axis)
    )
    subsystems: dict[str, dict] = {}
    for name, row in register.items():
        subsystem = row.get("subsystem", "frame")
        subsystems.setdefault(subsystem, {"resolved": [], "pending": []})
        if values.get(name) is None:
            subsystems[subsystem]["pending"].append(name)
        else:
            subsystems[subsystem]["resolved"].append(name)
    items: list[BomItem] = []
    unresolved: list[dict] = []
    for sequence, subsystem in enumerate(sorted(subsystems), start=1):
        rows = subsystems[subsystem]
        thickness = values.get("sheet_thickness") if subsystem == "mount" else None
        if subsystem == "mount" and thickness is None:
            unresolved.append(
                {
                    "label": subsystem,
                    "reason": "sheet thickness is a preserved interface and stays unmapped",
                }
            )
        items.append(
            BomItem(
                sequence=sequence,
                name=f"{subsystem} (mock, no model)",
                quantity=1,
                thickness_mm=thickness,
                size_hint=size_hint,
                material=None,
                source="parametric plan placeholder; not an OEM measurement",
                drawing_ref=drawing_ref,
            )
        )
        unresolved.extend(
            {"label": subsystem, "reason": f"{name} unmapped"} for name in rows["pending"]
        )
    return BomReport(
        status="review_required",
        items=tuple(items),
        unresolved=tuple(unresolved),
        backend="mock_plan",
        note="Mock BOM for a missing model; no CAD or drawing file written.",
    )


def bom_csv_rows(report: BomReport) -> list[list]:
    """CSV rows (header first). Unknown values stay empty strings."""

    rows = [["sequence", "name", "quantity", "thickness_mm", "material", "source", "drawing_ref"]]
    for item in report.items:
        rows.append(
            [
                item.sequence,
                item.name,
                item.quantity,
                "" if item.thickness_mm is None else f"{item.thickness_mm:g}",
                item.material or "",
                item.source,
                item.drawing_ref or "",
            ]
        )
    return rows


def write_bom_csv(report: BomReport, path: str | Path) -> Path:
    """Write the BOM as a data CSV. This is not a CAD or drawing product file."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", newline="", encoding="utf-8-sig") as stream:
        csv.writer(stream).writerows(bom_csv_rows(report))
    return destination


def export_plan(
    report: BomReport,
    *,
    destination: str | Path,
    formats: Sequence[str] = ("dxf",),
    backend: str = "mock",
) -> dict:
    """Describe (mock) the drawing / DXF export for a BOM report.

    The mock backend refuses CAD / drawing product suffixes and writes a JSON
    trace. ``backend='live'`` is refused on this offline dispatch.
    """

    destination = Path(destination)
    refusals: list[str] = []
    if backend != "mock":
        refusals.append(
            f"backend {backend!r} is not available in this offline framework; "
            "sw_live=not_applicable_on_linux"
        )
    if destination.suffix.lower() in DRAWING_SUFFIXES:
        refusals.append("mock export refuses to write a CAD or drawing product file")
    if destination.exists():
        refusals.append("destination already exists; export never overwrites")
    wanted = [str(item).lower() for item in formats]
    unknown = [item for item in wanted if item not in {"dxf", "dwg", "slddrw", "csv"}]
    if unknown:
        refusals.append(f"unsupported export formats: {sorted(set(unknown))}")
    trace = {
        "module": MODULE,
        "backend": backend,
        "status": "refused" if refusals else "mock_trace",
        "refusals": refusals,
        "requested_formats": wanted,
        "dxf_written": False,
        "dwg_written": False,
        "slddrw_written": False,
        "cad_executed": False,
        "sw_live": "not_applicable_on_linux",
        "bom": report.to_dict(),
        "note": "Interface description only; no drawing product file is produced.",
    }
    if refusals:
        return trace
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(trace, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    trace["trace_file"] = str(destination)
    return trace


def drawing_hints_for_bom(path: str | Path) -> dict:
    """Thickness / material hints for a DXF, via ``drawing_notes``."""

    drawing_notes = _load("drawing_notes")
    hints = drawing_notes.read_drawing_hints(path)
    return {
        "thickness_mm": hints.thickness_mm,
        "thickness_source": hints.thickness_source,
        "material": hints.material,
        "material_source": hints.material_source,
        "wall_thickness_mm": hints.wall_thickness_mm,
        "scanned_texts": hints.scanned_texts,
        "source": "drawing_notes.read_drawing_hints",
    }
