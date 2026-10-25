"""Reopen a newly generated owned part and verify native solid geometry."""
import math
from pathlib import Path


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
    from sw_session import require_model_write, close_owned_document, initialize_com_scope
    import solidworks_generator as sw
    import pythoncom
    import win32com.client
    lease = require_model_write()
    path = Path(path).resolve()
    if not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError('generated part is missing or empty')
    local_com_initialized=initialize_com_scope(pythoncom,lease)
    app = None
    title = None
    try:
        raw, _ = sw._connect_task_solidworks(lease, win32com, pythoncom)
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
            if local_com_initialized:pythoncom.CoUninitialize()


