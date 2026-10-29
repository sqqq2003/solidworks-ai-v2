"""Read-only evidence inbox, reusing the cross-version integrity auditor."""
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import zipfile
from test_handoff_audit import audit_handoff, validate_matrix


def audit_submission(matrix, submission, evidence_root):
    validate_matrix(matrix)
    normalized = deepcopy(submission)
    holds = {}
    for row in normalized.get('results', []):
        if not isinstance(row, dict): raise ValueError('evidence results must be records')
        key = (row.get('lane'), row.get('id'))
        if row.get('scope') == 'native':
            reasons = []
            if row.get('simulated_only') is not False: reasons.append('native_execution_not_declared')
            if row.get('session', {}).get('ownership') != 'spawned_pid_and_live_handle' or row.get('session', {}).get('attached_existing') is not False:
                reasons.append('owned_session_evidence_missing')
            if reasons:
                holds.setdefault(key, []).extend(reasons)
                # Preserve a declared failure instead of hiding it with a hold.
                if row.get('status') != 'failed': row['status'] = 'review_required'
    report = audit_handoff(matrix, normalized, evidence_root)
    for row in report['results']:
        row['issues'] = sorted(set(row['issues'] + holds.get((row['lane'],row['id']), [])))
    for row in report['results']:
        if row['status']=='degraded' and not row['issues']:row['issues']=['runner_reported_degradation']
    report['repair_tasks'] = [
        {'id': hashlib.sha256((r['lane']+'\0'+r['id']).encode()).hexdigest()[:16],
         'lane':r['lane'], 'check':r['id'], 'source_revision':r['sha'],
         'priority':'P0' if r['status']=='failed' else 'P1',
         'action':'repair_and_repeat_same_check' if r['status']=='failed' else 'supply_or_review_evidence',
         'reasons':r['issues'], 'status':'open'}
        for r in report['results'] if r['status'] != 'passed']
    return report


def inspect_diagnostics(archive):
    """Inspect bounded JSONL in a ZIP without extracting or running any member."""
    findings = []; counts = Counter(); seen = set()
    with zipfile.ZipFile(archive) as bundle:
        members = bundle.infolist()
        if len(members) > 500 or sum(m.file_size for m in members) > 32*1024*1024:
            raise ValueError('diagnostic ZIP exceeds bounded inbox size')
        for member in members:
            name = member.filename
            path = PurePosixPath(name)
            if path.is_absolute() or '..' in path.parts or '\\' in name or ':' in name:
                raise ValueError('unsafe diagnostic member path')
            if not name.endswith('.jsonl'): continue
            if member.file_size > 8*1024*1024: raise ValueError('diagnostic member too large')
            for index,line in enumerate(bundle.read(member).decode('utf-8-sig').splitlines(),1):
                if not line.strip(): continue
                try: row = json.loads(line)
                except (ValueError,TypeError):
                    findings.append({'member':name,'line':index,'kind':'malformed_jsonl'});continue
                if not isinstance(row,dict): continue
                event = row.get('event', 'unknown'); counts[str(event)] += 1
                # Journal schemas may nest payload as data or payload.
                payload = row.get('details', row.get('data', row.get('payload', row)))
                if not isinstance(payload,dict): continue
                if event not in {'job_finished','cli_error','error','queue_finished'}: continue
                if payload.get('status') not in {'failed','timed_out'} and event not in {'cli_error','error'}: continue
                messages = [str(e.get('message','')) for e in payload.get('errors',[]) if isinstance(e,dict)]
                message = str(payload.get('message') or payload.get('error') or (messages[-1] if messages else ''))
                detail = str(payload.get('detail',''))
                signature = hashlib.sha256((event+'\0'+message+'\0'+detail).encode()).hexdigest()[:16]
                if signature in seen: continue
                seen.add(signature)
                context = message+' '+str(payload.get('stderr',''))
                stage = 'dwg_conversion' if 'convert_dwg' in context or 'DWG' in context or 'exclusive ownership' in context else 'requires_triage'
                findings.append({'id':signature,'member':name,'line':index,'kind':'reported_failure',
                                 'event':event,'message':message[:1000],'error_type':detail,'stage':stage})
    return {'schema_version':1,'status':'review_required','scope':'diagnostic_triage_only',
            'events':dict(counts),'findings':findings,'cad_executed':False,'manufacturing_approved':False}
