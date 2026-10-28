"""Legacy Chutu template region candidates; never manufacturing approval."""
from collections import Counter
from ezdxf import bbox

DEFAULT_RULES = {
    'bom': {'x_min': 38000., 'x_max': 41400., 'y_min': 2000., 'y_max': 6400., 'layers': ['0']},
    'fang': {'geom_x_min': 43600., 'text_x_min': 43000., 'y_min': 3700.},
    'title': {'layers': ['细线', '细实线'], 'y_max': 3700.},
    'view': {'x_min': 41300., 'y_min': 3700.},
}


def _bounds(entity):
    ext = bbox.extents([entity], fast=True)
    if not ext.has_data: return None
    return (ext.extmin.x, ext.extmin.y, ext.extmax.x, ext.extmax.y)


def classify(entity, rules=DEFAULT_RULES):
    layer = entity.dxf.get('layer', '0'); kind = entity.dxftype()
    if layer in ('三视图标注', 'VIEW_DIM', 'overall_dims'): return 'view'
    box = _bounds(entity)
    if kind == 'LWPOLYLINE' and box and box[2]-box[0]>3000 and box[3]-box[1]>2000: return 'frame'
    if layer in rules['title']['layers'] and (box is None or box[3] <= rules['title']['y_max']): return 'title'
    bx = rules['bom']['x_min']
    if box and box[2] < bx: return 'banjin'
    def in_bom(x, y, right=None):
        b = rules['bom']
        return (b['y_min'] <= y <= b['y_max'] and x >= b['x_min'] and
                (x < b['x_max'] if layer in b['layers'] else right is not None and right <= b['x_max']))
    if kind in ('TEXT','MTEXT'):
        try: x, y = float(entity.dxf.insert[0]), float(entity.dxf.insert[1])
        except (AttributeError, TypeError, IndexError, ValueError): return 'extra'
        if x < bx: return 'banjin'
        if in_bom(x,y): return 'bom'
        if x >= rules['fang']['text_x_min']: return 'fang'
        if x >= rules['view']['x_min'] and y >= rules['view']['y_min']: return 'view'
        return 'extra'
    if box:
        x,y,right,_ = box
        if (layer.startswith('SW') or layer in ('中心线','虚线','粗实线','细实线','轮廓线')) and x >= rules['view']['x_min'] and y >= rules['view']['y_min']: return 'view'
        if x >= rules['view']['x_min'] and y >= rules['view']['y_min']:
            if x >= rules['fang']['geom_x_min'] and y >= rules['fang']['y_min']: return 'fang'
            if in_bom(x,y,right) and right < rules['view']['x_min']: return 'bom'
            return 'view'
        if in_bom(x,y,right): return 'bom'
        if x >= rules['fang']['geom_x_min'] and y >= rules['fang']['y_min']: return 'fang'
    return 'extra'


def inspect_regions(doc):
    """Count candidates; coordinate rules are valid only for matching templates."""
    result=Counter(classify(e) for e in doc.modelspace())
    return {'counts':dict(sorted(result.items())), 'status':'candidate_only',
            'rules_scope':'legacy_template_coordinates', 'production_approved':False}
