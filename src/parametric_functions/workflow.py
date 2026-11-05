"""Immutable formula/mapping/inspection review over existing approval contracts."""
from copy import deepcopy
import math
import os
from pathlib import Path

from cad_checkpoint import digest_file
from drawing_review import atomic_json
from design_review.impact import analyze_impact, record_approval, review_digest
from project_delivery import code_hashes, read_json
from sw_api.mapping import load_mappings
from parametric_workspace import _digest


def checked_preview(preview):
    payload={k:v for k,v in preview.items() if k!='review_sha256'}
    if _digest(payload)!=preview.get('review_sha256'):raise ValueError('parameter preview changed')
    source=preview['source_spec']
    if digest_file(source['path'])!=source['sha256']:raise ValueError('rules changed; recalculate')
    from parametric_workspace import preview_parameters
    inputs={k:v for k,v in preview.get('function_inputs',{}).items() if k not in {'length','width','height'}}
    recalculated=preview_parameters(**preview['target_dimensions_mm'],spec_path=source['path'],input_values=inputs)
    if _digest(recalculated)!=_digest(preview):raise ValueError('preview differs from source rules and inputs; recalculate')
    if preview['plan'].get('conflicts'):raise ValueError('resolve function constraints before native planning')
    return preview['plan']


def identity(path):return os.path.normcase(str(Path(path).expanduser().resolve()))


def inspect_digest(report):
    return review_digest({k:v for k,v in report.items() if k!='inspection_sha256'})


def build_edit_plan(preview, mapping_payload, inspection):
    plan=checked_preview(preview)
    if inspection.get('inspection_sha256')!=inspect_digest(inspection):raise ValueError('inspection record changed')
    if inspection.get('scope')!='native_dimension_snapshot':raise ValueError('native dimension snapshot required')
    source=inspection['source_document'];source_hash=inspection['source_sha256']
    if digest_file(source)!=source_hash:raise ValueError('source model changed since inspection')
    rows=load_mappings(mapping_payload)
    if not rows or len(rows)>64:raise ValueError('1..64 explicit dimension bindings required')
    inventory=inspection['inventory'];measurements={d['name']:d for d in inspection['dimensions']}
    if len(measurements)!=len(inspection['dimensions']):raise ValueError('duplicate inspected dimensions')
    features={r['name'] for r in inventory['features']}
    parameters=plan['parameter_register'];values=plan['values_mm']
    changes=[];intent={};pending=[];physical=set()
    for name,row in parameters.items():
        intent[name]={'role':'interface' if row.get('preserve_interface') else 'adjustable',
                      'review_status':'confirmed','source':row.get('source') or 'explicit parameter plan','unit':'mm'}
    for row in rows:
        if row.parameter not in parameters:raise ValueError('unknown mapped parameter: '+row.parameter)
        if row.status!='confirmed' or identity(row.document)!=identity(source) or row.configuration!=inspection['configuration']:
            raise ValueError('confirmed same-part/same-configuration bindings required')
        if row.unit not in {'mm','m'}:raise ValueError('native bindings currently support linear mm/m dimensions')
        if row.feature not in features or not row.dimension or row.feature not in row.dimension.split('@')[1:]:
            raise ValueError('binding feature differs from native dimension owner')
        if row.dimension in physical:raise ValueError('duplicate physical dimension target')
        physical.add(row.dimension)
        measured=measurements.get(row.dimension)
        if not measured or measured.get('unit')!='mm' or measured['feature']!=row.feature:
            raise ValueError('dimension absent from native inspection')
        value=values.get(row.parameter);unit=parameters[row.parameter].get('unit')
        if value is None:pending.append(row.parameter);continue
        if unit not in {'mm','m'}:raise ValueError('a length binding requires a length formula')
        target=float(value)*(1000 if unit=='m' else 1)
        before=float(measured['value_mm'])
        if not all(math.isfinite(v) and v>0 for v in (before,target)):raise ValueError('positive finite native lengths required')
        bounds=tuple(float(v)*(1000 if row.unit=='m' else 1) for v in row.allowed_range)
        if bounds[0]<=0 or not bounds[0]<=before<=bounds[1] or not bounds[0]<=target<=bounds[1]:
            raise ValueError('baseline/target outside reviewed mapping range: '+row.parameter)
        protected=row.component_kind!='editable' or bool(parameters[row.parameter].get('preserve_interface'))
        if not protected and measured.get('editable') is not True:raise ValueError('mapped target is not an editable driving length')
        role='interface' if parameters[row.parameter].get('preserve_interface') else row.component_kind if protected else 'adjustable'
        intent[row.parameter].update(role=role,source=row.source,allowed_range=list(bounds))
        changes.append({'parameter':row.parameter,'document':source,'configuration':row.configuration,
                        'feature':row.feature,'dimension':row.dimension,'unit':'mm',
                        'before_mm':before,'after_mm':target,'allowed_range':list(bounds),
                        'source':row.source,'protected':protected})
    protected_names={n for n,r in intent.items() if r['role'] in {'interface','fixed','purchased'}}
    if not protected_names<={r.parameter for r in rows}:raise ValueError('bind every declared protected interface before execution')
    if pending:raise ValueError('mapped formula values unresolved: '+', '.join(pending))
    result={'schema_version':1,'kind':'reviewed_parameter_edit','source_document':source,
            'source_sha256':source_hash,'configuration':inspection['configuration'],
            'expected_inspection_sha256':inspection['inspection_sha256'],
            'changes':changes,'unmapped_computed_parameters':sorted(set(parameters)-{r.parameter for r in rows}),
            'parameter_order':plan.get('parameter_order',list(parameters)),
            'status':'ready_for_review','manufacturing_approved':False}
    intentions={'parameters':intent,'dependency_graph':{n:r.get('depends_on',[]) for n,r in parameters.items()}}
    result['design_intentions']=intentions
    result['values_mm']={c['parameter']:c['after_mm'] for c in changes}
    result['parameter_register']={c['parameter']:{'unit':'mm','depends_on':parameters[c['parameter']].get('depends_on',[])} for c in changes}
    impact=analyze_impact(result,intentions)
    return result,impact


def prepare_edit_workspace(preview, mappings, inspection, destination):
    edit,impact=build_edit_plan(preview,mappings,inspection)
    root=Path(destination).expanduser().resolve();root.mkdir(parents=True,exist_ok=False)
    documents={'preview.json':preview,'mappings.json':mappings,'inspection.json':inspection,
               'edit-plan.json':edit,'impact.json':impact}
    for name,data in documents.items():atomic_json(root/name,data,exclusive=True)
    manifest={'schema_version':1,'kind':'parametric_execution_workspace',
              'files':{n:digest_file(root/n) for n in documents},'code_sha256':code_hashes(),
              'source_document':edit['source_document'],'source_sha256':edit['source_sha256'],
              'review_sha256':impact['review_sha256'],'review_ready':impact['review_ready']}
    manifest['workspace_id']=review_digest(manifest)
    atomic_json(root/'workspace.json',manifest,exclusive=True)
    return inspect_edit_workspace(root)


def verify_edit_workspace(directory):
    root=Path(directory).expanduser().resolve(strict=True);manifest=read_json(root/'workspace.json')
    payload=dict(manifest);workspace_id=payload.pop('workspace_id',None)
    if manifest.get('kind')!='parametric_execution_workspace' or review_digest(payload)!=workspace_id:
        raise ValueError('execution workspace manifest changed')
    expected={'preview.json','mappings.json','inspection.json','edit-plan.json','impact.json'}
    if set(manifest['files'])!=expected:raise ValueError('workspace file set changed')
    for name,sha in manifest['files'].items():
        if (root/name).is_symlink() or digest_file(root/name)!=sha:raise ValueError('workspace artifact changed: '+name)
    if code_hashes()!=manifest['code_sha256']:raise ValueError('implementation changed; prepare/review again')
    preview,mappings,inspection=(read_json(root/n) for n in ('preview.json','mappings.json','inspection.json'))
    edit,impact=build_edit_plan(preview,mappings,inspection)
    if edit!=read_json(root/'edit-plan.json') or impact!=read_json(root/'impact.json'):
        raise ValueError('derived edit/impact differs; prepare again')
    return root,manifest,edit,impact,inspection


def approve_edit_workspace(directory, *, reviewer, expected_review_sha256):
    root,manifest,edit,impact,inspection=verify_edit_workspace(directory)
    approval=record_approval(impact,reviewer=reviewer,review_sha256=expected_review_sha256)
    approval.update(workspace_id=manifest['workspace_id'],source_sha256=edit['source_sha256'])
    approval['approval_sha256']=review_digest(approval)
    atomic_json(root/'approval.json',approval,exclusive=True)
    return inspect_edit_workspace(root)


def checked_approval(root,manifest,impact,expected=None):
    approval=read_json(root/'approval.json');value=dict(approval);sha=value.pop('approval_sha256',None)
    if review_digest(value)!=sha or (expected is not None and sha!=expected):raise ValueError('approval changed or mismatched')
    if approval.get('workspace_id')!=manifest['workspace_id'] or approval.get('source_sha256')!=manifest['source_sha256']:
        raise ValueError('approval belongs to a different workspace/source')
    record_approval(impact,reviewer=approval['reviewer'],review_sha256=approval['review_sha256'])
    return approval


def inspect_edit_workspace(directory):
    root,manifest,edit,impact,inspection=verify_edit_workspace(directory)
    approval=checked_approval(root,manifest,impact) if (root/'approval.json').exists() else None
    return {'status':'review_required','phase':'review_recorded' if approval else 'ready_for_review' if impact['review_ready'] else 'blocked',
            'workspace':str(root),'workspace_id':manifest['workspace_id'],'review_sha256':impact['review_sha256'],
            'approval_sha256':approval['approval_sha256'] if approval else None,
            'changes':impact['changes'],'protected':impact['protected_readbacks'],'risks':impact['risks'],
            'conflicts':impact['conflicts'],'pending':impact['pending_confirmation'],
            'computed_only':edit['unmapped_computed_parameters'],'simulated_inspection':inspection.get('simulated_only'),
            'native_write_allowed':False,'manufacturing_approved':False}
