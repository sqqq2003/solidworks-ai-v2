"""Persistent plan/review/execution handoff over existing design and native modules."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

from design_review import record_approval
from design_review.impact import review_digest
from unified_project import build_release

ROOT = Path(__file__).resolve().parents[1]
CODE_ROOTS = ('src', 'work', 'feature_tree', 'geometry_ir', 'dependency_engine', 'dxf_extract', 'offline_verify')


def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''): h.update(block)
    return h.hexdigest()


def read_json(path):
    def pairs(rows):
        result = {}
        for key, value in rows:
            if key in result: raise ValueError('duplicate JSON key: ' + key)
            result[key] = value
        return result
    return json.loads(Path(path).read_text(encoding='utf-8-sig'), object_pairs_hook=pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError('nonfinite JSON: '+value)))


def write_new(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def code_hashes():
    paths = list(ROOT.glob('*.py'))
    for folder in CODE_ROOTS: paths.extend((ROOT / folder).rglob('*.py'))
    return {p.relative_to(ROOT).as_posix(): file_hash(p) for p in sorted(paths) if '__pycache__' not in p.parts}


def source_files(request):
    roller = request.get('roller', {})
    paths = {roller.get('source_document')}
    paths.update(row.get('document') for row in roller.get('mappings', {}).get('parameters', []))
    return sorted({str(Path(p).expanduser().resolve()) for p in paths if isinstance(p, str) and p})


def prepare_workflow(request, destination):
    """Generate existing unified plans and bind their bytes, without starting CAD."""
    root = Path(destination).resolve()
    root.mkdir(parents=True, exist_ok=False)
    request = deepcopy(request)
    plan = build_release(request, root / 'planning')
    impact = plan.get('stages', {}).get('roller_impact')
    source = {}
    pending = []
    for path in source_files(request):
        try:
            if Path(path).stat().st_size <= 0: raise ValueError('empty source')
            source[path] = file_hash(path)
        except (OSError, ValueError): pending.append('source unavailable: ' + path)
    if not source: pending.append('no real model source available')
    if not impact or not impact.get('review_ready'): pending.append('impact review or confirmed mappings incomplete')
    if plan['status'] == 'failed': pending.append('upstream planning failed')
    files = {p.relative_to(root).as_posix(): file_hash(p) for p in sorted((root/'planning').rglob('*')) if p.is_file()}
    manifest = {'schema_version': 1, 'request_sha256': review_digest(request),
                'source_sha256': source, 'planning_files': files, 'code_sha256': code_hashes(),
                'review_sha256': impact.get('review_sha256') if impact else None,
                'pending': pending, 'cad_executed': False, 'native_write_allowed': False}
    manifest['workspace_id'] = review_digest(manifest)
    write_new(root/'workflow.json', manifest)
    return workflow_status(root)


def verify_workspace(root):
    root = Path(root).resolve(strict=True)
    manifest = read_json(root/'workflow.json')
    payload = dict(manifest); identity = payload.pop('workspace_id', None)
    if manifest.get('schema_version') != 1 or review_digest(payload) != identity:
        raise ValueError('workspace manifest changed or unsupported')
    if code_hashes() != manifest['code_sha256']: raise ValueError('implementation changed; prepare and review again')
    for relative, sha in manifest['planning_files'].items():
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or file_hash(path) != sha:
            raise ValueError('planning artifacts changed: ' + relative)
    request = read_json(root/'planning/request.json')
    if review_digest(request) != manifest['request_sha256']: raise ValueError('request changed')
    for path, sha in manifest['source_sha256'].items():
        if file_hash(path) != sha: raise ValueError('original model changed since planning: ' + path)
    plan = read_json(root/'planning/release-result.json')
    return root, manifest, request, plan


def approve_workflow(root, *, reviewer, review_sha256):
    root, manifest, request, plan = verify_workspace(root)
    if manifest['pending']: raise ValueError('resolve pending inputs before approval')
    approval = record_approval(plan['stages']['roller_impact'], reviewer=reviewer, review_sha256=review_sha256)
    approval.update(workspace_id=manifest['workspace_id'], source_sha256=manifest['source_sha256'])
    approval['approval_sha256'] = review_digest(approval)
    write_new(root/'approval.json', approval)
    return workflow_status(root)


def checked_approval(root, manifest, plan, expected=None):
    approval = read_json(root/'approval.json')
    payload = dict(approval); declared = payload.pop('approval_sha256', None)
    if review_digest(payload) != declared or (expected is not None and expected != declared):
        raise ValueError('approval digest changed')
    if approval.get('workspace_id') != manifest['workspace_id'] or approval.get('source_sha256') != manifest['source_sha256']:
        raise ValueError('approval does not belong to this workspace/model baseline')
    record_approval(plan['stages']['roller_impact'], reviewer=approval['reviewer'], review_sha256=approval['review_sha256'])
    return approval


def workflow_status(root):
    root, manifest, request, plan = verify_workspace(root)
    phase = 'review_required'
    if manifest['pending']: phase = 'inputs_required'
    elif (root/'approval.json').exists():
        checked_approval(root, manifest, plan); phase = 'review_recorded'
    if (root/'execution-claim.json').exists(): phase = 'execution_attempted_requires_review'
    return {'schema_version': 1, 'status': 'failed' if plan['status']=='failed' else 'review_required',
            'phase': phase, 'workspace': str(root), 'workspace_id': manifest['workspace_id'],
            'review_sha256': manifest['review_sha256'], 'pending': manifest['pending'],
            'approval_sha256': read_json(root/'approval.json').get('approval_sha256') if (root/'approval.json').exists() else None,
            'execution_report': str(root/'execution.json') if (root/'execution.json').exists() else None,
            'next_action': 'review_execution_evidence' if (root/'execution-claim.json').exists() else
                           'supply_real_model_and_confirm_mapping' if manifest['pending'] else
                           'explicit_windows_execute' if phase=='review_recorded' else 'named_impact_review',
            'native_write_allowed': False, 'manufacturing_approved': False}


def execute_workflow(root, *, sw_exe, approval_sha256):
    """Explicit Windows-only call to the existing isolated roller implementation."""
    root, manifest, request, plan = verify_workspace(root)
    if manifest['pending']: raise ValueError('workspace is blocked')
    approval = checked_approval(root, manifest, plan, approval_sha256)
    if sys.platform != 'win32': raise RuntimeError('native execution requires Windows; cloud can prepare/review/audit')
    executable = Path(sw_exe).expanduser().resolve(strict=True)
    if not executable.is_file() or executable.name.casefold() != 'sldworks.exe': raise ValueError('installed SLDWORKS.exe required')
    # Permanent exclusive claim: never silently rerun an uncertain native attempt.
    write_new(root/'execution-claim.json', {'workspace_id': manifest['workspace_id'],
              'approval_sha256': approval['approval_sha256'], 'sw_exe': str(executable)})
    from roller_variant.native import run_native
    try:
        report = run_native(request['roller'], root/'native-output', executable)
    except Exception as exc:
        report = {'status': 'failed', 'error': type(exc).__name__+': '+str(exc),
                  'recovery': 'preserve_session_and_work_copy; do not repeat this workspace'}
    report.update(workspace_id=manifest['workspace_id'], approval_sha256=approval['approval_sha256'],
                  manufacturing_approved=False, independent_engineering_review_required=True)
    write_new(root/'execution.json', report)
    return report
