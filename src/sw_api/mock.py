"""Dry-run SolidWorks adapter. Writes a JSON trace, never a CAD file."""

from __future__ import annotations

import json
from pathlib import Path

from . import assert_distinct_copy


class MockAssemblyAdapter:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def open_assembly(self, path: str) -> str:
        self.calls.append(("open_assembly", path))
        return f"mock:{Path(path).name}"

    def set_equations(self, variables: dict[str, float]) -> None:
        for name, value in variables.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{name}: mock equation value must be numeric")
        self.calls.append(("set_equations", dict(variables)))

    def rebuild(self) -> dict:
        report = {
            "rebuilt": True,
            "backend": "mock",
            "sw_live": "not_applicable_on_linux",
            "cad_executed": False,
        }
        self.calls.append(("rebuild",))
        return report

    def save_as_copy(self, source: str, destination: Path, trace: dict) -> Path:
        destination = Path(destination)
        assert_distinct_copy(source, destination)
        if destination.suffix.lower() in {".sldprt", ".sldasm", ".slddrw", ".dwg", ".dxf"}:
            raise ValueError("mock dry-run refuses to write a CAD or drawing product file")
        destination.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "backend": "mock",
            "sw_live": "not_applicable_on_linux",
            "source": source,
            "intended_save_as": str(destination),
            "original_overwritten": False,
            "trace": trace,
        }
        destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self.calls.append(("save_as_copy", source, str(destination)))
        return destination
