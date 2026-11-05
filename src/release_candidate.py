"""Reproducible source candidate and Gork matrix using the existing packager."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from project_delivery import file_hash, read_json, write_new

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.append(str(ROOT))
from work.prepare_test_handoff import build_package

CHECKS = [
    ('cloud_regression','offline'), ('desktop_and_api','offline'),
    ('coexisting_instances','native'), ('dwg_analyze','native'),
    ('sheet_rebuild_flat_pattern','native'), ('roller_800_interfaces','native'),
    ('assembly_motion_interference','native'), ('drawings_bom_manufacturing','native'),
    ('save_reopen_references','native'), ('process_exit_and_source_unchanged','native'),
    ('checkpoint_half_edit_restore','native'), ('request_idempotency_and_conflict','native'),
    ('unresolved_session_reconciliation','native'),
    ('drawing_visual_acceptance','native'),('drawing_atomic_evidence','native'),
    ('drawing_dimension_rollback','native'),
    ('modeling_named_bodies_and_features','native'),('modeling_half_build_rollback','native'),
    ('modeling_revision_and_observation','native'),('modeling_body_clearance','native'),
    ('modeling_request_replay_and_quarantine','native'),
    ('parametric_function_units_and_dependencies','offline'),
    ('parametric_generated_feature_part','native'),('parametric_existing_part_batch','native'),
    ('parametric_review_and_request_replay','native'),('parametric_saved_batch_rollback','native')]


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], stderr=subprocess.PIPE).decode().strip()


def build_candidate(root, destination, *, expected_revision=None, source_index=None):
    root = Path(root).resolve(strict=True)
    if source_index is None:
        if Path(git(root, 'rev-parse', '--show-toplevel')).resolve() != root:
            raise ValueError('candidate root must be the repository root')
        revision = git(root, 'rev-parse', 'HEAD')
        if git(root, 'status', '--porcelain', '--untracked-files=no'):
            raise ValueError('tracked source changes must be committed before candidate packaging')
    else:
        if source_index.get('schema_version')!=1 or not isinstance(source_index.get('files'),dict):
            raise ValueError('explicit pinned source index required')
        revision=source_index.get('source_revision','')
    if not re.fullmatch('[0-9a-f]{40}', revision): raise ValueError('full repository revision required')
    if expected_revision is not None and expected_revision != revision: raise ValueError('source revision mismatch')
    destination = Path(destination).resolve()
    if destination.is_relative_to(root): raise ValueError('candidate output must be outside the source repository')
    destination.mkdir(parents=True, exist_ok=False)
    package = build_package(root, destination/'source.zip', revision, source_index=source_index)
    import zipfile
    with zipfile.ZipFile(destination/'source.zip') as bundle:
        handoff = json.loads(bundle.read('HANDOFF.json'))
        # Spot concurrent workspace changes during file collection/copy.
        for name, digest in handoff['files'].items():
            if hashlib.sha256(bundle.read(name)).hexdigest() != digest or file_hash(root/name) != digest:
                raise ValueError('source changed while building candidate: '+name)
    if source_index is None and (git(root,'rev-parse','HEAD') != revision or git(root,'status','--porcelain','--untracked-files=no')):
        raise ValueError('repository changed while building candidate')
    matrix = {'schema_version':1, 'lanes':[{'id':'unified', 'sha':revision,
        'checks':[{'id':name,'scope':scope} for name,scope in CHECKS]}]}
    submission = {'schema_version':1,'results':[
        {'lane':'unified','id':name,'sha':revision,'scope':scope,'status':'review_required',
         'simulated_only': None, 'environment':{}, 'session':{}, 'process_exit_code':None,'artifacts':[]}
        for name,scope in CHECKS]}
    candidate = {'schema_version':1,'source_revision':revision,'package_sha256':package['sha256'],
        'file_count':package['file_count'],'source_manifest_sha256':hashlib.sha256(bundle_manifest(handoff)).hexdigest(),
        'matrix_sha256':hashlib.sha256(bundle_manifest(matrix)).hexdigest(),
        'native_acceptance':'not_run','manufacturing_approved':False,
        'runtime_bundled':False, 'source_only':True}
    candidate['candidate_id'] = hashlib.sha256(bundle_manifest(candidate)).hexdigest()
    if source_index is not None:write_new(destination/'source-index.json',source_index)
    for name,value in [('candidate.json',candidate),('matrix.json',matrix),('submission-template.json',submission)]:
        write_new(destination/name,value)
    (destination/'READ-FIRST.txt').write_text(
        'Source candidate; Windows runtime and SolidWorks are NOT included.\n'
        'Extract source.zip into a NEW directory. Run python work/verify_test_handoff.py .\n'
        'Install requirements-cloud.txt into a new environment. python app.py\n'
        'Cloud regression: python work/run_integrated_tests.py --out <new-directory>\n'
        'Workflow: python work/delivery.py prepare <request.json> --out <new-workspace>\n'
        'Native work is Windows-only, explicitly reviewed, on isolated work copies.\n'
        'Fill submission-template.json. Audit with work/delivery.py audit matrix.json submission.json --evidence-root <evidence> --out <new-report-directory>.\n'
        'A passed audit checks declared records and bytes, never manufacturing approval.\n',encoding='utf-8')
    return candidate


def bundle_manifest(value):
    return json.dumps(value,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()


def verify_candidate(root):
    root=Path(root).resolve(strict=True);candidate=read_json(root/'candidate.json')
    payload=dict(candidate);identity=payload.pop('candidate_id',None)
    issues=[]
    if candidate.get('schema_version')!=1 or hashlib.sha256(bundle_manifest(payload)).hexdigest()!=identity:
        issues.append('candidate_identity_changed')
    if file_hash(root/'source.zip')!=candidate.get('package_sha256'):issues.append('source_archive_changed')
    if hashlib.sha256(bundle_manifest(read_json(root/'matrix.json'))).hexdigest()!=candidate.get('matrix_sha256'):
        issues.append('test_matrix_changed')
    return {'status':'failed' if issues else 'passed','issues':issues,'source_revision':candidate.get('source_revision'),
            'scope':'candidate_file_integrity_only','manufacturing_approved':False}
