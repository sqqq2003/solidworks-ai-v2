"""Desktop repair preparation service. No CAD activation or writes."""
import hashlib
import json
from pathlib import Path

from .repair_planning import plan_slot_relief, require_trial


def prepare_trial(source, specification, output):
    source=Path(source).resolve();specification=Path(specification).resolve()
    spec=json.loads(specification.read_text(encoding='utf-8-sig'))
    actual=hashlib.sha256(source.read_bytes()).hexdigest()
    if spec.get('source_sha256')!=actual:
        raise ValueError('来源模型已变化，请重新测量并更新参数记录。')
    plan=plan_slot_relief(**spec)
    payload=json.dumps(plan,ensure_ascii=False,indent=2,allow_nan=False)+'\n'
    output=Path(output).resolve()
    output.mkdir(parents=True,exist_ok=False)
    target=output/'trial-plan.json'
    with target.open('x',encoding='utf-8') as stream:stream.write(payload)
    return {'status':plan['status'],'plan':str(target),'source_sha256':actual,
            'existing_radius_mm':plan['existing_radius_mm'],
            'target_radius_mm':plan['target_radius_mm'],
            'cad_executed':False,'production_approved':False}


def validate_trial(source, plan_path):
    source=Path(source).resolve();plan_path=Path(plan_path).resolve()
    plan=json.loads(plan_path.read_text(encoding='utf-8-sig'))
    actual=hashlib.sha256(source.read_bytes()).hexdigest()
    require_trial(plan,actual)
    return {'status':'trial_plan_valid','source_sha256':actual,
            'plan':str(plan_path),'cad_executed':False,'production_approved':False}
