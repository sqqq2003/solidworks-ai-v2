"""Bounded concept comparison and Chinese review-request adapter."""
from design_platform.assistant import parse_request
from .common import quantity, number, index, result, review_digest


def compare_proposals(request):
    alternatives=index(request['alternatives']); metrics=index(request['metrics'])
    pending=[]; records=[]; weights={}
    if len(alternatives)<2 or not metrics: pending.append('at_least_two_alternatives_and_metrics_required')
    for key,metric in metrics.items():
        weights[key]=number(metric['weight'],minimum=0)
        if metric['preference'] not in {'min','max'} or not metric.get('source'):
            raise ValueError('explicit sourced comparison preference required')
    if sum(weights.values())<=0: raise ValueError('positive total metric weight required')
    values={}
    for key,alt in alternatives.items():
        if alt.get('kind') not in {'gravity','chain','belt'}: raise ValueError('supported alternatives: gravity/chain/belt')
        values[key]={}
        for name,metric in metrics.items():
            cell=alt.get('metrics',{}).get(name)
            if cell is None: pending.append('missing_metric:'+key+':'+name); continue
            values[key][name]=quantity(cell,metric['unit'])
    if not pending:
        for key,alt in alternatives.items():
            score=0
            for name,metric in metrics.items():
                observed=[v[name] for v in values.values()]; low,high=min(observed),max(observed)
                normalized=.5 if high==low else (values[key][name]-low)/(high-low)
                if metric['preference']=='min': normalized=1-normalized
                score+=normalized*weights[name]/sum(weights.values())
            records.append({'id':key,'weighted_relative_score':score,'values':values[key]})
    return result({'comparison':sorted(records,key=lambda r:r['weighted_relative_score'],reverse=True),
                   'values':values,'best_scheme':None,'scope':'relative weighted comparison of supplied metrics only; engineering feasibility not inferred'},issues=pending)


def instruction_request(request):
    parsed=parse_request(request['text'])
    return result({'parsed':parsed,'request_sha256':review_digest(request),
                   'binding_review':request.get('binding_review'),
                   'proposed_targets':{'overall':{'value':parsed['target_overall_mm'],'unit':'mm','source':'user_instruction'}} if parsed['target_overall_mm'] else {},
                   'native_write_allowed':False,'requires_approval':True},issues=parsed['pending_confirmation'])
