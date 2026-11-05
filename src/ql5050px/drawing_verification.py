"""Native drawing readback and PDF validation; imports remain cloud-safe."""
import math
from pathlib import Path
from .auto_layout import rectangles_overlap
from .native_machine import read_member


def default_frame_mm(width, height):
    # GB/T 14689 binding margin on the left, 10 mm on the other edges. A2/A3.
    return [25, 10, float(width)-10, float(height)-10]


def default_title_block_mm(width):
    return [float(width)-180, 0, float(width), 60]


def view_exceeds_frame(box, frame):
    return box[0]<frame[0]-.1 or box[1]<frame[1]-.1 or box[2]>frame[2]+.1 or box[3]>frame[3]+.1


def annotation_evidence(owner, kind, requested):
    from sw_compat.annotation import resolve_annotation,read_annotation_position
    from sw_compat.com_access import read_com_member
    annotation=resolve_annotation(owner)
    name=str(read_com_member(annotation,'GetName'))
    position=[float(v)*1000 for v in read_annotation_position(owner)]
    if not name or len(position)!=3 or not all(math.isfinite(v) for v in position):
        raise RuntimeError('drawing annotation identity/position unavailable')
    result={'kind':kind,'name':name,'type':int(read_com_member(annotation,'GetType')),
            'position_mm':position,'requested':requested}
    if kind=='note':
        result['text']=str(read_com_member(owner,'GetText'))
        if result['text']!=requested['text']:raise RuntimeError('drawing annotation text mismatch')
    return result


def verify_annotation_evidence(drawing,expected):
    """Require one matching native object; view enumeration may expose it twice."""
    if not expected:return []
    from sw_compat.com_access import read_com_member
    annotations={};view=read_member(drawing,'GetFirstView');seen=set()
    while view is not None:
        view_name=str(read_member(view,'GetName2'))
        if view_name in seen or len(seen)>=4096:raise RuntimeError('drawing view chain cyclic or oversized')
        seen.add(view_name)
        for annotation in read_member(view,'GetAnnotations') or []:
            name=str(read_com_member(annotation,'GetName'))
            entries=annotations.setdefault(name,[])
            def same_object(other):
                if annotation is other:return True
                if hasattr(annotation,'_oleobj_') and hasattr(other,'_oleobj_'):
                    import pythoncom
                    return annotation._oleobj_.QueryInterface(pythoncom.IID_IUnknown)==other._oleobj_.QueryInterface(pythoncom.IID_IUnknown)
                return False
            if not any(same_object(other) for other in entries):entries.append(annotation)
        view=read_member(view,'GetNextView')
    results=[]
    for item in expected:
        candidates=annotations.get(item['name'],[])
        if not candidates:raise RuntimeError('saved drawing annotation missing: '+item['name'])
        matches=[]
        for annotation in candidates:
            position=[float(v)*1000 for v in read_com_member(annotation,'GetPosition')]
            if (len(position)!=3 or not all(math.isfinite(v) for v in position) or
                    int(read_com_member(annotation,'GetType'))!=item['type'] or
                    any(not math.isclose(a,b,abs_tol=.1) for a,b in zip(position,item['position_mm']))):continue
            if item['kind']=='note':
                note=read_com_member(annotation,'GetSpecificAnnotation')
                if str(read_com_member(note,'GetText'))!=item['text']:continue
            if item['kind']=='model_dimension':
                from .model_dimensions import display_dimension_value,dimension_values_match
                display=read_com_member(annotation,'GetSpecificAnnotation')
                if not dimension_values_match(display_dimension_value(display),item['model_dimension']):continue
            matches.append(position)
        if not matches:raise RuntimeError('saved annotation type/position/text differs: '+item['name'])
        if len(matches)!=1:raise RuntimeError('ambiguous saved annotation identity: '+item['name'])
        results.append({**item,'reopened':True,'position_mm':matches[0]})
    return results


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
            if rectangles_overlap(a, b):
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


def _outline_bounds(item):
    cx,cy=item['center']; w,h=item['size']
    return [cx-w/2, cy-h/2, cx+w/2, cy+h/2]


def _format_outlines(measured):
    parts=[]
    for name in ('front','top','right'):
        if name not in measured:continue
        parts.append(name+':['+','.join(f'{v:.2f}' for v in _outline_bounds(measured[name]))+']')
    return 'outlines_mm={'+','.join(parts)+'}'


def _refuse_measured(measured, error=None, task=None):
    from .auto_layout import LayoutDoesNotFit,explicit_fit_alternatives
    diagnostic={'sizes_mm':{name:item['size'] for name,item in measured.items()},
                'outlines_mm':{name:_outline_bounds(item) for name,item in measured.items()}}
    alternatives=[]
    suffix='; '+_format_outlines(measured)
    if task is not None:
        diagnostic.update(sheet_mm=[float(task['width_mm']),float(task['height_mm'])],scale=list(task['scale']))
        alternatives=explicit_fit_alternatives(diagnostic['sizes_mm'],task['scale'],diagnostic['sheet_mm'])
        suffix+=f"; sheet_mm=[{float(task['width_mm']):.2f},{float(task['height_mm']):.2f}]; scale={task['scale'][0]}:{task['scale'][1]}"
    if error is not None and 'layout_does_not_fit' in str(error):
        message=str(error)
        if 'outlines_mm=' not in message:message+=suffix
        raise LayoutDoesNotFit(message,diagnostic=diagnostic,alternatives=alternatives) from None
    raise LayoutDoesNotFit('layout_does_not_fit_requested_scale; choose a larger sheet or explicitly change scale'+suffix,
                          diagnostic=diagnostic,alternatives=alternatives)


def _centers_moved(before, after):
    return any(abs(before[name]['center'][i]-after[name]['center'][i])>0.05 for name in before for i in (0,1))


def _aligned(measured):
    """First-angle: top below front, right on the left, sharing the front axes."""
    if set(measured)!={'front','top','right'}:return False
    front,top,right=(measured[name]['center'] for name in ('front','top','right'))
    return right[0]<front[0]-5 and top[1]<front[1]-5 and abs(top[0]-front[0])<2 and abs(right[1]-front[1])<2


def _boxes_pass(measured, frame, reserved):
    """Same frame and overlap predicates as verify_view_layout. Center match is not required."""
    boxes={name:_outline_bounds(item) for name,item in measured.items()}
    if any(view_exceeds_frame(box, frame) for box in boxes.values()):return False
    names=list(boxes)
    for index,name in enumerate(names):
        for other in names[index+1:]:
            if rectangles_overlap(boxes[name], boxes[other]):return False
        for rect in reserved:
            if rectangles_overlap(boxes[name], rect):return False
    return _aligned(measured)


def _remember_positions(task, measured):
    for item in task['drawing_model']['views']:
        item['position_mm']=list(measured[item['id']]['position'])


def _sheet_frame(drawing, task):
    """Frame and title block from the sheet readback verify_view_layout uses."""
    properties=read_member(drawing.GetCurrentSheet(),'GetProperties2')
    width,height=float(properties[5])*1000,float(properties[6])*1000
    if not math.isfinite(width) or not math.isfinite(height) or width<=0 or height<=0:
        width,height=float(task['width_mm']),float(task['height_mm'])
    frame=task.get('frame_bounds_mm', default_frame_mm(width, height))
    reserved=task.get('reserved_rectangles_mm', [default_title_block_mm(width)])
    return frame, reserved


def _settle_auto_layout(drawing, task, views):
    """Move until post-rebuild GetOutline boxes pass the verifier predicates.

    18a718db trusted one anchor and one nudge. The outline verify measured
    could still be the pre-move box, so top/front landed outside the frame
    while A2 at 1:10 still fit in the slack. Stop when the boxes are inside
    the sheet frame and clear of the title block. Do not keep nudging a
    placement that already passes. The requested scale is never replaced.
    """
    from .auto_layout import first_angle_layout
    frame,reserved=_sheet_frame(drawing, task)
    previous=None
    center_requested=bool(task.get('center_views'))
    for _ in range(12):
        measured=_measure_views(views)
        if previous is not None and not _centers_moved(previous, measured) and not _boxes_pass(measured,frame,reserved):
            caught=measured
            for _catch in range(3):
                if not read_member(drawing,'EditRebuild3'):raise RuntimeError('drawing layout rebuild failed')
                caught=_measure_views(views)
                if _centers_moved(previous, caught):
                    measured=caught
                    break
            else:_refuse_measured(caught, task=task)
        if _boxes_pass(measured, frame, reserved) and not center_requested:
            if not read_member(drawing,'EditRebuild3'):raise RuntimeError('drawing layout rebuild failed')
            confirmed=_measure_views(views)
            if _boxes_pass(confirmed, frame, reserved):
                _remember_positions(task, confirmed)
                return
            measured=confirmed
        try:
            centers=first_angle_layout(task['width_mm'], task['height_mm'], {name:item['size'] for name,item in measured.items()},
                                       centered=bool(task.get('center_views')))
        except ValueError as error:
            _refuse_measured(measured, error, task)
        previous=measured
        _apply_outline_centers(task, views, centers, measured)
        center_requested=False
        if not read_member(drawing,'EditRebuild3'):raise RuntimeError('drawing layout rebuild failed')
    _refuse_measured(_measure_views(views), task=task)


def lock_view_layout(drawing,task,views):
    # SW can change sheet scale when inserting the first view. Enforce the
    # requested ratio here and do not replace it when a view misses the frame.
    if not drawing.GetCurrentSheet().SetScale(*task['scale'],True,True):
        raise RuntimeError('drawing sheet scale update failed')
    if task.get('auto_layout'):
        for view in views.values():view.UseSheetScale=1
        if not read_member(drawing,'EditRebuild3'):raise RuntimeError('view size rebuild failed')
        _settle_auto_layout(drawing,task,views)
    else:
        for item in task['drawing_model']['views']:
            _write_position(views[item['id']], item['position_mm'])
        if not read_member(drawing,'EditRebuild3'):raise RuntimeError('drawing layout rebuild failed')
    try:
        return verify_view_layout(drawing,task,views)
    except RuntimeError as error:
        # Placement could not keep the outline inside. Say so with the boxes,
        # instead of reporting a bad place as blocked_view_exceeds_frame.
        if task.get('auto_layout') and ('exceeds frame' in str(error) or 'layout overlap' in str(error)):
            _refuse_measured(_measure_views(views), task=task)
        raise


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
