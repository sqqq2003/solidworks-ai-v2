"""Reopen a newly generated owned part and verify native solid geometry."""
import math
from pathlib import Path


def assert_native_save(path, error_code):
    path = Path(path)
    if type(error_code) is not int or int(error_code) != 0:
        raise RuntimeError(f'native save error: {error_code}')
    if not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError('native save produced a missing or empty file')


def verify_saved_part(path, *, expected_dims_mm=None):
    from sw_session import require_model_write, close_owned_document
    import solidworks_generator as sw
    import pythoncom
    import win32com.client
    lease = require_model_write()
    path = Path(path).resolve()
    if not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError('generated part is missing or empty')
    pythoncom.CoInitialize()
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
        bounds = [v*1000 for v in sw._body_bounds(part, module)]
        dims = [bounds[i+3]-bounds[i] for i in range(3)]
        if not all(math.isfinite(v) and v > 0 for v in dims):
            raise RuntimeError('invalid reopened solid bounding dimensions')
        if expected_dims_mm is not None:
            if len(expected_dims_mm) != 3 or any(not math.isclose(a,b,rel_tol=1e-4,abs_tol=.05)
                    for a,b in zip(sorted(dims),sorted(expected_dims_mm))):
                raise RuntimeError('reopened solid dimensions differ from plan')
        return {'status':'reopen_geometry_verified','rebuilt':True,'reopened':True,
                'bounds_mm':bounds,'dimensions_mm':dims,
                'feature_types':[str(sw._com_read(f,'GetTypeName2')) for f in sw._features(model,module)],
                'mechanical_acceptance':'unverified','threads':'not_certified'}
    finally:
        try:
            if title and app is not None and title in lease.owned_docs:
                close_owned_document(lease,app,title)
        finally:
            pythoncom.CoUninitialize()
