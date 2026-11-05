"""Per-drawing atomic technical evidence and explicit, immutable visual review.

Save/reopen and a native readback only admit `reviewing`. An acceptance decision
binds the exact evidence and artifact bytes, and never grants manufacturing
approval. No CAD APIs, process control or image recognition run here.
"""
from contextlib import contextmanager
import hashlib
import json
import os
import sqlite3
import re
from pathlib import Path
import tempfile
import uuid

from cad_checkpoint import digest_file, json_bytes

CHECKLIST = ('views', 'dimensions_annotations', 'scale', 'frame_title_bom')


def drawing_implementation_hashes():
    root=Path(__file__).resolve().parent
    return {name:digest_file(root/name) for name in
        ('drawing_review.py','drawing_checkpoint.py','drawing_run.py','cad_run.py',
         'ql5050px/native_drawings.py','ql5050px/drawing_verification.py',
         'ql5050px/drawing_trial.py','ql5050px/auto_layout.py','part_verification.py',
         'a01_next/native_production.py','sw_compat/com_access.py','sw_compat/annotation.py')}


def atomic_json(path, value, *, exclusive=False):
    path = Path(path).absolute()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or path.parent != path.parent.resolve():
        raise ValueError('evidence path alias refused')
    data = json_bytes(value) + b'\n'
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name + '-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        if exclusive:
            # Atomically publish without overwrite. A crash cannot expose half
            # a decision; concurrent accept/reject attempts have one winner.
            os.link(temporary, path)
        else:
            os.replace(temporary, path)
        if os.name != 'nt':
            directory = os.open(path.parent, os.O_RDONLY)
            try: os.fsync(directory)
            finally: os.close(directory)
    finally:
        if Path(temporary).exists(): Path(temporary).unlink()


def _read(path):
    from project_delivery import read_json
    return read_json(path)


class DrawingEvidence:
    def __init__(self, path, task, *, simulated_only=False, partial_model_test=False,
                 required_artifacts=('slddrw',), model_path=None):
        self.path = Path(path).resolve()
        self.data = {'schema_version': 1, 'scope': 'drawing_native_readback_and_visual_layout',
                     'evidence_id': uuid.uuid4().hex, 'task': task.get('id'),
                     'state': 'generating', 'complete': False, 'technical_status': 'running',
                     'simulated_only': bool(simulated_only), 'partial_model_test': bool(partial_model_test),
                     'required_artifacts': list(required_artifacts), 'artifacts': {},
                     'requested': {'scale': task.get('scale'), 'views': task.get('drawing_model', {}).get('views', []),
                                   'annotation_count': sum(len(task.get(k, [])) for k in ('dimensions', 'annotations', 'balloons'))+
                                   int(bool(task.get('drawing_model',{}).get('bom')))},
                     'views': [], 'annotations': [], 'layout_readback': None,
                     'annotation_reopen_verified': False,
                     'member_not_found': False, 'member_not_found_events': [],
                     'delivery_accepted': False, 'manufacturing_approved': False}
        self.data['implementation_sha256']=drawing_implementation_hashes()
        if model_path and Path(model_path).is_file():
            self.data['source'] = {'path': str(Path(model_path).resolve()), 'sha256': digest_file(model_path)}
        self.flush(exclusive=True)

    @classmethod
    def load(cls, path):
        obj = cls.__new__(cls); obj.path = Path(path).resolve(); obj.data = _read(obj.path)
        return obj

    def flush(self, *, exclusive=False):
        atomic_json(self.path, self.data, exclusive=exclusive)

    def com_error(self, member, error):
        from part_verification import is_member_not_found
        if not is_member_not_found(error): return
        self.data['member_not_found'] = True
        events = self.data['member_not_found_events']
        if len(events) < 128:
            events.append({'member': member, 'error_type': type(error).__name__,
                           'hresult': getattr(error, 'hresult', None)})
        else: self.data['events_truncated'] = True

    @contextmanager
    def observe_com(self):
        from sw_compat.com_access import observe_member_errors
        with observe_member_errors(self.com_error): yield

    def artifact(self, role, path):
        path = Path(path).resolve(strict=True)
        if not path.is_file() or not path.stat().st_size: raise ValueError('empty drawing artifact')
        self.data['artifacts'][role] = {'path': str(path), 'sha256': digest_file(path)}

    def finish(self):
        d = self.data
        d['complete'] = bool(d.get('source') and d['layout_readback'] and d['views'] and
            len(d['views']) == len(d['requested']['views']) and
            len(d['annotations']) == d['requested']['annotation_count'] and
            d['annotation_reopen_verified'] is True and not d.get('events_truncated') and
            all(k in d['artifacts'] for k in d['required_artifacts']) and
            ('pdf' not in d['required_artifacts'] or d.get('pdf_validation',{}).get('parsed') is True))
        d['technical_status'] = 'saved_reopened' if d['complete'] else 'incomplete_evidence'
        d['state'] = 'reviewing' if d['complete'] else 'generating'
        d['delivery_accepted'] = False
        self.flush()
        return inspect_drawing(self.path)

    def fail(self, error):
        self.com_error('drawing_pipeline', error)
        self.data.update(state='failed', complete=False, technical_status='failed',
                         error_type=type(error).__name__, error=str(error), delivery_accepted=False)
        if hasattr(error,'diagnostic'):
            self.data['layout_diagnostic']=error.diagnostic
            self.data['explicit_fit_alternatives']=error.alternatives
        self.flush()


def _verified_evidence(path):
    path = Path(path).resolve(strict=True); data = _read(path)
    if data.get('schema_version') != 1 or data.get('scope') != 'drawing_native_readback_and_visual_layout':
        raise ValueError('unsupported drawing evidence')
    issues = []
    if data.get('complete') is not True or data.get('technical_status') != 'saved_reopened': issues.append('technical_evidence_incomplete')
    if data.get('simulated_only') is not False: issues.append('simulated_evidence')
    requested = data.get('requested', {})
    if (not data.get('views') or len(data['views']) != len(requested.get('views', [])) or
            not data.get('layout_readback') or data.get('annotation_reopen_verified') is not True or
            len(data.get('annotations', [])) != requested.get('annotation_count') or data.get('events_truncated')):
        issues.append('native_readback_incomplete')
    artifacts = data.get('artifacts', {})
    if not data.get('required_artifacts') or any(role not in artifacts for role in data['required_artifacts']): issues.append('required_artifacts_missing')
    if 'pdf' in data.get('required_artifacts',[]) and data.get('pdf_validation',{}).get('parsed') is not True:issues.append('pdf_parse_unverified')
    for row in [data.get('source', {}), *artifacts.values()]:
        try:
            if not row or digest_file(row['path']) != row['sha256']: issues.append('source_or_artifact_changed')
        except (OSError, KeyError, TypeError): issues.append('source_or_artifact_missing')
    receipt=data.get('request_receipt')
    if receipt:
        from cad_receipts import ReceiptStore
        try:
            if not Path(receipt['database']).is_file():raise ValueError('missing receipt database')
            row=ReceiptStore(receipt['database']).get(receipt['key'])
            if row['status']!='COMPLETED' or row['session_state']!='RESOLVED':issues.append('native_request_unresolved_or_failed')
        except (OSError,KeyError,ValueError,sqlite3.Error):issues.append('native_request_receipt_missing')
    return path, data, sorted(set(issues))


def _decision_path(path, evidence_sha):
    return path.parent / 'visual-reviews' / (evidence_sha + '.json')


def inspect_drawing(path):
    path, data, issues = _verified_evidence(path)
    sha = digest_file(path); decision_file = _decision_path(path, sha)
    state = data.get('state') if data.get('state') in {'generating','failed','reviewing'} else 'reviewing'
    decision = None
    if decision_file.exists():
        decision = _read(decision_file)
        if (decision.get('evidence_sha256') != sha or decision.get('evidence_id') != data['evidence_id'] or
                decision.get('decision') not in {'accepted', 'rejected'} or not decision.get('reviewer') or
                decision.get('scope')!='human_visual_layout_review' or
                decision.get('artifact_sha256')!={k:v['sha256'] for k,v in data['artifacts'].items()} or
                (decision.get('decision')=='accepted' and any(decision.get('checklist',{}).get(k) is not True for k in CHECKLIST))):
            issues.append('visual_decision_invalid')
        elif decision['decision']=='rejected' or not issues: state = decision['decision']
    if issues and state == 'accepted': state = 'reviewing'
    accepted = state == 'accepted' and not issues
    return {'schema_version': 1, 'state': state, 'technical_status': data['technical_status'],
            'evidence_sha256': sha, 'evidence': str(path), 'issues': issues,
            'visual_accepted': accepted,
            'delivery_accepted': accepted and data.get('partial_model_test') is False,
            'partial_model_test': data.get('partial_model_test'),
            'member_not_found': data.get('member_not_found'), 'decision': decision,
            'manufacturing_approved': False}


def review_drawing(path, *, reviewer, expected_sha256, decision, checklist, notes=''):
    path, data, issues = _verified_evidence(path)
    sha = digest_file(path)
    if sha != expected_sha256: raise ValueError('drawing evidence changed since review')
    if not isinstance(reviewer, str) or not reviewer.strip(): raise ValueError('named visual reviewer required')
    if decision not in {'accepted', 'rejected'}: raise ValueError('accepted or rejected decision required')
    if decision == 'accepted':
        if issues: raise ValueError('drawing cannot be accepted: ' + ', '.join(issues))
        if not isinstance(checklist, dict) or any(checklist.get(k) is not True for k in CHECKLIST):
            raise ValueError('all four visual checklist items must be explicitly confirmed')
    elif not isinstance(notes, str) or not notes.strip(): raise ValueError('rejection reason required')
    record = {'schema_version': 1, 'decision': decision, 'reviewer': reviewer.strip(),
              'evidence_id': data['evidence_id'], 'evidence_sha256': sha,
              'artifact_sha256': {k: v['sha256'] for k, v in data['artifacts'].items()},
              'checklist': checklist, 'notes': notes, 'scope': 'human_visual_layout_review',
              'manufacturing_approved': False}
    atomic_json(_decision_path(path, sha), record, exclusive=True)
    # If CAD bytes changed during review, this result fails closed on readback.
    return inspect_drawing(path)


def inspect_drawing_batch(root):
    root=Path(root).resolve(strict=True);pages=[];issues=[]
    indexes=sorted(root.rglob('drawing-index.json'))
    for index in indexes:
        manifest=_read(index)
        if manifest.get('schema_version')!=1 or not manifest.get('pages'):issues.append('invalid_drawing_index');continue
        seen=set()
        for row in manifest['pages']:
            path=(index.parent/row['evidence']).resolve()
            if not path.is_relative_to(index.parent) or str(path) in seen:
                issues.append('external_or_duplicate_page');continue
            seen.add(str(path))
            try:pages.append(inspect_drawing(path))
            except (OSError,ValueError,KeyError,TypeError):issues.append('page_evidence_missing_or_invalid')
    if not indexes:issues.append('drawing_index_missing')
    if (root/'result.json').is_file():
        trial=_read(root/'result.json')
        if trial.get('mode')=='explicit_partial_model_test':
            if (trial.get('status')!='completed_partial_model_trial' or not trial.get('cells') or
                    any(c.get('status')!='pass_pending_visual' for c in trial['cells'])):
                issues.append('trial_not_fully_generated')
    accepted=bool(pages) and not issues and all(p['visual_accepted'] for p in pages)
    state=('accepted' if accepted else 'failed' if any(p['state']=='failed' for p in pages) else
           'rejected' if any(p['state']=='rejected' for p in pages) else
           'generating' if any(p['state']=='generating' for p in pages) else 'reviewing')
    return {'state':state,'pages':pages,'issues':issues,
            'visual_accepted':accepted,'delivery_accepted':accepted and all(p['delivery_accepted'] for p in pages),
            'counts':{state:sum(p['state']==state for p in pages) for state in ('generating','reviewing','accepted','rejected','failed')},
            'manufacturing_approved':False}


def export_visual_review(root,destination,*,source_revision):
    if not isinstance(source_revision,str) or not re.fullmatch('[a-f0-9]{40}',source_revision):
        raise ValueError('full tested code pin required')
    batch=inspect_drawing_batch(root)
    pages=[]
    for index,page in enumerate(batch['pages'],1):
        decision=page.get('decision') or {}
        pages.append({'page':index,'state':page['state'],'visual_accepted':page['visual_accepted'],
            'delivery_accepted':page['delivery_accepted'],'evidence_sha256':page['evidence_sha256'],
            'reviewer':decision.get('reviewer'),'checklist':decision.get('checklist',{}),
            'artifact_sha256':decision.get('artifact_sha256',{}),'member_not_found':page['member_not_found']})
    result={'schema_version':1,'scope':'human_visual_layout_review_export','source_revision':source_revision,
        'state':batch['state'],'visual_accepted':batch['visual_accepted'],'delivery_accepted':batch['delivery_accepted'],
        'pages':pages,'issues':batch['issues'],'manufacturing_approved':False,'includes_cad_binaries':False}
    atomic_json(destination,result,exclusive=True)
    return result
