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
        from solidworks_generator import generate_sheet_metal
        p = plan['parameters']
        result = generate_sheet_metal(analysis, plan['profile_index'], plan['bend_indices'],
            p['thickness_mm'], p['radius_mm'], p['angle_degrees'], part,
            flip_direction=p['flip_direction'], auto_bend=True, cad_import=False,
            relief_bend_indices=plan['relief_bend_indices'],
            bend_allowance=BendAllowanceSpec(**plan['bend_allowance']['spec']),
            close_saved_document=True)
        data = asdict(result)
        data['path'] = Path(result.path).name
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
                'editable': False, 'bend_feature_count': sum(t in {'SM3dBend', 'SketchBend', 'SMEdgeFlange'} for t in types)}
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
                    custom = data.GetCustomBendAllowance()
                    evidence['bend_allowance_type'] = int(custom.Type)
                    evidence['k_factor'] = float(custom.KFactor)
                    from bend_allowance import SW_BEND_ALLOWANCE_K_FACTOR
                    evidence['editable'] = int(custom.Type) == SW_BEND_ALLOWANCE_K_FACTOR
                finally:
                    data.ReleaseSelectionAccess()
                break
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
