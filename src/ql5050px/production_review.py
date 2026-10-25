"""Bind declared local production inputs and implementation bytes to a review."""
from copy import deepcopy
import hashlib
from pathlib import Path
from .production import fingerprint,validate_review


def file_sha256(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
    return digest.hexdigest()


def declared_inputs(plan):
    """Declared CAD/templates only; does not discover hidden SLDASM references."""
    machine=plan['machine_plan'];items={}
    def add(label,value):
        if value:items[label]=str(Path(value).expanduser().resolve())
    for node,spec in machine['assembly_plan']['tree']['catalog'].items():
        for field in ('source_path','template'):add('catalog/'+node+'/'+field,spec.get(field))
        add('catalog/'+node+'/generation_cad',spec.get('generation',{}).get('cad_path'))
    for task in machine['drawing_plan']['tasks']:
        for field in ('template','sheet_format','bom_template'):add(task['id']+'/'+field,task.get(field))
    return items


def code_fingerprint():
    source=Path(__file__).resolve().parent
    paths=list(source.glob('*.py'))
    paths += [source.parent/name for name in ('sw_session.py','sw_owned_launch.py','solidworks_generator.py',
        'turned_part.py','turned_generate.py','part_verification.py','sheet_metal_pipeline.py','sheet_metal_windows.py','sw_math_arrays.py')]
    paths += list((source.parent/'sw_compat').glob('*.py')) + [source.parent/'owned_document_lifetime.py']
    return {str(p.relative_to(source.parent)).replace('\\','/'):file_sha256(p) for p in sorted(paths) if p.is_file()}


def seal_production_review(plan):
    """Local read-only review step. Caller must inspect the returned new digest."""
    validate_review(plan,plan['review_sha256'])
    result=deepcopy(plan);result.pop('review_sha256')
    inputs=declared_inputs(result)
    if not inputs:raise ValueError('no declared production files to bind')
    result['input_review']={'schema_version':1,'scope':'declared_files_only; native Pack-and-Go reference audit still required',
        'files':{label:{'path':path,'sha256':file_sha256(path)} for label,path in inputs.items()},
        'code_sha256':code_fingerprint()}
    result['review_sha256']=fingerprint(result)
    return result


def verify_production_inputs(plan,*,require_seal=False):
    review=plan.get('input_review')
    if review is None:
        if require_seal:raise ValueError('native-production requires review-production input sealing')
        return {'status':'legacy_unsealed','scope':'plan_digest_only'}
    expected=declared_inputs(plan);records=review.get('files',{})
    if set(records)!=set(expected):raise ValueError('reviewed input inventory differs from plan')
    for label,path in expected.items():
        row=records[label]
        if row.get('path')!=path or file_sha256(path)!=row.get('sha256'):
            raise ValueError('production input changed after review: '+label)
    if not review.get('code_sha256') or review['code_sha256']!=code_fingerprint():
        raise ValueError('production implementation changed after review; regenerate review locally')
    return {'status':'declared_files_verified','files':len(records),'scope':review['scope']}
