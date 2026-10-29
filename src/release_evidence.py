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
        {'id': hashlib.sha256((r['sha']+'\0'+r['lane']+'\0'+r['id']).encode()).hexdigest()[:16],
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


def compare_audits(before, after):
    """Compare declared evidence coverage, never close an engineering defect."""
    states={'passed','degraded','failed','review_required'}
    def indexed(report):
        if report.get('scope')!='declared_coverage_and_file_integrity_only':
            raise ValueError('expected an evidence integrity audit report')
        rows={}
        for row in report.get('results',[]):
            key=(row.get('sha'),row.get('lane'),row.get('id'))
            if (not isinstance(key[0],str) or not re.fullmatch('[0-9a-f]{40}',key[0]) or
                not all(isinstance(k,str) and k for k in key[1:]) or
                row.get('status') not in states or key in rows):
                raise ValueError('invalid or duplicate audit result identity')
            rows[key]=row
        return rows
    old,new=indexed(before),indexed(after);changes=[]
    for key in sorted(set(old)|set(new)):
        left,right=old.get(key),new.get(key)
        if left is None:kind='new_check_or_candidate'
        elif right is None:kind='no_longer_reported'
        elif left['status']=='passed' and right['status']!='passed':kind='regression'
        elif left['status']!='passed' and right['status']=='passed':kind='evidence_improved_requires_engineering_review'
        elif (left['status'],sorted(left.get('issues',[])))!=(right['status'],sorted(right.get('issues',[]))):kind='changed'
        else:continue
        changes.append({'source_revision':key[0],'lane':key[1],'check':key[2],'kind':kind,
            'before':left['status'] if left else None,'after':right['status'] if right else None,
            'new_issues':sorted(set(right.get('issues',[]) if right else [])-set(left.get('issues',[]) if left else [])),
            'resolved_evidence_issues':sorted(set(left.get('issues',[]) if left else [])-set(right.get('issues',[]) if right else [])) if left and right else []})
    return {'schema_version':1,'status':'review_required','scope':'evidence_comparison_only','changes':changes,
            'counts':dict(Counter(row['kind'] for row in changes)),
            'engineering_defects_auto_closed':False,'manufacturing_approved':False}


def save_audit(report, destination, *, previous=None):
    from design_review.impact import review_digest
    from project_delivery import write_new
    delta=compare_audits(previous,report) if previous is not None else None
    root=Path(destination).resolve();root.mkdir(parents=True,exist_ok=False)
    write_new(root/'audit.json',report)
    write_new(root/'repair-tasks.json',{'schema_version':1,'tasks':report['repair_tasks']})
    if delta is not None:write_new(root/'comparison.json',delta)
    receipt={'schema_version':1,'audit_sha256':review_digest(report),'previous_audit_sha256':review_digest(previous) if previous else None,
             'files':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in root.iterdir() if p.is_file()},
             'native_acceptance':'requires_independent_review','manufacturing_approved':False}
    write_new(root/'receipt.json',receipt)
    return {**report,'report_directory':str(root),'comparison':delta}
