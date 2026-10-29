"""Sourced design review; reuse existing scalar rule engine, never auto-fix."""
from design_platform.rules import evaluate_rules
from .common import number, result


def review_design(request):
    accepted=[]; pending=[]; metadata={}
    minimum=number(request.get('minimum_confidence',1),minimum=0)
    if minimum>1: raise ValueError('invalid minimum confidence')
    for key,value in request.get('values',{}).items():
        if not value.get('source'): pending.append('missing_value_source:'+key)
    for rule in request.get('rules',[]):
        confidence=number(rule.get('confidence',0),minimum=0)
        if confidence>1: raise ValueError('confidence exceeds one')
        metadata[rule['id']]={k:rule.get(k) for k in ('source','scope','confidence','suggestion')}
        if not rule.get('scope') or rule.get('scope')!=request.get('scope') or confidence<minimum:
            pending.append('rule_applicability_requires_review:'+rule['id'])
        else: accepted.append(rule)
    output=evaluate_rules(request.get('values',{}),accepted)
    if not request.get('rules'): pending.append('no_review_rules')
    records=[dict(row,metadata=metadata[row['id']]) for row in output['results']]
    return result({'results':records,'repair_suggestions':[{'id':r['id'],'suggestion':metadata[r['id']].get('suggestion'),
                     'evidence':r,'automatic_write':False} for r in records if r['status']!='passed'],
                   'automatic_write':False},issues=pending+(['unconfirmed_rule'] if output['status']=='review_required' else []),
                  failed=['design_rule_failed'] if output['status']=='failed' else [])
