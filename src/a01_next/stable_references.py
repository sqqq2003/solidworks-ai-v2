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
