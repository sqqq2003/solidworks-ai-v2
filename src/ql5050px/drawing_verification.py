"""Native drawing readback and PDF validation; imports remain cloud-safe."""
import math
from pathlib import Path
from .native_machine import read_member


def default_frame_mm(width, height):
    # GB/T 14689 binding margin on the left, 10 mm on the other edges. A2/A3.
    return [25, 10, float(width)-10, float(height)-10]


def default_title_block_mm(width):
    return [float(width)-180, 0, float(width), 60]


def view_exceeds_frame(box, frame):
    return box[0]<frame[0]-.1 or box[1]<frame[1]-.1 or box[2]>frame[2]+.1 or box[3]>frame[3]+.1


def verify_view_layout(drawing, task, views):
    sheet=drawing.GetCurrentSheet()
    properties=read_member(sheet,'GetProperties2')
    expected=float(task['scale'][0])/float(task['scale'][1])
    actual=float(properties[2])/float(properties[3])
    if not math.isclose(actual,expected,rel_tol=1e-8):
        raise RuntimeError(f'drawing sheet scale mismatch: {actual} != {expected}')
    width,height=float(properties[5])*1000,float(properties[6])*1000
    if not math.isclose(width,task['width_mm'],abs_tol=.1) or not math.isclose(height,task['height_mm'],abs_tol=.1):
        raise RuntimeError('drawing sheet size differs from task')
    # GB/T frame defaults; callers may supply a different verified frame.
    frame=task.get('frame_bounds_mm',default_frame_mm(width,height))
    boxes=[]
    for name,view in views.items():
        if not math.isclose(float(read_member(view,'ScaleDecimal')),expected,rel_tol=1e-8):
            raise RuntimeError('drawing view scale mismatch: '+name)
        requested=next(item['position_mm'] for item in task['drawing_model']['views'] if item['id']==name)
        actual_position=[float(v)*1000 for v in read_member(view,'Position')]
        if len(actual_position)!=2 or any(not math.isclose(a,b,abs_tol=.1) for a,b in zip(actual_position,requested)):
            raise RuntimeError('drawing view position readback mismatch: '+name)
        box=[float(v)*1000 for v in read_member(view,'GetOutline')]
        if len(box)!=4 or not all(map(math.isfinite,box)) or box[2]<=box[0] or box[3]<=box[1]:
            raise RuntimeError('invalid drawing view bounds: '+name)
        if view_exceeds_frame(box, frame):
            raise RuntimeError('drawing view exceeds frame: '+name)
        boxes.append((name,box))
    reserved=task.get('reserved_rectangles_mm',[default_title_block_mm(width)])
    for index,(name,a) in enumerate(boxes):
        for other,b in boxes[index+1:]+[('reserved area',r) for r in reserved]:
            if min(a[2],b[2])-max(a[0],b[0])>.1 and min(a[3],b[3])-max(a[1],b[1])>.1:
                raise RuntimeError(f'drawing layout overlap: {name} / {other}')
    return {'sheet_scale':[properties[2],properties[3]],'sheet_size_mm':[width,height],
            'views':[{'name':name,'bounds_mm':box} for name,box in boxes], 'frame_bounds_mm':frame}


def _write_position(view, position_mm):
    view.UseSheetScale=1
    position=tuple(float(v)/1000 for v in position_mm)
    if '_oleobj_' in getattr(view,'__dict__',{}):
        import pythoncom
        from win32com.client import VARIANT
        position=VARIANT(pythoncom.VT_ARRAY|pythoncom.VT_R8,position)
    view.Position=position


def _measure_views(views):
    """Outline size plus the offset from Position to the GetOutline center."""
    measured={}
    for name,view in views.items():
        position=[float(v)*1000 for v in read_member(view,'Position')]
        if len(position)!=2 or not all(map(math.isfinite,position)):
            raise RuntimeError('invalid drawing view position: '+name)
        box=[float(v)*1000 for v in read_member(view,'GetOutline')]
        if len(box)!=4 or not all(map(math.isfinite,box)) or box[2]<=box[0] or box[3]<=box[1]:
            raise RuntimeError('invalid drawing view bounds: '+name)
        center=[(box[0]+box[2])/2,(box[1]+box[3])/2]
        measured[name]={'anchor':[position[0]-center[0],position[1]-center[1]],
                        'size':[box[2]-box[0],box[3]-box[1]],'center':center,'position':position}
    return measured


def _apply_outline_centers(task, views, centers, measured):
    from .auto_layout import position_for_outline_center
    for item in task['drawing_model']['views']:
        item['position_mm']=position_for_outline_center(centers[item['id']], measured[item['id']]['anchor'])
        _write_position(views[item['id']], item['position_mm'])


def _nudge_outline_centers(task, views, centers):
    """One translation if the outline did not land on the slot. Scale stays put."""
    moved=False
    for item in task['drawing_model']['views']:
        geometry=_measure_views({item['id']:views[item['id']]})[item['id']]
        delta=[centers[item['id']][0]-geometry['center'][0], centers[item['id']][1]-geometry['center'][1]]
        if any(abs(v)>0.05 for v in delta):
            item['position_mm']=[geometry['position'][0]+delta[0], geometry['position'][1]+delta[1]]
            _write_position(views[item['id']], item['position_mm'])
            moved=True
    return moved


def lock_view_layout(drawing,task,views):
    # SW can change sheet scale when inserting the first view. Enforce the
    # requested ratio here and do not replace it when a view misses the frame.
    if not drawing.GetCurrentSheet().SetScale(*task['scale'],True,True):
        raise RuntimeError('drawing sheet scale update failed')
    if task.get('auto_layout'):
        from .auto_layout import first_angle_layout
        for view in views.values():view.UseSheetScale=1
        if not read_member(drawing,'EditRebuild3'):raise RuntimeError('view size rebuild failed')
        measured=_measure_views(views)
        centers=first_angle_layout(task['width_mm'],task['height_mm'],{name:item['size'] for name,item in measured.items()})
        _apply_outline_centers(task,views,centers,measured)
        if not read_member(drawing,'EditRebuild3'):raise RuntimeError('drawing layout rebuild failed')
        updated=_measure_views(views)
        # A stale outline (common before the view is actually moved) must be
        # placed again at the same scale. Refusal stays refusal.
        if any(abs(a-b)>0.5 for name in measured for a,b in zip(measured[name]['size'], updated[name]['size'])):
            centers=first_angle_layout(task['width_mm'],task['height_mm'],{name:item['size'] for name,item in updated.items()})
            _apply_outline_centers(task,views,centers,updated)
            if not read_member(drawing,'EditRebuild3'):raise RuntimeError('drawing layout rebuild failed')
        if _nudge_outline_centers(task,views,centers):
            if not read_member(drawing,'EditRebuild3'):raise RuntimeError('drawing layout rebuild failed')
    else:
        for item in task['drawing_model']['views']:
            _write_position(views[item['id']], item['position_mm'])
        if not read_member(drawing,'EditRebuild3'):raise RuntimeError('drawing layout rebuild failed')
    return verify_view_layout(drawing,task,views)


def validate_pdf(path,expected_pages):
    path=Path(path)
    if not path.is_file() or path.stat().st_size==0:raise RuntimeError('PDF export did not create a nonempty file')
    if not path.read_bytes().startswith(b'%PDF-'):raise RuntimeError('PDF signature missing')
    from pypdf import PdfReader
    try:
        reader=PdfReader(str(path),strict=True)
        if reader.is_encrypted or len(reader.pages)!=expected_pages:raise ValueError('unexpected PDF page count/encryption')
        sizes=[]
        for page in reader.pages:
            content=page.get_contents()
            if content is None or not content.get_data().strip():raise ValueError('empty PDF page content')
            w,h=float(page.mediabox.width),float(page.mediabox.height)
            if min(w,h)<=0:raise ValueError('invalid PDF page size')
            sizes.append([w,h])
    except Exception as error:raise RuntimeError('PDF parse/content validation failed: '+str(error)) from error
    return {'pages':len(reader.pages),'page_sizes_points':sizes,'parsed':True,'visual_review':'pending'}


def export_pdf(driver,drawing,path):
    driver.guard();path=driver.owned_path(path)
    if path.exists():raise FileExistsError(path)
    driver.activate(drawing)
    sheets=list(drawing.GetSheetNames() or [])
    if not sheets:raise RuntimeError('drawing has no exportable sheets')
    current=str(read_member(drawing.GetCurrentSheet(),'GetName'))
    try:
        for name in sheets:
            if not drawing.ActivateSheet(name):raise RuntimeError('PDF sheet activation failed: '+name)
            props=read_member(drawing.GetCurrentSheet(),'GetProperties2')
            if max(float(props[5]),float(props[6]))>5.08:
                raise RuntimeError('PDF sheet exceeds SolidWorks 5080 mm limit: '+name)
    finally:
        drawing.ActivateSheet(current)
    data=driver.app.GetExportFileData(1)
    if data is None:raise RuntimeError('PDF export options unavailable')
    data.ViewPdfAfterSaving=False
    names=sheets
    if '_oleobj_' in getattr(data,'__dict__',{}):
        import pythoncom
        from win32com.client import VARIANT
        names=VARIANT(pythoncom.VT_ARRAY|pythoncom.VT_BSTR,sheets)
    if not data.SetSheets(3,names):raise RuntimeError('PDF explicit sheet selection failed')
    result=drawing.Extension.SaveAs(str(path),0,1,data,0,0)
    ok=result[0] if isinstance(result,tuple) else result
    error=result[1] if isinstance(result,tuple) and len(result)>1 else None
    if ok is not True or error not in (None,0):raise RuntimeError('native PDF SaveAs failed: '+str(result))
    return {'save_result':result,'sheets':sheets,**validate_pdf(path,len(sheets))}
