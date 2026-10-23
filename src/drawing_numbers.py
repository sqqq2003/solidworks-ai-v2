"""Drawing-number allocation with a persistent journal.

BOM sequence numbers are per-assembly; drawing numbers are per-part and must
never be silently reused once issued (the same rule as closed review-session
titles). Allocation is monotonic, journaled to a JSON file, and idempotent for
the same part name. A number issued to a different part is refused, not
overwritten.
"""
from __future__ import annotations

import dataclasses
import json
from datetime import datetime, timezone
from pathlib import Path

MODULE = "issue6-drawing-numbers"

JOURNAL_VERSION = 1


class DrawingNumberError(ValueError):
    """Raised when allocation would reuse or collide with an issued number."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_journal(path: Path) -> dict:
    path = Path(path)
    if not path.exists():
        return {"journal_version": JOURNAL_VERSION, "issued": {}, "max_seq": 0}
    try:
        journal = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DrawingNumberError(f"drawing-number journal is not valid JSON: {path}: {exc}") from exc
    if journal.get("journal_version") != JOURNAL_VERSION:
        raise DrawingNumberError(f"unsupported journal_version in {path}")
    journal.setdefault("issued", {})
    journal.setdefault("max_seq", 0)
    return journal


def save_journal(path: Path, journal: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(journal, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _format(scheme: str, seq: int) -> str:
    try:
        return scheme.format(seq=seq)
    except (KeyError, IndexError, ValueError) as exc:
        raise DrawingNumberError(f"invalid drawing-number scheme: {scheme!r} ({exc})") from exc


def allocate_drawing_numbers(
    part_names: list[str],
    *,
    scheme: str = "QL-5050PX-{seq:03d}",
    journal_path: Path,
) -> dict:
    """Allocate one drawing number per part name; persist the journal.

    Idempotent per part: a part that already holds a number gets the same one
    back with status "existing". A new part gets the next monotonic number.
    Any collision with a number issued to a different part is refused.
    """
    journal = load_journal(journal_path)
    issued: dict[str, dict] = journal["issued"]
    by_part: dict[str, str] = {}
    for number, row in issued.items():
        by_part.setdefault(row["part"], number)

    allocations: list[dict] = []
    changed = False
    for part in part_names:
        if not part:
            raise DrawingNumberError("part name must not be empty")
        existing = by_part.get(part)
        if existing is not None:
            allocations.append(
                {"part": part, "sequence": issued[existing].get("sequence"), "drawing_number": existing, "status": "existing"}
            )
            continue
        seq = int(journal["max_seq"]) + 1
        number = _format(scheme, seq)
        if number in issued and issued[number]["part"] != part:
            raise DrawingNumberError(
                f"drawing number {number} is already issued to {issued[number]['part']}; refusing to reuse it for {part}"
            )
        issued[number] = {"part": part, "sequence": seq, "assigned": _now()}
        by_part[part] = number
        journal["max_seq"] = seq
        changed = True
        allocations.append({"part": part, "sequence": seq, "drawing_number": number, "status": "allocated"})

    if changed:
        save_journal(journal_path, journal)
    return {
        "module": MODULE,
        "scheme": scheme,
        "journal": str(journal_path),
        "allocations": allocations,
        "max_seq": journal["max_seq"],
        "sw_live": "not_applicable_on_linux",
    }


def attach_drawing_refs(report, allocations: list[dict]) -> "object":
    """Return a copy of a BomReport with drawing_ref filled from allocations."""
    from src.drawing_bom import BomReport  # local import avoids a cycle at module load

    mapping = {row["part"]: row["drawing_number"] for row in allocations}
    items = []
    for item in report.items:
        ref = mapping.get(item.name) or item.drawing_ref
        items.append(dataclasses.replace(item, drawing_ref=ref))
    return dataclasses.replace(report, items=tuple(items))
