"""Parameter planning and a source-bound handoff; never launches CAD."""
import hashlib
import json
import math
from pathlib import Path

from a01_parametric.config import SPEC_PATH
from a01_parametric.solver import solve_spec
from sw_api.mapping import mapping_template


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    allow_nan=False).encode('utf8')).hexdigest()


def preview_parameters(length, width, height, *, spec_path=None):
    dimensions = {}
    for key, label, value in [('length','长度',length), ('width','宽度',width), ('height','高度',height)]:
        try:
            if isinstance(value, bool):raise ValueError()
            number = float(value)
            if not math.isfinite(number) or number <= 0:raise ValueError()
        except (TypeError, ValueError, OverflowError):
            raise ValueError('请填写大于零的目标'+label+'（mm）') from None
        dimensions[key] = number
    path = Path(spec_path) if spec_path else SPEC_PATH
    path = path.expanduser().resolve()
    raw = path.read_bytes()
    plan = solve_spec(path, **dimensions)
    if path.read_bytes() != raw:
        raise ValueError('机型规则已变化，请重新计算')
    result = {'schema_version':1, 'kind':'parametric_modeling_workspace',
              'source_spec':{'path':str(path),'sha256':hashlib.sha256(raw).hexdigest()},
              'spec_snapshot':json.loads(raw.decode('utf-8-sig')),
              'target_envelope_mm':dimensions, 'plan':plan,
              'mapping_template':mapping_template(plan),
              'status':'review_required', 'native_write_allowed':False,
              'cad_executed':False, 'manufacturing_approved':False}
    result['review_sha256'] = _digest(result)
    return result


def save_parameter_workspace(preview, destination):
    payload = {k:v for k,v in preview.items() if k!='review_sha256'}
    if _digest(payload) != preview.get('review_sha256'):
        raise ValueError('参数方案已变化，请重新计算')
    source = preview['source_spec']
    if hashlib.sha256(Path(source['path']).read_bytes()).hexdigest()!=source['sha256']:
        raise ValueError('机型规则已变化，请重新计算')
    destination = Path(destination).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=False)
    documents = {'request.json':preview, 'plan.json':preview['plan'],
                 'model-mapping.json':preview['mapping_template'],
                 'machine-spec.json':preview['spec_snapshot']}
    for name, body in documents.items():
        with (destination/name).open('x',encoding='utf8') as stream:
            json.dump(body,stream,ensure_ascii=False,indent=2,allow_nan=False)
    manifest = {name:hashlib.sha256((destination/name).read_bytes()).hexdigest() for name in documents}
    with (destination/'SHA256.json').open('x',encoding='utf8') as stream:
        json.dump(manifest,stream,indent=2)
    return destination
