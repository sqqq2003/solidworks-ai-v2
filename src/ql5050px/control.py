"""Controlled execution facade reusing the repository's transaction/session layer."""
import sys
from pathlib import Path


def execute_variant(plan, mapping_payload, destination, *, driver=None, mock_port=None, timeout=120):
    """Execute a confirmed variant; ``pending_mapping`` mirrors the plan's
    unresolved set, so the target envelope is never reported as an OEM map."""
    from sw_api.mapping import load_mappings
    from sw_api.transaction import execute
    if plan.get("machine") != "QL-5050PX" or plan.get("units") != "mm":
        raise ValueError("QL-5050PX mm contract required")
    rows = load_mappings(mapping_payload)
    writable = [r for r in rows if r.status == "confirmed" and r.component_kind == "editable"]
    if not writable:
        return {"status": "pending_mapping", "cad_executed": False, "pending_mapping": plan["pending_mapping"]}
    for row in writable:
        if row.unit != "mm":
            raise ValueError("v1 native execution supports length mappings in mm only")
        if plan["values_mm"].get(row.parameter) is None:
            raise ValueError(f"unresolved target: {row.parameter}")
    if mock_port is not None:
        if mock_port.simulated is not True:
            raise ValueError("mock_port must declare simulated=True")
        result = execute(plan, mapping_payload, mock_port, str(destination))
    elif sys.platform != "win32":
        raise RuntimeError("Windows SolidWorks worker required")
    elif driver is None:
        raise ValueError("owned, isolated Windows transaction driver required")
    else:
        # Source/document/reference isolation is validated by driver.preflight.
        from sw_api.windows_execution import WindowsExecutionPort
        from sw_api.win32com_backend import _import_sw_session
        result = _import_sw_session().run_on_task_sta(
            lambda: execute(plan, mapping_payload, WindowsExecutionPort(driver), str(destination)),
            timeout=timeout, task_name="ql5050px-variant")
    result["pending_mapping"] = list(plan["pending_mapping"])
    return result


def export_native(port, model, destination, kind):
    """Export through an owned execution port; no foreign COM attachment."""
    if kind not in {"drawing", "flat_dxf"}:
        raise ValueError("unsupported native export kind")
    suffix = {"drawing": ".slddrw", "flat_dxf": ".dxf"}[kind]
    destination = Path(destination).resolve()
    if destination.suffix.lower() != suffix or destination.exists():
        raise ValueError("new output path with correct extension required")
    with port.writer():
        return port.guarded("export_" + kind, model, str(destination))
