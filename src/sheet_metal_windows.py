"""Native bridge: existing generator, then fresh reopen and feature readback.

Call the entire pipeline in sw_session.run_on_task_sta. No implicit user-session
attachment and no process termination. COM imports remain Windows-call-only.
"""
from dataclasses import asdict
import sys
from pathlib import Path


class WindowsSheetMetalPort:
    simulated = False

    def guard(self):
        if sys.platform != 'win32':
            raise RuntimeError('SolidWorks native execution requires Windows')
        from sw_session import require_model_write
        return require_model_write()

    def generate(self, analysis, plan, part):
        self.guard()
        from bend_allowance import BendAllowanceSpec
        from solidworks_generator import generate_sheet_metal_with_relief_retries
        p = plan['parameters']
        result = generate_sheet_metal_with_relief_retries(analysis, plan['profile_index'], plan['bend_indices'],
            p['thickness_mm'], p['radius_mm'], p['angle_degrees'], part,
            flip_direction=p['flip_direction'], auto_bend=True, cad_import=False,
            relief_bend_indices=plan['relief_bend_indices'],
            bend_allowance=BendAllowanceSpec(**plan['bend_allowance']['spec']),
            close_saved_document=True)
        data = asdict(result)
        data['path'] = Path(result.path).name
        self.completed_bend_count = result.bend_count
        return data

    def reopen_inspect(self, part):
        lease = self.guard()
        import pythoncom
        import win32com.client
        from sw_session import close_owned_document, require_model_write
        from solidworks_generator import (_connect_task_solidworks, ensure_solidworks_typelib,
            _as_interface, _features, _com_read)
        pythoncom.CoInitialize()
        app = None
        title = None
        try:
            raw, _ = _connect_task_solidworks(lease, win32com, pythoncom)
            module = ensure_solidworks_typelib()
            app = _as_interface(module, raw, 'ISldWorks')
            lease.note_bound_application(app)
            # A fresh reopening is mandatory, not inspecting an unsaved live handle.
            if str(part.name) in lease.owned_docs:
                close_owned_document(lease, app, part.name)
            require_model_write(lease)
            opened = app.OpenDoc6(str(part), 1, 1, '', 0, 0)
            raw_model = opened[0] if isinstance(opened, tuple) else opened
            if raw_model is None:
                raise RuntimeError('OpenDoc6 failed for generated native part')
            model = _as_interface(module, raw_model, 'IModelDoc2')
            title = str(_com_read(model, 'GetTitle'))
            if title in lease.foreign_titles:
                raise RuntimeError('reopened title belongs to another document')
            lease.note_owned_document(title, handle_id=id(raw_model))
            require_model_write(lease)
            rebuilt = bool(_com_read(model, 'EditRebuild3'))
            features = _features(model, module)
            types = [str(_com_read(f, 'GetTypeName2')) for f in features]
            evidence = {'reopened': True, 'rebuilt': rebuilt, 'feature_types': types,
                'editable': False, 'completed_bend_count': getattr(self, 'completed_bend_count', None), 'bend_feature_count': sum(t in {'SM3dBend', 'SketchBend', 'SMEdgeFlange'} for t in types)}
            for feature, kind in zip(features, types):
                if kind != 'SheetMetal':
                    continue
                definition = feature.GetDefinition()
                data = _as_interface(module, definition, 'ISheetMetalFeatureData')
                if not data.AccessSelections(model, None):
                    raise RuntimeError('sheet-metal definition selection access failed')
                try:
                    evidence['thickness_mm'] = float(data.Thickness) * 1000
                    evidence['radius_mm'] = float(data.BendRadius) * 1000
                    custom = _as_interface(module, data.GetCustomBendAllowance(), 'ICustomBendAllowance')
                    evidence['bend_allowance_type'] = int(custom.Type)
                    evidence['k_factor'] = float(custom.KFactor)
                    from bend_allowance import SW_BEND_ALLOWANCE_K_FACTOR
                    evidence['editable'] = int(custom.Type) == SW_BEND_ALLOWANCE_K_FACTOR
                finally:
                    data.ReleaseSelectionAccess()
                break
            try:
                evidence['geometry_states'] = measure_folded_and_flat(model, module)
            except Exception as exc:
                # The caller closes this unsaved inspection document in finally.
                # Failed restoration must not permit export or acceptance.
                raise RuntimeError("folded/flat measurement or state restoration failed: " + str(exc)) from exc
            return evidence
        finally:
            try:
                if title and title in lease.owned_docs and app is not None:
                    close_owned_document(lease, app, title)
            finally:
                pythoncom.CoUninitialize()

    def export_flat(self, part, dxf):
        self.guard()
        from solidworks_generator import export_flat_pattern_dxf
        export_flat_pattern_dxf(part, dxf, close_document=True)

    def abort(self, stage):
        # Generation/inspection/export close only their owned document in finally.
        # If a lease was poisoned, preserve staging for Windows recovery.
        self.guard()


def measure_folded_and_flat(model, module):
    """Inspect the owned work part in both states, restore suppression, never save.

    Bounding boxes are in model axes, in mm; DXF axes may differ. These are
    diagnostics, not automatic validation of a dimensional manufacturing datum.
    """
    from sw_session import require_model_write
    from solidworks_generator import _features, _body_bounds, _as_interface, _com_read
    lease = require_model_write()
    features = [f for f in _features(model, module) if _com_read(f, 'GetTypeName2') == 'FlatPattern']
    if len(features) != 1:
        raise RuntimeError('expected one FlatPattern for geometry measurements')
    feature = features[0]
    suppressed = _com_read(feature, 'IsSuppressed')
    if type(suppressed) is not bool:
        raise RuntimeError('flat suppression state unavailable')
    part = _as_interface(module, model, 'IPartDoc')

    def set_flat(flat):
        require_model_write(lease)
        model.ClearSelection2(True)
        if not model.Extension.SelectByID2(feature.Name, 'BODYFEATURE', 0., 0., 0., False, 0, None, 0):
            raise RuntimeError('cannot select flat feature for measurement')
        _com_read(model, 'EditUnsuppress2' if flat else 'EditSuppress2')
        model.ClearSelection2(True)
        require_model_write(lease)
        if not _com_read(model, 'EditRebuild3'):
            raise RuntimeError('geometry measurement rebuild failed')
        if bool(_com_read(feature, 'IsSuppressed')) == flat:
            raise RuntimeError('flat suppression did not change')

    try:
        set_flat(False)
        folded = [v * 1000 for v in _body_bounds(part, module)]
        set_flat(True)
        flat = [v * 1000 for v in _body_bounds(part, module)]
        return {'status': 'measured', 'units': 'mm', 'folded_bounds': folded,
                'flat_bounds': flat, 'axes': 'model_axes', 'saved': False}
    finally:
        set_flat(not suppressed)
