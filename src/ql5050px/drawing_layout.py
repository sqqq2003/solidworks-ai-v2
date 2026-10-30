"""Offline engineering sheet composition with notes, dimensions and BOM."""
from html import escape
from math import isfinite
from pathlib import Path


def _number(value):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not isfinite(value):
        raise ValueError("drawing coordinate must be finite")
    return float(value)


def render_sheet_svg(sheet, destination):
    """Explicit polyline projection views in sheet mm; no automatic 3D projection.

    Views: {origin_mm, scale, contours_xy_mm, label}; dimensions: {a,b,
    offset_mm,label?}; notes and BOM use a separate right-hand column.
    SVG is an offline review sheet, not a native SLDDRW or manufacturing release.
    """
    width,height = (_number(sheet.get(k,v)) for k,v in (("width_mm",420),("height_mm",297)))
    if width<200 or height<150:
        raise ValueError("sheet must be at least 200 x 150 mm")
    sidebar = width-105
    output = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}mm" height="{height}mm" viewBox="0 0 {width} {height}">',
              '<rect width="100%" height="100%" fill="white"/>',
              '<g fill="none" stroke="black" stroke-width="0.25">',
              f'<rect x="10" y="10" width="{width-20}" height="{height-20}"/>',
              f'<path d="M{sidebar} 10V{height-10}M10 {height-35}H{width-10}"/>','</g>']
    def text(x,y,value,size=3):
        output.append(f'<text x="{x}" y="{y}" font-size="{size}" font-family="sans-serif">{escape(str(value))}</text>')
    text(15,18,sheet.get("title","QL-5050PX"),4)
    text(15,height-25,sheet.get("part_number","pending_mapping"),4)
    text(15,height-18,"Units: mm | " + str(sheet.get("revision","development")))
    text(15,height-12,"UNVERIFIED DEVELOPMENT DRAWING",2.8)
    for view in sheet.get("views",[]):
        ox,oy = map(_number,view["origin_mm"])
        scale = _number(view.get("scale",1))
        if scale<=0:
            raise ValueError("positive drawing scale required")
        for contour in view["contours_xy_mm"]:
            transformed = [(ox+_number(p[0])*scale,oy-_number(p[1])*scale) for p in contour]
            if any(not 12<=x<sidebar-3 or not 22<=y<height-38 for x,y in transformed):
                raise ValueError("view exceeds allocated drawing region")
            coords = " ".join(f"{x},{y}" for x,y in transformed)
            output.append(f'<polyline points="{coords}" fill="none" stroke="black" stroke-width="0.35"/>')
        text(ox,oy+6,view.get("label",""))
    for dimension in sheet.get("dimensions",[]):
        ax,ay = map(_number,dimension["a"])
        bx,by = map(_number,dimension["b"])
        offset = _number(dimension.get("offset_mm",5))
        if abs(ay-by)>1e-8:
            raise ValueError("v1 sheet dimensions support horizontal references")
        y = ay+offset
        output.append(f'<path d="M{ax} {ay}V{y+2}M{bx} {by}V{y+2}M{ax} {y}H{bx}" fill="none" stroke="black" stroke-width="0.2"/>')
        for x in (ax,bx):
            output.append(f'<path d="M{x-1} {y+1}l2 -2" stroke="black" stroke-width="0.3"/>')
        text((ax+bx)/2,y-1,dimension.get("label",f"{abs(bx-ax):g}"))
    y = 20
    text(sidebar+3,y,"NOTES / BOM",3.5)
    for note in sheet.get("notes",[]):
        # Deterministic basic wrapping avoids long text escaping the page.
        words = str(note).split()
        line = ""
        for word in words:
            if len(line)+len(word)>45 and line:
                y+=5
                text(sidebar+3,y,line,2.7)
                line = ""
            line += (" " if line else "")+word
        y+=5
        text(sidebar+3,y,line,2.7)
    y+=8
    for row in sheet.get("bom",[]):
        text(sidebar+3,y,f'{row["item"]}. {row["part_number"]} x{row["quantity"]}',2.8)
        y+=4
        text(sidebar+5,y,row.get("material","pending_mapping"),2.5)
        y+=5
    if y>height-40:
        raise ValueError("notes/BOM overflow; split into additional sheets")
    output.append('</svg>')
    with Path(destination).open("x",encoding="utf-8") as stream:
        stream.write("\n".join(output))
    return str(destination)


def annotate_owned_drawing(port, drawing_path, *, notes=(), bom=()):
    """Host driver must implement annotate_drawing; no direct COM attachment."""
    with port.writer():
        return port.guarded("annotate_drawing",str(drawing_path),list(notes),list(bom))


class DrawingAnnotationsMixin:
    """Add to an owned Windows host driver alongside NativeExportsMixin.

    Uses indexed COM Text property via IDispatch; Windows binding is untested.
    Document remains dirty; saving is a separate explicit host transaction.
    """
    def annotate_drawing(self, drawing_path, notes, bom):
        from sw_api.win32com_backend import _import_sw_session
        from sw_compat.annotation import set_annotation_position
        _import_sw_session().require_model_write()
        self.require_isolated_model(drawing_path)
        drawing = self.resolve_owned_model(drawing_path)
        if int(drawing.GetType())!=3:
            raise ValueError("owned drawing document required")
        count = 0
        for i,note in enumerate(notes):
            obj = drawing.InsertNote(str(note))
            if obj is None:
                raise RuntimeError("InsertNote failed")
            set_annotation_position(obj, 0.02, 0.25-i*0.008, 0)
            count+=1
        if bom:
            import pythoncom
            table = drawing.InsertTableAnnotation2(False,0.20,0.25,1,"",len(bom)+1,4)
            if table is None:
                raise RuntimeError("InsertTableAnnotation2 failed")
            rows = [["Item","Part number","Material","Qty"]]+[
                [r["item"],r["part_number"],r.get("material","pending_mapping"),r["quantity"]] for r in bom]
            dispatch = table._oleobj_
            dispid = dispatch.GetIDsOfNames("Text")
            for i,row in enumerate(rows):
                for j,value in enumerate(row):
                    dispatch.Invoke(dispid,0,pythoncom.DISPATCH_PROPERTYPUT,0,i,j,str(value))
        return {"notes_created":count,"bom_rows":len(bom),"saved":False,
                "status":"native_annotations_created","engineering_acceptance":"unverified"}
