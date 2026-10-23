"""Windows SolidWorks adapter. COM is imported only inside a live call.

Cloud and Linux dry-runs must use ``sw_api.apply.dry_run_apply``. This module
does not attach to SolidWorks at import time. A live call refuses to run
unless ``sw_session.require_model_write`` can prove an exclusive task session,
and it SaveAs-es a different path. It does not shut down SolidWorks, close
every open document, or kill a process.
"""

from __future__ import annotations

import sys
from pathlib import Path

from . import assert_distinct_copy, assignments_from_plan

SW_DOC_ASSEMBLY = 2
SW_OPEN_SILENT = 1
SW_OPEN_READONLY = 2


def com_available() -> bool:
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


def _assign_existing_equations(model, variables: dict[str, float]) -> None:
    """Update equations that already exist. Do not create new OEM equations."""

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
    for name, value in variables.items():
        manager.Equation(index_by_name[name], f'"{name}"={value}')

