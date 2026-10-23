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
) -> dict:
    """Save a work copy and push resolved variables. Never overwrite ``source``."""

    source = Path(source).expanduser().resolve()
    destination = Path(destination).expanduser().resolve()
    assert_distinct_copy(source, destination)
    if destination.suffix.lower() != ".sldasm":
        raise ValueError("live SaveAs copy must use a .SLDASM work-copy path")
    if not com_available():
        raise RuntimeError("SolidWorks COM is unavailable. sw_live=not_applicable_on_linux")
    variables = assignments_from_plan(plan)
    sw_session = _import_sw_session()

    def job():
        # Import here as well so a caller who skips com_available still stays lazy.
        import pythoncom
        import win32com.client

        from solidworks_generator import _connect_task_solidworks

        sw_session.require_model_write()
        lease = sw_session.current_lease()
        app, _created = _connect_task_solidworks(lease, win32com, pythoncom)
        sw_session.require_model_write(lease)
        errors = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        warnings = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        model = app.OpenDoc6(
            str(source),
            SW_DOC_ASSEMBLY,
            SW_OPEN_SILENT | SW_OPEN_READONLY,
            "",
            errors,
            warnings,
        )
        if model is None:
            raise RuntimeError(f"OpenDoc6 failed for the work copy; errors={int(errors.value)}")
        _assign_existing_equations(model, variables)
        save_errors = model.SaveAs3(str(destination), 0, 1)
        return {
            "backend": "win32com",
            "sw_live": "attempted_on_windows",
            "save_errors": int(save_errors),
            "save_as": str(destination),
            "original_overwritten": False,
            "variables_set": sorted(variables),
        }

    return sw_session.run_on_task_sta(job, timeout=timeout, task_name="a01-saveas-copy")


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
