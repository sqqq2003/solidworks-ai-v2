"""Read-only flat-pattern dimensional comparison; never approves production."""
import hashlib,math
from pathlib import Path


def flat_dimensions(path):
    import ezdxf
    from ezdxf import bbox
    path=Path(path);doc=ezdxf.readfile(path)
    if doc.units!=4:raise ValueError('explicit millimetre DXF units required')
    entities=list(doc.modelspace())
    if any(e.dxftype() in ('INSERT','SPLINE','ELLIPSE') for e in entities):
        raise ValueError('complex DXF requires geometry-specific comparison')
    geometry=[e for e in entities if e.dxftype() in ('LINE','ARC','CIRCLE','LWPOLYLINE','POLYLINE')]
    ext=bbox.extents(geometry)
    if not ext.has_data:raise ValueError('no DXF geometry')
    lo,hi=ext.extmin,ext.extmax
    return {'path':str(path.resolve()),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
        'units':'mm','size':[hi.x-lo.x,hi.y-lo.y],
        'holes':[{'x':e.dxf.center.x-lo.x,'y':e.dxf.center.y-lo.y,'diameter':2*e.dxf.radius} for e in entities if e.dxftype()=='CIRCLE']}


def compare_flat(reference,actual,*,numerical_tolerance_mm):
    tolerance=float(numerical_tolerance_mm)
    if not math.isfinite(tolerance) or tolerance<=0:raise ValueError('explicit positive numerical tolerance required')
    ref=flat_dimensions(reference);got=flat_dimensions(actual)
    size_ok=all(abs(a-b)<=tolerance for a,b in zip(ref['size'],got['size']))
    width,height=ref['size'];matches=[]
    if size_ok and len(ref['holes'])==len(got['holes']):
        for label,flipx,flipy in [('translation',False,False),('face_flip_x',True,False),('face_flip_y',False,True),('rotation_180',True,True)]:
            remaining=list(got['holes'])
            for h in ref['holes']:
                x=width-h['x'] if flipx else h['x'];y=height-h['y'] if flipy else h['y']
                candidates=[i for i,g in enumerate(remaining) if max(abs(x-g['x']),abs(y-g['y']),abs(h['diameter']-g['diameter']))<=tolerance]
                if not candidates:break
                remaining.pop(candidates[0])
            else:
                if not remaining:matches.append(label)
    return {'scope':'flat_envelope_and_circular_holes_only','reference':ref,'actual':got,
        'numerical_tolerance_mm':tolerance,'manufacturing_tolerance_confirmed':False,
        'envelope_delta_mm':[a-b for a,b in zip(got['size'],ref['size'])],
        'size_matches':size_ok,'hole_count_matches':len(ref['holes'])==len(got['holes']),
        'matching_coordinate_transforms':matches,
        'status':'dimensions_match_datum_review_required' if matches else 'dimension_mismatch',
        'mechanical_acceptance':'unverified','manufacturing_approved':False,
        'not_checked':['arcs_and_full_contour_equivalence','noncircular_holes','bending_direction','material','production_tolerances','engineering_signoff']}
