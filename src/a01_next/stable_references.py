"""Validate identity-bound persistent reference records without resolving COM."""
import base64
import binascii
import re


def validate_references(payload):
    if not isinstance(payload,dict) or payload.get('schema_version') != 1:
        raise ValueError('reference schema_version 1 required')
    refs=payload.get('references')
    if not isinstance(refs,list) or not refs:
        raise ValueError('nonempty references required')
    seen,targets=set(),set()
    pending=[]
    for row in refs:
        if not isinstance(row,dict):
            raise ValueError('reference record must be an object')
        name=row.get('id')
        if not isinstance(name,str) or not name or name in seen:
            raise ValueError('unique semantic reference id required')
        seen.add(name)
        for key in ('document_sha256','configuration','component_path','entity_type'):
            if not isinstance(row.get(key),str) or not row[key]:
                raise ValueError(name+': missing '+key)
        if not re.fullmatch('[0-9a-f]{64}',row['document_sha256']):
            raise ValueError(name+': invalid document hash')
        if row['entity_type'] not in ('face','edge','vertex','plane','axis','point'):
            raise ValueError(name+': unsupported entity type')
        token=row.get('persistent_reference_base64')
        if not isinstance(token,str) or not token or len(token)>65536:
            raise ValueError(name+': persistent reference required; face/edge ordinal is not stable')
        try:
            decoded=base64.b64decode(token,validate=True)
        except (ValueError,binascii.Error) as error:
            raise ValueError(name+': invalid persistent reference') from error
        if not decoded:
            raise ValueError(name+': empty persistent reference')
        target=(row['document_sha256'],row['configuration'],row['component_path'],decoded)
        if target in targets:
            raise ValueError('duplicate physical reference')
        targets.add(target)
        # A claimed confirmation is not live resolution evidence.
        pending.append(dict(id=name,reason='native resolution and geometric signature must be verified on owned working copy'))
    return dict(status='pending_native_resolution',validated_records=len(refs),pending=pending,
                cad_executed=False,native_resolved=False)


def compare_resolution(payload, observations, *, document_sha256, configuration,
                       component_path, tolerance_mm):
    """Compare caller-supplied native readbacks; never search by face ordinal.

    Observations must come from a separately owned native read-only adapter.
    This compares evidence only and grants no permission to write a model.
    Expected geometric signature fields and tolerance must be reviewed first.
    """
    import math
    validate_references(payload)
    if type(tolerance_mm) not in (float, int) or not math.isfinite(tolerance_mm) or tolerance_mm <= 0:
        raise ValueError('explicit positive millimetre tolerance required')
    if not isinstance(observations, list):
        raise ValueError('native observation list required')
    rows = []
    for ref in payload['references']:
        reasons = []
        if (ref['document_sha256'], ref['configuration'], ref['component_path']) != (
                document_sha256, configuration, component_path):
            reasons.append('document_configuration_or_component_mismatch')
        matches = [o for o in observations if o.get('id') == ref['id']]
        if len(matches) != 1:
            reasons.append('missing_or_ambiguous_native_resolution')
        else:
            observed = matches[0]
            for key in ('document_sha256', 'configuration', 'component_path', 'entity_type',
                        'persistent_reference_base64'):
                if observed.get(key) != ref[key]:
                    reasons.append(key + '_mismatch')
            if observed.get('resolution_status') != 'resolved':
                reasons.append('native_reference_not_resolved')
            signature = ref.get('signature_mm')
            actual = observed.get('signature_mm')
            if not isinstance(signature, dict) or not signature or not isinstance(actual, dict):
                reasons.append('geometric_signature_missing')
            else:
                # Only millimetre quantities belong here; normals/angles/areas
                # need their own unit-specific contract and are not guessed.
                for key, expected in signature.items():
                    if key not in {'center_x', 'center_y', 'center_z', 'radius', 'length'}:
                        raise ValueError('unsupported millimetre signature field')
                    value = actual.get(key)
                    if (type(expected) not in (int, float) or not math.isfinite(expected)
                            or type(value) not in (int, float) or not math.isfinite(value)):
                        reasons.append(key + '_unavailable')
                    elif abs(expected - value) > tolerance_mm:
                        reasons.append(key + '_changed')
        rows.append({'id': ref['id'], 'status': 'blocked' if reasons else 'observations_match',
                     'reasons': reasons})
    return {'schema_version': 1, 'status': 'blocked' if any(r['reasons'] for r in rows)
            else 'observations_match_pending_review', 'references': rows,
            'tolerance_mm': tolerance_mm, 'native_write_allowed': False,
            'production_approved': False, 'cad_executed': False}
