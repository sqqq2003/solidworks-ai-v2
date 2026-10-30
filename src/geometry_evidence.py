"""Compare explicit geometry observations without authorizing CAD or production."""
from __future__ import annotations

import math
import re

_HASH = re.compile(r'^[0-9a-f]{64}$')
_METRICS = {'body_count':'count','volume_mm3':'mm3',
            'extent_x_mm':'mm','extent_y_mm':'mm','extent_z_mm':'mm'}


def _number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(name + ' must be finite')
    return float(value)


def _validate_snapshot(snapshot):
    if not isinstance(snapshot, dict) or snapshot.get('schema_version') != 1:
        raise ValueError('geometry snapshot schema_version 1 required')
    identity=snapshot.get('identity')
    if not isinstance(identity,dict) or not _HASH.fullmatch(str(identity.get('source_sha256',''))):
        raise ValueError('source baseline SHA256 required')
    if not all(isinstance(identity.get(k),str) and identity[k] for k in ('document_key','configuration')):
        raise ValueError('document and configuration identity required')
    if identity.get('document_confirmed') is not True or identity.get('configuration_confirmed') is not True:
        raise ValueError('unconfirmed document or configuration identity')
    if snapshot.get('rebuilt') not in (True,False,None) or type(snapshot.get('rebuilt')) not in (bool,type(None)):
        raise ValueError('rebuilt must be true, false, or unknown')
    count=snapshot.get('body_count')
    if count is not None and (type(count) is not int or count < 0):
        raise ValueError('body count must be a nonnegative integer or unknown')
    volume=snapshot.get('volume_mm3')
    if volume is not None and _number(volume,'volume_mm3') < 0:
        raise ValueError('negative volume refused')
    bounds=snapshot.get('bounds_mm')
    if bounds is not None:
        if not isinstance(bounds,(list,tuple)) or len(bounds)!=6:
            raise ValueError('bounds require six millimetre coordinates')
        values=[_number(v,'bounds_mm') for v in bounds]
        if any(values[i+3] < values[i] for i in range(3)):
            raise ValueError('bounds are not ordered')
    dims=snapshot.get('dimensions_mm',{})
    if not isinstance(dims,dict):raise ValueError('dimensions must be an object')
    for key,value in dims.items():
        if not isinstance(key,str) or not key:raise ValueError('dimension name required')
        if value is not None:_number(value,'dimension '+key)
    return identity


def _metric(snapshot, field):
    if field.startswith('dimension:'):
        return snapshot.get('dimensions_mm',{}).get(field.partition(':')[2])
    if field.startswith('extent_'):
        bounds=snapshot.get('bounds_mm')
        if bounds is None:return None
        axis={'extent_x_mm':0,'extent_y_mm':1,'extent_z_mm':2}[field]
        return bounds[axis+3]-bounds[axis]
    return snapshot.get(field)


def compare_snapshots(before, after, checks, *, step_id):
    """Check explicit target/delta/invariance tolerances against two observations.

    Bounding boxes may be approximate. A matched check is not manufacturing,
    feature, interface, assembly or SolidWorks validation.
    """
    left=_validate_snapshot(before);right=_validate_snapshot(after)
    if left != right:raise ValueError('snapshot identity or source baseline changed')
    if not isinstance(step_id,str) or not step_id.strip():raise ValueError('step id required')
    if not isinstance(checks,list):raise ValueError('checks must be a list')
    results=[];seen=set()
    for check in checks:
        if not isinstance(check,dict):raise ValueError('check must be an object')
        field=check.get('field');mode=check.get('mode')
        if not isinstance(field,str) or not (field in _METRICS or (field.startswith('dimension:') and field[10:])):
            raise ValueError('unsupported metric')
        expected_unit=_METRICS.get(field,'mm')
        if check.get('unit') != expected_unit:raise ValueError('explicit correct unit required')
        if mode not in {'target','delta','unchanged','changed'}:raise ValueError('unsupported comparison mode')
        if (field,mode) in seen:raise ValueError('duplicate check')
        seen.add((field,mode))
        if 'tolerance' not in check:
            results.append({'field':field,'mode':mode,'status':'unverified','reason':'未提供确认的公差'});continue
        tolerance=_number(check['tolerance'],'tolerance')
        if tolerance < 0:raise ValueError('negative tolerance refused')
        expected=_number(check.get('value'),'expected value') if mode in {'target','delta'} else None
        a=_metric(before,field);b=_metric(after,field)
        if a is None or b is None:
            results.append({'field':field,'mode':mode,'status':'unverified','reason':'缺少前后读回'});continue
        a=_number(a,'before');b=_number(b,'after');delta=b-a
        actual=b if mode=='target' else delta
        target=expected if expected is not None else 0.0
        passed=abs(actual-target)>tolerance if mode=='changed' else abs(actual-target)<=tolerance
        results.append({'field':field,'mode':mode,'unit':expected_unit,'before':a,'after':b,
                        'delta':delta,'expected':expected,'tolerance':tolerance,
                        'status':'observed_consistent' if passed else 'failed'})
    rebuilt=[before.get('rebuilt'),after.get('rebuilt')]
    if False in rebuilt or any(row['status']=='failed' for row in results):status='failed'
    elif not checks or None in rebuilt or any(row['status']=='unverified' for row in results):status='review_required'
    else:status='observations_consistent_pending_engineering'
    return {'schema_version':1,'step_id':step_id,'identity':left,'status':status,
            'before':before,'after':after,'checks':results,
            'geometry_verified':False,'production_approved':False,
            'limitations':['包络可能为近似值，不证明特征形状或配合。','尺寸和公差须由工程人员确认。']}
