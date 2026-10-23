"""Abstract assembly port and path guards shared by mock and Windows backends."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class AssemblyPort(Protocol):
    def open_assembly(self, path: str) -> str: ...

    def set_equations(self, variables: dict[str, float]) -> None: ...

    def rebuild(self) -> dict: ...

    def save_as_copy(self, source: str, destination: Path, trace: dict) -> Path: ...


def assert_distinct_copy(source: str | Path, destination: str | Path) -> None:
    if Path(str(source)).expanduser().resolve() == Path(str(destination)).expanduser().resolve():
        raise ValueError("refusing to overwrite the original SolidWorks project; SaveAs a work copy")


def assignments_from_plan(plan: dict) -> dict[str, float]:
    assigned: dict[str, float] = {}
    for name, value in plan["values_mm"].items():
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{name}: equation value must be a number")
        assigned[name] = float(value)
    return assigned
