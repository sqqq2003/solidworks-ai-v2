"""Native export driver mixin for a task-owned Windows driver.

The host driver supplies app, preflight, checkpoint, restore, and normal
transaction operations. Call ONLY via WindowsExecutionPort (owned STA lease).
Native API signatures and generated output remain untested on Windows.
"""
from pathlib import Path


class NativeExportsMixin:
    def export_drawing(self, request, destination):
        """Create an SLDDRW from an explicit template and isolated model copy.

        request: template, model_path, sheet_width_mm, sheet_height_mm,
        views [{orientation: '*Front', x_mm, y_mm}]. No inferred OEM view names.
        """
        from .parameters import numeric
        from sw_api.win32com_backend import _import_sw_session
        _import_sw_session().require_model_write()
        output = Path(destination).resolve()
        template = Path(request["template"]).resolve()
        source = Path(request["model_path"]).resolve()
        if output.exists() or output.suffix.lower() != ".slddrw":
            raise ValueError("new SLDDRW output required")
        if not template.is_file() or not source.is_file() or template.suffix.lower() != ".drwdot":
            raise ValueError("existing drawing template and isolated model required")
        # The host must prove this model belongs to the task and is isolated,
        # including all assembly references. This is intentionally mandatory.
        self.require_isolated_model(str(source))
        width = numeric(request["sheet_width_mm"],"sheet width")/1000
        height = numeric(request["sheet_height_mm"],"sheet height")/1000
        views = request["views"]
        if not views:
            raise ValueError("at least one drawing view required")
        validated = []
        for view in views:
            x = numeric(view["x_mm"],"view x")/1000
            y = numeric(view["y_mm"],"view y")/1000
            if x >= width or y >= height or not view.get("orientation"):
                raise ValueError("view must lie inside drawing sheet and name orientation")
            validated.append((view["orientation"],x,y))
        drawing = self.app.NewDocument(str(template),12,width,height)
        if drawing is None:
            raise RuntimeError("NewDocument returned no drawing")
        # Do not close on failure: keep the new, owned drawing for diagnostics.
        for orientation,x,y in validated:
            if drawing.CreateDrawViewFromModelView3(str(source),orientation,x,y,0) is None:
                raise RuntimeError(f"failed drawing view: {orientation}")
        if not drawing.EditRebuild3():
            raise RuntimeError("drawing rebuild failed")
        # SaveAs3 returns swFileSaveError_e (0 means success).
        error = int(drawing.SaveAs3(str(output),0,1))
        if error or not output.is_file():
            raise RuntimeError(f"drawing SaveAs3 failed: {error}")
        return {"status":"native_export_created", "path":str(output),
                "views_created":len(validated), "reopen_status":"unverified",
                "engineering_acceptance":"unverified"}

    def export_flat_dxf(self, request, destination):
        """Export native sheet-metal flat geometry and bend lines from owned part."""
        from sw_api.win32com_backend import _import_sw_session
        _import_sw_session().require_model_write()
        source = str(Path(request["model_path"]).resolve())
        output = Path(destination).resolve()
        if output.exists() or output.suffix.lower() != ".dxf":
            raise ValueError("new DXF output required")
        self.require_isolated_model(source)
        # Supplied native object must be resolved by host driver from task lease.
        model = self.resolve_owned_model(source)
        if int(model.GetType()) != 1:
            raise ValueError("flat DXF requires a part document")
        # swExportToDWG_ExportSheetMetal=1; geometry=1, bend lines=4.
        ok = model.ExportToDWG2(str(output),source,1,True,None,False,False,5,None)
        if not ok or not output.is_file():
            raise RuntimeError("ExportToDWG2 failed")
        return {"status":"native_export_created", "path":str(output),
                "engineering_acceptance":"unverified"}
