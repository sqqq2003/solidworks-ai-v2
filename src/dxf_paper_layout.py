"""Explicit paper-space partitions; model geometry and text stay unchanged."""
import math
from ezdxf import bbox


def add_partitioned_layout(doc, groups, cells, *, name='SWAI_A3', page_size=(420,297),
                           layer_prefix='SWAI'):
    """Add paper-space viewports for caller-reviewed model-entity groups.

    Each model entity must occur exactly once, including any hidden frame.
    Cells select visible groups; omitted groups remain in model space but are
    frozen in every viewport. Layer names change to isolate partitions.
    This is a presentation operation, never engineering approval.
    """
    if not isinstance(layer_prefix,str) or not layer_prefix or any(c not in
            'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in layer_prefix):
        raise ValueError('simple partition layer prefix required')
    if (len(page_size)!=2 or not all(math.isfinite(x) and x>0 for x in page_size)):
        raise ValueError('positive finite page dimensions required')
    if name in doc.layouts or not groups or not cells or set(cells)-set(groups):
        raise ValueError('new layout and explicit nonempty group/cell mapping required')
    expected={e.dxf.handle for e in doc.modelspace()}
    if any(e.doc is not doc for entities in groups.values() for e in entities):
        raise ValueError('partition contains entities from another document')
    handles=[e.dxf.handle for entities in groups.values() for e in entities]
    if len(set(handles)) != len(handles) or set(handles) != expected:
        raise ValueError('every model entity must belong to exactly one group')
    rectangles=[]
    extents={}
    for key, cell in cells.items():
        if len(cell)!=4 or not all(math.isfinite(x) for x in cell):
            raise ValueError('finite paper-space cell required')
        x0,y0,x1,y1=cell
        if not (0<=x0<x1<=page_size[0] and 0<=y0<y1<=page_size[1]):
            raise ValueError('cell must fit declared page dimensions')
        for other in rectangles:
            if min(x1,other[2])>max(x0,other[0]) and min(y1,other[3])>max(y0,other[1]):
                raise ValueError('paper-space cells overlap')
        rectangles.append(cell)
        extent=bbox.extents(groups[key])
        if not extent.has_data or min(extent.size.x,extent.size.y)<=0:
            raise ValueError('group has no usable 2D extent: '+key)
        extents[key]=extent
    # Resolve layer definitions before the first mutation.
    layer_specs={}
    for key, entities in groups.items():
        for e in entities:
            pair=(key,e.dxf.layer)
            if pair not in layer_specs:
                layer_name=f'{layer_prefix}_{len(layer_specs):03d}'
                if layer_name in doc.layers:
                    raise ValueError('reserved paper partition layer already exists')
                attrs=doc.layers.get(e.dxf.layer).dxf.all_existing_dxf_attribs().copy()
                for field in ('handle','owner','name'):
                    attrs.pop(field,None)
                layer_specs[pair]=(layer_name,attrs)
    for layer_name,attrs in layer_specs.values():
        doc.layers.new(layer_name,dxfattribs=attrs)
    layers_by_group={key:set() for key in groups}
    for key, entities in groups.items():
        for e in entities:
            layer_name=layer_specs[(key,e.dxf.layer)][0]
            e.dxf.layer=layer_name
            layers_by_group[key].add(layer_name)
    paper=doc.layouts.new(name)
    paper.page_setup(size=page_size,margins=(0,0,0,0),units='mm')
    if 'SWAI_VIEWPORTS' not in doc.layers:
        doc.layers.new('SWAI_VIEWPORTS',dxfattribs={'plot':0,'color':7})
    records=[]
    for key,(x0,y0,x1,y1) in cells.items():
        extent=extents[key];width,height=x1-x0,y1-y0
        scale=min(width/extent.size.x,height/extent.size.y)/1.06
        viewport=paper.add_viewport(center=((x0+x1)/2,(y0+y1)/2),size=(width,height),
            view_center_point=(extent.center.x,extent.center.y),view_height=height/scale,
            dxfattribs={'layer':'SWAI_VIEWPORTS'})
        for other,layer_names in layers_by_group.items():
            if other!=key:
                for layer_name in layer_names:
                    viewport.freeze(layer_name)
        records.append({'group':key,'cell_mm':[x0,y0,x1,y1],
                        'display_scale':scale,'viewport_handle':viewport.dxf.handle,
                        'entity_count':len(groups[key])})
    doc.layouts.set_active_layout(name)
    paper.set_plot_type(5)  # Layout; no extents-based clipping of model regions.
    return paper,{'layout':name,'page_mm':list(page_size),'viewports':records,
                  'model_geometry_transformed':False,'production_approved':False}
