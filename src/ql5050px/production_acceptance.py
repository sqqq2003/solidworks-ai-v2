"""Read-only whole-machine checkpoint audit and compact shareable evidence ZIP."""
import json,re,zipfile
from pathlib import Path,PureWindowsPath,PurePosixPath
from .production_review import file_sha256


def audit_production(directory):
    root=Path(directory).resolve()
    checkpoint=json.loads((root/'checkpoint.json').read_text(encoding='utf-8'))
    errors=[];artifacts=[]
    expected=['assembly','drive','checks','drawings']
    stages=[{'name':s.get('name'),'status':s.get('status')} for s in checkpoint.get('stages',[])]
    if [s['name'] for s in stages]!=expected or any(s['status']!='returned' for s in stages):errors.append('incomplete_stage_sequence')
    if checkpoint.get('status')!='outputs_created_review_required':errors.append('transaction_not_completed')
    for name,digest in checkpoint.get('artifact_sha256',{}).items():
        # Parse both OS syntaxes before resolving on this host.
        if not isinstance(name,str) or PurePosixPath(name).root or PureWindowsPath(name).root or PureWindowsPath(name).drive or '\\' in name or '..' in PurePosixPath(name).parts:
            errors.append('external_artifact');continue
        path=(root/name).resolve()
        if not path.is_relative_to(root) or not path.is_file():errors.append('missing_or_external_artifact');continue
        actual=file_sha256(path);matches=actual==digest
        artifacts.append({'name':name,'sha256':actual,'matches':matches})
        if not matches:errors.append('artifact_checksum_mismatch')
    if not artifacts:errors.append('missing_artifacts')
    # Every final model and drawing receipt must refer to a checked artifact.
    checks={str((root/a['name']).resolve()):a['matches'] for a in artifacts}
    if not checkpoint.get('documents'):errors.append('missing_final_models')
    if not checkpoint.get('drawings',{}).get('results'):errors.append('missing_drawing_receipts')
    suffixes={Path(a['name']).suffix.lower() for a in artifacts}
    if not {'.sldasm','.slddrw','.csv'}<=suffixes:errors.append('missing_manufacturing_deliverables')
    receipts=list(checkpoint.get('documents',{}).values())
    receipts+=checkpoint.get('drawings',{}).get('results',[])
    if not receipts:errors.append('missing_final_receipts')
    for item in receipts:
        for key in ('path','flat_dxf'):
            if item.get(key) and not checks.get(str(Path(item[key]).resolve()),False):errors.append('receipt_artifact_not_verified')
        if not item.get('path'):errors.append('receipt_missing_path')
    findings=checkpoint.get('mechanical_findings',{})
    native_reported=findings.get('simulated_only') is False
    if not native_reported:errors.append('missing_native_check_evidence')
    digest=checkpoint.get('review_sha256')
    if not isinstance(digest,str) or not re.fullmatch('[a-f0-9]{64}',digest):errors.append('missing_review_digest')
    input_review=checkpoint.get('input_verification',{})
    if input_review.get('status')!='declared_files_verified':errors.append('unsealed_inputs')
    from drawing_review import inspect_drawing_batch
    visual=inspect_drawing_batch(root)
    return {'schema_version':1,'review_sha256':digest if isinstance(digest,str) and re.fullmatch('[a-f0-9]{64}',digest) else None,
        'status':'review_required','reported_status':checkpoint.get('status'),'stages':stages,
        'artifact_checks':artifacts,'evidence_errors':sorted(set(errors)),
        'execution_evidence_complete':not errors,
        'drawing_visual_acceptance':visual,'drawing_delivery_accepted':visual['delivery_accepted'],
        'delivery_accepted':False,
        'mechanical_findings':{'native_reported':native_reported,'mate_records':len(findings.get('mates',[])),
            'interference_records':len(findings.get('interference',[])),'motion_samples':len(findings.get('motion',[]))},
        'scope':'reported stages and file integrity; no independent CAD inspection or mechanical approval',
        'native_acceptance':'pending_windows_validation','process_exit':'pending_external_observation',
        'manufacturing_approved':False,'includes_cad_binaries':False}


def export_production_acceptance(directory,destination):
    report=audit_production(directory)
    out=Path(destination).resolve();out.mkdir(parents=True,exist_ok=False)
    document=out/'production-acceptance.json'
    document.write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    (out/'SHA256.json').write_text(json.dumps({document.name:file_sha256(document)},indent=2),encoding='utf-8')
    archive=out/'gork-production-acceptance.zip'
    with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED) as z:
        z.write(document,document.name);z.write(out/'SHA256.json','SHA256.json')
    return {'status':'review_required','package':str(archive),'execution_evidence_complete':report['execution_evidence_complete'],
        'evidence_errors':report['evidence_errors'],'native_acceptance':'pending_windows_validation'}
