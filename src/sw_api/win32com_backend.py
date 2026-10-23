"""Windows SolidWorks adapter. COM is imported only inside a live call.

Cloud and Linux dry-runs must use ``sw_api.apply.dry_run_apply``. This module
does not attach to SolidWorks at import time. A live call refuses to run
unless ``sw_session.require_model_write`` can prove an exclusive task session,
and it SaveAs-es a different path. It does not shut down SolidWorks, close
every open document, or kill a process.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from . import assert_distinct_copy, assignments_from_plan

SW_DOC_ASSEMBLY = 2
SW_OPEN_SILENT = 1
SW_OPEN_READONLY = 2


def com_available() -> bool:
    # Test hook: let a subprocess deterministically exercise the "no COM"
    # refusal path even on a machine that has pywin32 installed. Without this,
    # the CLI's --live refusal behavior depends on the host environment.
    if os.environ.get("SW_API_FORCE_NO_COM") == "1":
        return False
    try:
        import pythoncom  # noqa: F401
        import win32com.client  # noqa: F401
    except ImportError:
        return False
    return True


def _import_sw_session():
    src = Path(__file__).resolve().parents[1]
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    import sw_session

    return sw_session


def apply_live(
    plan: dict,
    source: Path,
    destination: Path,
    *,
    timeout: float = 120.0,
    mapping_payload: dict | None = None,
    driver=None,
) -> dict:
    """Save a work copy and push resolved variables. Never overwrite ``source``."""

    source = Path(source).expanduser().resolve()
    destination = Path(destination).expanduser().resolve()
    assert_distinct_copy(source, destination)
    if destination.suffix.lower() != ".sldasm":
        raise ValueError("live SaveAs copy must use a .SLDASM work-copy path")
    if not com_available():
        raise RuntimeError("SolidWorks COM is unavailable. sw_live=not_applicable_on_linux")
    if mapping_payload is None or driver is None:
        raise RuntimeError("Live writes require confirmed mappings and a Windows transaction driver; legacy equation-only writes are disabled")
    from .transaction import execute
    from .windows_execution import WindowsExecutionPort
    sw_session = _import_sw_session()

    def transaction_job():
        return execute(plan, mapping_payload, WindowsExecutionPort(driver), str(destination))

    return sw_session.run_on_task_sta(transaction_job, timeout=timeout, task_name="a01-transaction-copy")


# Windows transaction drivers must check OpenDoc6 and SaveAs3 error codes.


def _mm_literal(value: float) -> str:
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        raise ValueError("equation value must be finite")
    if number.is_integer():
        return str(int(number))
    return format(number, ".17g")


def _replace_equation_at_index(manager, index: int, equation: str) -> None:
    """Rewrite one equation with Delete(index) then Add2 at that same index.

    On SolidWorks Premium 2025 SP1.2 / Rev 33.1.2, PROPERTYPUT of
    ``EquationMgr.Equation(index, text)`` does not change the stored equation.
    The write that read back on the operator work copy is ``Delete(index)``
    then ``Add2(index, equation, False)``.

    After Delete, ``Add(-1)`` or ``Add3(-1)`` returns -1 and drops the name
    while other equations still reference it. Do not append.

    A failed rewrite leaves that document dirty. Closing it without saving
    restores the on-disk file. This helper is not the operator script
    ``apply_variant.py``; that PC-only ``_equation_put`` patch is not in this
    repository, and ``apply_live`` does not call this function.
    """

    count = int(manager.GetCount())
    original = str(manager.Equation(index))
    if not manager.Delete(index):
        raise RuntimeError("Delete failed; refusing Add2")
    added = int(manager.Add2(index, equation, False))
    if added != index or int(manager.GetCount()) != count:
        raise RuntimeError(
            "Add2 returned -1 at index "
            + str(index)
            + ". The name may be gone while dependents still reference it. "
            + "Discard the unsaved document so the on-disk file stays unchanged."
        )

    if str(manager.Equation(index)).replace(" ", "") != equation.replace(" ", ""):
        raise RuntimeError("equation text readback mismatch; discard unsaved work copy")


def _assign_existing_equations(model, variables: dict[str, float]) -> None:
    """Rewrite existing numeric globals. Do not create new OEM equations.

    Unused by ``apply_live``. Numeric text matches the GT-ZX global form
    ``"Name"= <number>mm`` from the read-only dump. Formula equations such as
    DeckHeight are left alone; their ``Value()`` readback is not a solved dimension.
    """

    manager = model.GetEquationMgr()
    count = int(manager.GetCount())
    index_by_name: dict[str, int] = {}
    for index in range(count):
        text = str(manager.Equation(index))
        if text.startswith('"'):
            name = text.split('"', 2)[1]
            index_by_name[name] = index
    missing = [name for name in variables if name not in index_by_name]
    if missing:
        raise RuntimeError(
            "work copy has no equation for: " + ", ".join(missing)
            + ". Refusing to invent global variables."
        )
    # Validate all updates before the first destructive Delete.
    import re
    literals = {}
    for name, value in variables.items():
        if isinstance(value, bool):
            raise ValueError("boolean is not a dimension")
        literal = _mm_literal(value)
        existing = str(manager.Equation(index_by_name[name]))
        if "@" in name or not re.fullmatch(r'\s*"[^"]+"\s*=\s*[-+]?\d+(?:\.\d*)?\s*mm\s*', existing):
            raise ValueError("only existing numeric mm globals may be updated")
        literals[name] = literal
    # Each Delete+Add2 pair puts the row back, so later indexes stay valid.
    for name in sorted(variables, key=lambda item: index_by_name[item]):
        index = index_by_name[name]
        _replace_equation_at_index(manager, index, f'"{name}"= {literals[name]}mm')

