"""Stable snapshot-to-binding wizard API reusing existing mapping candidates."""
from copy import deepcopy
from ql5050px.intelligent_scan import identity
from ql5050px.automatic_mapping import map_parameters
from design_review.impact import review_digest


def suggest_bindings(snapshot,parameters):
    database={'documents':{}};pending=[]
    for original in snapshot.get('documents',[]):
        row=deepcopy(original);key=identity(row['path'],row['configuration'])
        for dim in row.get('dimensions',[]):
            if dim.get('unit')=='SI':
                kind=dim.get('dimension_kind')
                if kind=='length':dim.update(value=dim['value_si']*1000,unit='mm')
                elif kind=='angle':
                    import math
                    dim.update(value=math.degrees(dim['value_si']),unit='deg')
                else:pending.append({'document_id':key,'dimension':dim['name'],'reason':'SI dimension kind needs confirmation'})
        if key in database['documents'] and database['documents'][key]!=row:raise ValueError('conflicting snapshot document')
        database['documents'][key]=row
    report=map_parameters(database,parameters)
    report.update(snapshot_sha256=review_digest(snapshot),unit_confirmation=pending,
        source_machine=snapshot.get('machine'),native_write_allowed=False)
    report['report_sha256']=review_digest(report);return report


def approve_binding(report,approval):
    matches=[c for row in report['mappings'] if row['parameter']==approval['parameter']
        for c in row['candidates'] if c['document_id']==approval['document_id'] and c['dimension']==approval['dimension']]
    if len(matches)!=1 or report.get('dependency_cycles'):raise ValueError('unique acyclic binding candidate required')
    candidate=matches[0]
    payload=deepcopy(report);declared=payload.pop('report_sha256')
    if approval.get('report_sha256')!=declared or review_digest(payload)!=declared:raise ValueError('snapshot candidate report changed')
    if approval.get('reviewed') is not True or not approval.get('source'):raise ValueError('explicit sourced binding approval required')
    if candidate.get('measured_value') is None:raise ValueError('unmeasured/unknown-unit candidate cannot be approved')
    from .calculations import number
    number(candidate['measured_value'])
    role=approval['role']
    if role not in {'adjustable','interface','fixed','purchased'}:raise ValueError('explicit design role required')
    if candidate.get('protected') and role=='adjustable':raise ValueError('fixed/purchased component cannot be made adjustable')
    bounds=approval.get('allowed_range')
    if role=='adjustable':
        from .calculations import number
        if not isinstance(bounds,list) or len(bounds)!=2 or number(bounds[0])>number(bounds[1]):raise ValueError('reviewed allowed range required')
    return {'parameter':approval['parameter'],'document_id':candidate['document_id'],'document':candidate['model_path'],
        'configuration':candidate['configuration'],'feature':candidate['feature'],'dimension':candidate['dimension'],
        'unit':candidate['units'],'measured_value':candidate['measured_value'],'role':role,'allowed_range':bounds,
        'source':approval['source'],'review_status':'confirmed','snapshot_sha256':report['snapshot_sha256'],
        'native_write_allowed':False,'approval_record':deepcopy(approval)}
