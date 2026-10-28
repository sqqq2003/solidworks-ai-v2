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


SAVED_DISCONNECT_STATUS = "saved_com_disconnected_after_generation"
PARTIAL_COM_DISCONNECT_STATUS = "partial_com_disconnect"
PARTIAL_REBIND_STATUS = "partial_rebind_failed"
KEPT_AFTER_SAVE_STATUSES = frozenset(
    {
        SAVED_DISCONNECT_STATUS,
        PARTIAL_COM_DISCONNECT_STATUS,
        PARTIAL_REBIND_STATUS,
    }
)
# 0x80020003. Calling an ISldWorks propget as a method raises this.
DISP_E_MEMBERNOTFOUND = -2147352573


def product_file_ready(product) -> bool:
    """True when a saved part is still on disk.

    SolidWorks can hold the file so ``stat`` raises ``PermissionError`` after
    SaveAs. That lock is not "no product". A missing path stays false.
    """
    if product is None:
        return False
    path = Path(product)
    try:
        info = path.stat()
    except FileNotFoundError:
        return False
    except OSError:
        # SaveAs can leave the file locked so stat fails. The lease flag is
        # set only after that save (or the S1 checkpoint) succeeded.
        from sw_session import current_lease
        lease = current_lease()
        if bool(getattr(lease, "generation_saved", False)):
            return True
        try:
            return path.exists()
        except OSError:
            return False
    return info.st_size > 0


def disconnect_after_saved_product(error, product) -> bool:
    """True when a later COM drop must not erase a part already on disk."""
    if not product_file_ready(product):
        return False
    from sw_session import SessionOwnershipError, normalize_com_disconnect
    if normalize_com_disconnect(error) is not None:
        return True
    if not isinstance(error, SessionOwnershipError):
        return False
    text = str(error)
    folded = text.casefold()
    return (
        "disconnected" in folded
        or "没有连接到服务器" in text
        or "not connected to server" in folded
        or "writes refused" in folded
        or "-2147220995" in text
    )


def is_member_not_found(error) -> bool:
    """True for DISP_E_MEMBERNOTFOUND, including a wrapped SolidWorksGenerationError."""
    if error is None:
        return False
    unsigned = DISP_E_MEMBERNOTFOUND & 0xFFFFFFFF
    seen: set[int] = set()

    def walk(value) -> bool:
        if value is None or isinstance(value, bool):
            return False
        if isinstance(value, int):
            return value == DISP_E_MEMBERNOTFOUND or (value & 0xFFFFFFFF) == unsigned
        if isinstance(value, str):
            folded = value.casefold()
            return (
                "找不到成员" in value
                or "membernotfound" in folded
                or "-2147352573" in value
            )
        ident = id(value)
        if ident in seen:
            return False
        seen.add(ident)
        if isinstance(value, BaseException):
            if walk(getattr(value, "args", ())):
                return True
            if walk(str(value)):
                return True
            return walk(value.__cause__) or walk(value.__context__)
        if isinstance(value, (tuple, list)):
            return any(walk(item) for item in value)
        return False

    return walk(error)


def read_com_property(instance, name: str):
    """Read a COM propget.

    A Python property or a non-callable attribute is returned as-is. A callable
    is invoked only for dynamic Dispatch. ``DISP_E_MEMBERNOTFOUND`` means this
    object is an early-bound wrapper and the call was the wrong invoke kind.
    """
    descriptor = getattr(type(instance), name, None)
    if isinstance(descriptor, property):
        return descriptor.fget(instance)
    value = getattr(instance, name)
    if not callable(value):
        return value
    try:
        return value()
    except Exception as error:
        if is_member_not_found(error):
            raise
        raise


def read_active_document(app):
    """Read ``ISldWorks.ActiveDoc`` without calling a wrapped propget.

    Early-bound wrappers expose ``ActiveDoc`` as a callable. Invoking it is
    ``DISP_E_MEMBERNOTFOUND``. Path reopen is the fallback; this function does
    not make that call.
    """
    descriptor = getattr(type(app), "ActiveDoc", None)
    if isinstance(descriptor, property):
        got = descriptor.fget(app)
        if callable(got):
            return None
        return got
    value = getattr(app, "ActiveDoc", None)
    if value is None or callable(value):
        return None
    return value


class PostSaveRebindFailed(RuntimeError):
    """SaveAs wrote a file, then ActiveDoc/path rebind did not return a model.

    This is not a COM disconnect and must not delete the part.
    """


def execution_exit_code(status) -> int:
    """CLI code for a sheet-metal run. A saved part is not exit 1."""
    if status in KEPT_AFTER_SAVE_STATUSES:
        return 0
    if status == "failed":
        return 1
    if status == "pending":
        return 3
    return 0


def kept_after_save_exit(rc, *, generation_saved, cleanup_status=None, post_save_outcome=None) -> int:
    """Exit 0 when a saved part's only failure is post-save cleanup or rebind.

    An unverified success with no COM failure keeps ``rc`` (often 3). A hard
    failure before any file is written also keeps ``rc``.
    """
    if not generation_saved:
        return rc
    if cleanup_status in KEPT_AFTER_SAVE_STATUSES or post_save_outcome in KEPT_AFTER_SAVE_STATUSES:
        return 0
    return rc


def saved_generation_after_disconnect(generation, error):
    """Keep a finished save visible. This is not a SolidWorks live pass."""
    from sw_session import normalize_com_disconnect
    reported = normalize_com_disconnect(error) or error
    return {
        "status": SAVED_DISCONNECT_STATUS,
        "exit_code": 0,
        "warning": (
            "owned COM server disconnected after the part was saved; "
            "ExitApp was not called"
        ),
        "error": str(reported),
        "modeling": "saved_pending_reopen",
        "native_acceptance": "pending_windows_validation",
        "sw_live_verified": False,
        "passed": False,
        "file_on_disk": True,
        "exit_app": False,
        "process_killed": False,
        "generation": generation,
        "post_save_disconnect": str(reported),
        "error_kind": type(reported).__name__,
        "hresult": -2147220995,
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


def rebind_failure_after_save(error, product) -> bool:
    """True when SaveAs left a SLDPRT and rebind failed without a disconnect."""
    if product is None or Path(product).suffix.casefold() != ".sldprt":
        return False
    if not product_file_ready(product):
        return False
    if isinstance(error, PostSaveRebindFailed):
        return True
    return is_member_not_found(error)


def partial_rebind_after_save(generation, error):
    """Keep the saved part. This is not a SolidWorks live pass."""
    return {
        "status": PARTIAL_REBIND_STATUS,
        "exit_code": 0,
        "warning": (
            "SaveAs3 wrote the part; ActiveDoc rebind failed; "
            "the file was kept and ExitApp was not called"
        ),
        "error": str(error),
        "error_kind": type(error).__name__,
        "modeling": "saved_pending_reopen",
        "native_acceptance": "pending_windows_validation",
        "sw_live_verified": False,
        "passed": False,
        "file_on_disk": True,
        "exit_app": False,
        "process_killed": False,
        "generation": generation,
        "recovery": "products_kept",
    }


def rebind_model_after_save(app, fetch_active, read_title, *, lease=None, open_saved=None):
    """Drop the pre-save model pointer and resolve the document that is open now.

    ``fetch_active`` should read ``ActiveDoc`` as a property. A
    ``DISP_E_MEMBERNOTFOUND`` from calling that property is not a disconnect:
    ``open_saved`` (GetOpenDocumentByName / OpenDoc6 by path) runs next. If the
    file is already on disk the caller keeps it.
    """
    member_error = None
    try:
        model = fetch_active(app)
    except PostSaveComDisconnect:
        mark_session_disconnected(lease)
        raise
    except Exception as error:
        if is_com_server_disconnect(error):
            mark_session_disconnected(lease)
            raise PostSaveComDisconnect(
                "post-save COM disconnect while rebinding the open document: " + str(error)
            ) from error
        if not is_member_not_found(error):
            raise
        member_error = error
        model = None
    if model is None and open_saved is not None:
        try:
            model = open_saved(app)
        except Exception as error:
            if is_com_server_disconnect(error):
                mark_session_disconnected(lease)
                raise PostSaveComDisconnect(
                    "post-save COM disconnect while reopening the saved part: " + str(error)
                ) from error
            if member_error is None:
                member_error = error
            model = None
    if model is None:
        if member_error is not None:
            raise PostSaveRebindFailed(
                "post-save ActiveDoc rebind failed; SaveAs file is kept; "
                "ExitApp was not called: " + str(member_error)
            ) from member_error
        raise PostSaveComDisconnect(
            "post-save rebind found no ActiveDoc; the save is not a live-session pass"
        )
    try:
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
        if is_member_not_found(error):
            raise PostSaveRebindFailed(
                "post-save title read failed with DISP_E_MEMBERNOTFOUND; "
                "SaveAs file is kept; ExitApp was not called: " + str(error)
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


def verify_saved_part(path, *, expected_dims_mm=None, expected_body_count=None,
                      inspect_cylinders=False):
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
        from app_logging import get_journal
        get_journal().record('part_reopen_geometry',path=str(path),rebuilt=True,reopened=True,
            body_count=len(body_boxes),bounds_mm=bounds,dimensions_mm=dims,volume_mm3=None,
            bounds_precision='approximate',geometry_verified=False,production_approved=False)
        surface_inventory = None
        if inspect_cylinders:
            from native_surface_inventory import cylindrical_surface_inventory
            surface_inventory = cylindrical_surface_inventory(part, sw, module)
        return {'status':status,'rebuilt':True,'reopened':True,
                'cylindrical_surfaces':surface_inventory,
                'verification_scope':('solid_inventory_envelope_and_cylindrical_surfaces'
                                      if inspect_cylinders else 'solid_inventory_and_optional_envelope_only'),
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

