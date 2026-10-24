"""Read-only, redacted batch evidence export; no reconstruction of a native pass."""
import hashlib,json,zipfile,re
from pathlib import Path


def collect_acceptance(batch_root):
    root=Path(batch_root).resolve()
    summary=json.loads((root/'summary.json').read_text(encoding='utf-8'))
    source=json.loads((root/'source-manifest.json').read_text(encoding='utf-8')) if (root/'source-manifest.json').is_file() else {'status':'missing_source_fingerprint'}
    raw_code=source.get('code_sha256',{})
    code={name:sha for name,sha in raw_code.items() if isinstance(name,str) and not Path(name).is_absolute() and '..' not in Path(name).parts and ':' not in name and '\\' not in name and isinstance(sha,str) and re.fullmatch(r'[0-9a-f]{64}',sha)}
    signature=source.get('request_and_code_signature')
    source={'code_sha256':code,'request_and_code_signature':signature if isinstance(signature,str) and re.fullmatch(r'[0-9a-f]{64}',signature) else None}
    batch_errors=[]
    if not code or source['request_and_code_signature'] is None:batch_errors.append('missing_source_fingerprint')
    if not summary.get('results'):batch_errors.append('empty_batch_results')
    reports=[]
    for row in summary['results']:
        report={key:row.get(key) for key in ('id','status','modeling','cleanup','returncode','exit_class','worker_may_be_running')}
        errors=[];checks=[]
        for relative,expected in row.get('artifacts',{}).items():
            path=(root/relative).resolve()
            if not path.is_relative_to(root) or not path.is_file():
                errors.append('missing_or_external_artifact');continue
            actual=hashlib.sha256(path.read_bytes()).hexdigest()
            checks.append({'name':path.name,'sha256':actual,'matches':actual==expected})
            if actual!=expected:errors.append('artifact_checksum_mismatch')
        if row.get('status')=='completed':
            if row.get('returncode')!=0 or row.get('modeling')!='saved_reopened' or row.get('cleanup')!='owned_document_closed':
                errors.append('completed_status_contradicts_phase_evidence')
            if not checks:errors.append('completed_without_artifacts')
        report.update(artifact_checks=checks,evidence_errors=errors,
            evidence_consistent=not errors,native_acceptance='pending_windows_validation')
        reports.append(report)
    return {'schema_version':1,'source_fingerprint':source,'results':reports,
        'evidence_errors':batch_errors,
        'evidence_consistent':not batch_errors and all(r['evidence_consistent'] for r in reports),
        'scope':'revalidated reported worker evidence, not independent model inspection',
        'manufacturing_approved':False,'native_acceptance':'pending_windows_validation',
        'redaction':'no absolute paths, source CAD or binary artifacts included'}


def export_acceptance(batch_root,destination):
    report=collect_acceptance(batch_root)
    root=Path(destination).resolve();root.mkdir(parents=True,exist_ok=False)
    path=root/'acceptance.json';path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    (root/'SHA256.json').write_text(json.dumps({'acceptance.json':digest},indent=2))
    with zipfile.ZipFile(root/'gork-acceptance.zip','x',zipfile.ZIP_DEFLATED) as z:
        z.write(path,path.name);z.write(root/'SHA256.json','SHA256.json')
    return {'status':'review_required','package':str(root/'gork-acceptance.zip'),'evidence_consistent':report['evidence_consistent']}
