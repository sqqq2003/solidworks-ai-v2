"""Materialize numeric parameters into the existing editable-feature whitelist."""
from copy import deepcopy
from pathlib import Path
import math
import re

from cad_checkpoint import digest_file
from drawing_review import atomic_json
from modeling_domain import analyze_draft
from modeling_domain.contract import digest
from .workflow import checked_preview

TOKEN=re.compile(r'\$\{([A-Za-z][A-Za-z0-9_]{0,63})\}\Z')


def materialize_part_plan(preview):
    checked_preview(preview)
    template=deepcopy(preview['spec_snapshot'].get('feature_template'))
    if not isinstance(template,dict):raise ValueError('rule file has no reviewed editable feature_template')
    values=preview['plan']['values_mm'];register=preview['plan']['parameter_register']
    if preview['plan'].get('unresolved'):raise ValueError('resolve all feature-template inputs before generation')
    def substitute(value,depth=0,path=()):
        if depth>32:raise ValueError('feature template nesting limit exceeded')
        if isinstance(value,dict):return {k:substitute(v,depth+1,path+(k,)) for k,v in value.items()}
        if isinstance(value,list):return [substitute(v,depth+1,path+(i,)) for i,v in enumerate(value)]
        if isinstance(value,str):
            token=TOKEN.fullmatch(value)
            if token:
                name=token[1]
                if name not in values or values[name] is None:raise ValueError('unknown feature parameter: '+name)
                unit=register[name]['unit']
                field=next((p for p in reversed(path) if isinstance(p,str)),None)
                allowed=({'mm3'} if field in {'min_volume_mm3','max_volume_mm3'} else
                         {'count'} if field=='min_faces' else
                         {'deg','rad'} if field=='angle_degrees' else {'mm','m'})
                if unit not in allowed:raise ValueError('feature parameter unit differs at '+str(path))
                # The existing feature contract's linear coordinates and
                # body bounds use mm; its volume expectations use mm3.
                result=values[name]*(1000 if unit=='m' else 180/math.pi if unit=='rad' else 1)
                if type(result) not in (int,float) or not math.isfinite(result):raise ValueError('numeric substitution required')
                return result
        return value
    plan=substitute(template)
    plan['parametric_origin']={'preview_sha256':preview['review_sha256'],
                               'source_spec_sha256':preview['source_spec']['sha256']}
    draft=analyze_draft(plan)
    if draft['status']!='draft_ready':raise ValueError('materialized feature plan has unresolved geometry: '+str(draft['conflicts']))
    return {'plan':plan,'plan_sha256':draft['plan_sha256'],'draft':draft,
            'native_executed':False,'manufacturing_approved':False}


def generate_native_part(preview, sw_exe, template, output, *, reviewer,
                         reviewed_plan_sha256, expected_template_sha256,
                         request_key, session_mode='auto', state_db=None):
    materialized=materialize_part_plan(preview)
    if not isinstance(reviewer,str) or not reviewer.strip():raise ValueError('named reviewer required')
    if materialized['plan_sha256']!=reviewed_plan_sha256:raise ValueError('materialized plan changed since review')
    if digest_file(template)!=expected_template_sha256:raise ValueError('part template changed since review')
    plan=deepcopy(materialized['plan'])
    # Bind the named decision into the execution payload. This is an explicit
    # review record and still grants no engineering/manufacturing acceptance.
    plan['parametric_review']={'reviewer':reviewer,'reviewed_feature_plan_sha256':reviewed_plan_sha256,
                              'template_sha256':expected_template_sha256}
    from modeling_domain.api import run_native_modeling
    return run_native_modeling(plan,sw_exe,template,output,
        expected_template_sha256=expected_template_sha256,reviewed_plan_sha256=digest(plan),
        request_key=request_key,state_db=state_db,session_mode=session_mode)
