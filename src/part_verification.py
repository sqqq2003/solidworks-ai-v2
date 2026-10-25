"""Reopen a newly generated owned part and verify native solid geometry."""
import math
from pathlib import Path

from sw_session import ComSessionDisconnected, is_com_server_disconnect


class PostSaveComDisconnect(ComSessionDisconnected):
    """Save returned, then the COM server or document pointer was gone.

    A file on disk is not a modeling pass. ExitApp and process kill are not
    recovery. Native acceptance stays pending until a Windows reopen.
    """

    status = "post_save_com_disconnected"


def mark_session_disconnected(lease) -> None:
    if lease is None:
        return
    lease.disconnected = True
    lease.writes_blocked = True
    lease.verified_exclusive = False


def disconnect_after_saved_product(error, product) -> bool:
    """True when a later COM drop must not erase a part already on disk."""
    path = Path(product) if product is not None else None
    try:
        ready = path is not None and path.is_file() and path.stat().st_size > 0
    except OSError:
        ready = False
    if not ready:
        return False
    if isinstance(error, ComSessionDisconnected) or is_com_server_disconnect(error):
        return True
    from sw_session import SessionOwnershipError
    if not isinstance(error, SessionOwnershipError):
        return False
    text = str(error)
    folded = text.casefold()
    return (
        "disconnected" in folded
        or "没有连接到服务器" in text
        or "not connected to server" in folded
        or "writes refused" in folded
    )


def saved_generation_after_disconnect(generation, error):
    """Keep a finished save visible. This is not a SolidWorks live pass."""
    return {
        "status": "partial_com_disconnect",
        "warning": (
            "owned COM server disconnected after the part was saved; "
            "ExitApp was not called"
        ),
        "modeling": "saved_pending_reopen",
        "native_acceptance": "pending_windows_validation",
        "sw_live_verified": False,
        "passed": False,
        "file_on_disk": True,
        "exit_app": False,
        "process_killed": False,
        "generation": generation,
        "post_save_disconnect": str(error),
        "error_kind": type(error).__name__,
        "recovery": "products_kept",
    }


def post_save_status(*, saved, disconnected, exit_app=False, killed=False):
    """Offline contract for the shaft r2 failure. Never reports a native pass."""
    if exit_app or killed:
        raise AssertionError("ExitApp and process kill are forbidden after generation")
    if disconnected:
        return {
            "modeling": "failed",
            "status": PostSaveComDisconnect.status,
            "native_acceptance": "pending_windows_validation",
            "passed": False,
            "file_on_disk": bool(saved),
            "exit_app": False,
            "process_killed": False,
        }
    return {
        "modeling": "saved_pending_reopen",
        "status": "saved_pending_reopen",
        "native_acceptance": "pending_windows_validation",
        "passed": False,
        "file_on_disk": bool(saved),
        "exit_app": False,
        "process_killed": False,
    }


def rebind_model_after_save(app, fetch_active, read_title, *, lease=None):
    """Drop the pre-save model pointer and resolve the document that is open now."""
    try:
        model = fetch_active(app)
        if model is None:
            raise PostSaveComDisconnect(
                "post-save rebind found no ActiveDoc; the save is not a live-session pass"
            )
        title = read_title(model)
    except PostSaveComDisconnect:
        mark_session_disconnected(lease)
        raise
    except Exception as error:
        if is_com_server_disconnect(error):
            mark_session_disconnected(lease)
            raise PostSaveComDisconnect(
                "post-save COM disconnect while rebinding the open document: " + str(error)
            ) from error
        raise
    if not title:
        mark_session_disconnected(lease)
        raise PostSaveComDisconnect(
            "rebound document has an empty title; refusing to treat the save as success"
        )
    return model, str(title)


def assert_native_save(path, error_code):
    path = Path(path)
    if type(error_code) is not int or int(error_code) != 0:
        raise RuntimeError(f'native save error: {error_code}')
    if not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError('native save produced a missing or empty file')


def solid_inventory(part, sw, module):
    """Measure the union of every solid, retaining body-by-body evidence."""
    bodies = part.GetBodies2(sw.SW_BODY_TYPE_SOLID, False)
    if not bodies:
        raise RuntimeError('reopened part has no solid bodies')
    boxes = []
    for raw in bodies:
        body = sw._as_interface(module, raw, 'IBody2')
        faces = body.GetFaces()
        if not faces:
            raise RuntimeError('solid body has no measurable faces')
        face_boxes = [sw._as_interface(module,f,'IFace2').GetBox() for f in faces]
        if any(b is None or len(b)!=6 or not all(math.isfinite(v) for v in b) for b in face_boxes):
            raise RuntimeError('invalid native body bounds')
        box = [min(b[i] for b in face_boxes) for i in range(3)]+[max(b[i] for b in face_boxes) for i in range(3,6)]
        if any(box[i+3]<=box[i] for i in range(3)):
            raise RuntimeError('degenerate solid body')
        boxes.append([v*1000 for v in box])
    union = [min(b[i] for b in boxes) for i in range(3)]+[max(b[i] for b in boxes) for i in range(3,6)]
    return union,boxes


def verify_saved_part(path, *, expected_dims_mm=None, expected_body_count=None):
    from sw_session import require_model_write, close_owned_document
    import solidworks_generator as sw
    import pythoncom
    import win32com.client
    try:
        lease = require_model_write()
    except ComSessionDisconnected as error:
        raise PostSaveComDisconnect(
            "post-save reopen refused because the owned COM session is disconnected; not a pass: "
            + str(error)
        ) from error
    path = Path(path).resolve()
    if not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError('generated part is missing or empty')
    apartment_owned = bool(getattr(lease, "com_initialized", False))
    if not apartment_owned:
        pythoncom.CoInitialize()
    app = None
    title = None
    try:
        try:
            raw, _ = sw._connect_task_solidworks(lease, win32com, pythoncom)
            sw._com_read(raw, "GetProcessID")
        except ComSessionDisconnected as error:
            raise PostSaveComDisconnect(
                "post-save application pointer did not rebind; not a pass: " + str(error)
            ) from error
        except Exception as error:
            if is_com_server_disconnect(error):
                mark_session_disconnected(lease)
                raise PostSaveComDisconnect(
                    "post-save COM disconnect before reopen; not a pass: " + str(error)
                ) from error
            raise
        module = sw.ensure_solidworks_typelib()
        app = sw._as_interface(module, raw, 'ISldWorks')
        lease.note_bound_application(app)
        if path.name in lease.owned_docs:
            close_owned_document(lease, app, path.name)
        require_model_write(lease)
        opened = app.OpenDoc6(str(path), 1, 1, '', 0, 0)
        native_errors = opened[1] if isinstance(opened, tuple) and len(opened) > 1 else 0
        model = opened[0] if isinstance(opened, tuple) else opened
        if model is None or native_errors:
            raise RuntimeError(f'OpenDoc6 failed: errors={native_errors}')
        model = sw._as_interface(module, model, 'IModelDoc2')
        title = str(sw._com_read(model, 'GetTitle'))
        if Path(str(sw._com_read(model, 'GetPathName'))).resolve() != path:
            raise RuntimeError('reopened document path differs from generated artifact')
        lease.note_owned_document(title, handle_id=id(model))
        require_model_write(lease)
        if not sw._com_read(model, 'EditRebuild3'):
            raise RuntimeError('reopened part rebuild failed')
        part = sw._as_interface(module, model, 'IPartDoc')
        bounds,body_boxes = solid_inventory(part,sw,module)
        dims = [bounds[i+3]-bounds[i] for i in range(3)]
        if not all(math.isfinite(v) and v > 0 for v in dims):
            raise RuntimeError('invalid reopened solid bounding dimensions')
        if expected_dims_mm is not None:
            if len(expected_dims_mm) != 3 or not all(type(v) in (int,float) and math.isfinite(v) and v>0 for v in expected_dims_mm) or any(not math.isclose(a,b,rel_tol=1e-4,abs_tol=.05)
                    for a,b in zip(sorted(dims),sorted(expected_dims_mm))):
                raise RuntimeError('reopened solid dimensions differ from plan')
        if expected_body_count is not None:
            if type(expected_body_count) is not int or expected_body_count<1 or len(body_boxes)!=expected_body_count:
                raise RuntimeError('reopened solid body count differs from plan')
        # Bounds, even with body counts, cannot establish holes, bends or shape.
        status = 'reopen_dimensions_verified' if expected_dims_mm is not None else 'reopened_rebuilt'
        return {'status':status,'rebuilt':True,'reopened':True,
                'verification_scope':'solid_inventory_and_optional_envelope_only',
                'body_count':len(body_boxes),'body_bounds_mm':body_boxes,
                'expected_body_count':expected_body_count,'geometry_verified':False,
                'bounds_mm':bounds,'dimensions_mm':dims,
                'feature_types':[str(sw._com_read(f,'GetTypeName2')) for f in sw._features(model,module)],
                'mechanical_acceptance':'unverified','threads':'not_certified'}
    finally:
        try:
            if title and app is not None and title in lease.owned_docs:
                close_owned_document(lease,app,title)
        finally:
            if not apartment_owned:
                pythoncom.CoUninitialize()

