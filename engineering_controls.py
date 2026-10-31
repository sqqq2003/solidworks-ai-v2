"""Future CAD input/reference gates; no SolidWorks imports or write operations."""
from __future__ import annotations

import base64
import binascii
import math
import re

SHA256 = re.compile(r'^[a-fA-F0-9]{64}$')


def production_parameter_issues(record: dict) -> list[str]:
    issues = []
    value = record.get('value')
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        issues.append('missing_or_invalid_value')
    if record.get('unit') not in {'mm', 'degree', 'ratio', 'count'}:
        issues.append('unsupported_unit')
    if record.get('confirmation_status') != 'engineering_confirmed':
        issues.append('engineering_confirmation_required')
    if record.get('production_approved') is not True:
        issues.append('production_approval_required')
    source = record.get('source') or {}
    if not source.get('locator') or not SHA256.fullmatch(str(source.get('artifact_sha256', ''))):
        issues.append('traceable_source_required')
    limit = record.get('confirmed_range')
    valid_range = isinstance(limit, list) and len(limit) == 2 and all(
        not isinstance(v, bool) and isinstance(v, (int, float)) and math.isfinite(v) for v in limit
    ) and limit[0] <= limit[1]
    if not valid_range:
        issues.append('confirmed_range_required')
    elif not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value) and not limit[0] <= value <= limit[1]:
        issues.append('outside_confirmed_range')
    if not record.get('confirmed_by') or not record.get('confirmed_at'):
        issues.append('confirmation_audit_required')
    return issues


def stable_reference_issues(record: dict, *, document_sha256: str, configuration: str) -> list[str]:
    issues = []
    if not record.get('semantic_role') or not record.get('component_instance_key'):
        issues.append('semantic_and_component_identity_required')
    if not SHA256.fullmatch(str(record.get('document_sha256', ''))) or record.get('document_sha256') != document_sha256:
        issues.append('document_revision_mismatch')
    if not configuration or record.get('configuration') != configuration:
        issues.append('configuration_mismatch')
    if record.get('reference_kind') != 'solidworks_persistent_reference':
        issues.append('persistent_reference_required')
    try:
        encoded = record.get('persistent_reference_base64')
        if not isinstance(encoded, str) or not encoded or not base64.b64decode(encoded, validate=True):
            issues.append('persistent_reference_bytes_required')
    except (ValueError, binascii.Error):
        issues.append('persistent_reference_bytes_required')
    if record.get('resolved_and_checked') is not True or not record.get('validation_evidence'):
        issues.append('cad_resolution_evidence_required')
    return issues
