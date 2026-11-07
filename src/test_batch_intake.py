"""Read-only, source-bound intake of a batch of native test reports.

Consistency is not independent CAD verification or mechanical acceptance.
Manifest paths are relative to the manifest directory; no scripts are run.
"""
import hashlib
import json
from pathlib import Path
import re

from sheet_metal_acceptance import audit_report


def _sha(value):
    return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) is not None


def _inside(root, name):
    if not isinstance(name, str) or not name or Path(name).is_absolute():
        raise ValueError('relative evidence path required')
    path = (root / name).resolve()
    if not path.is_relative_to(root):
        raise ValueError('evidence path escapes batch directory')
    return path


def audit_batch(manifest, folder):
    """Audit every declared case, keeping missing/invalid cases visible."""
    if not isinstance(manifest, dict) or manifest.get('schema_version') != 1:
        raise ValueError('batch schema_version must be 1')
    cases = manifest.get('cases')
    if not isinstance(cases, list) or not cases:
        raise ValueError('nonempty cases list required')
    root = Path(folder).resolve()
    results, seen = [], set()
    for index, case in enumerate(cases):
        issues = []
        label = case.get('id') if isinstance(case, dict) else None
        role = case.get('executor') if isinstance(case, dict) else None
        try:
            if not isinstance(label, str) or not label or not isinstance(role, str) or not role:
                raise ValueError('case id and executor required')
            key = (role, label)
            if key in seen:
                raise ValueError('duplicate executor/case id')
            seen.add(key)
            for field in ('report_sha256', 'source_sha256', 'code_sha256'):
                if not _sha(case.get(field)):
                    raise ValueError('invalid ' + field)
            source = _inside(root, case.get('source'))
            if hashlib.sha256(source.read_bytes()).hexdigest() != case['source_sha256']:
                issues.append('fixture_bytes_changed')
            raw = _inside(root, case.get('report')).read_bytes()
            if hashlib.sha256(raw).hexdigest() != case['report_sha256']:
                issues.append('report_bytes_changed')
            report = json.loads(raw.decode('utf-8-sig'))
            if not isinstance(report, dict) or not isinstance(report.get('plan'), dict):
                raise ValueError('report and plan must be objects')
            plan = report['plan']
            for field in ('source_sha256', 'code_sha256'):
                if plan.get(field) != case[field]:
                    issues.append(field + '_mismatch')
            params = case.get('parameters')
            if not isinstance(params, dict) or not params:
                raise ValueError('explicit expected parameters required')
            if any(plan.get('parameters', {}).get(k) != v for k, v in params.items()):
                issues.append('expected_parameters_mismatch')
            if type(case.get('profile_index')) is not int or plan.get('profile_index') != case['profile_index']:
                issues.append('profile_index_mismatch')
            issues.extend(audit_report(report)['issues'])
        except (OSError, ValueError, TypeError, KeyError, AttributeError, RuntimeError) as error:
            issues.append('invalid_or_missing_evidence: ' + str(error))
        results.append(dict(index=index, id=label, executor=role,
                            status='review_required' if issues else 'evidence_consistent',
                            issues=list(dict.fromkeys(issues))))
    passed = sum(item['status'] == 'evidence_consistent' for item in results)
    return dict(schema_version=1, status='evidence_consistent' if passed == len(results) else 'review_required',
                counts=dict(total=len(results), consistent=passed, review_required=len(results)-passed),
                cases=results, cad_executed=False, mechanical_acceptance='unverified',
                note='Submitted records and local bytes only; no independent live CAD verification.')
