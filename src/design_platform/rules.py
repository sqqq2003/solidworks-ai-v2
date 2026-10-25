"""Sourced mechanical constraints over resolved existing-plan parameters."""
from .calculations import number


def evaluate_rules(values,rules):
    results=[]
    for rule in rules:
        if not rule.get('source') or rule.get('reviewed') is not True:
            results.append({'id':rule['id'],'status':'review_required','reason':'rule applicability not confirmed'});continue
        a=values.get(rule['left']);b=values.get(rule['right'])
        if a is None or b is None:results.append({'id':rule['id'],'status':'review_required','reason':'missing measured/resolved parameter'});continue
        if a.get('unit')!=b.get('unit') or a.get('unit')!=rule['unit']:raise ValueError('mechanical rule unit mismatch')
        x,y=number(a['value']),number(b['value']);margin=number(rule.get('margin',0))
        if rule['op']=='le':ok=x+margin<=y
        elif rule['op']=='ge':ok=x>=y+margin
        elif rule['op']=='equal':
            if 'tolerance' not in rule:raise ValueError('explicit equality tolerance required')
            tolerance=number(rule['tolerance'])
            if tolerance<0:raise ValueError('nonnegative tolerance required')
            ok=abs(x-y)<=tolerance
        else:raise ValueError('unknown mechanical comparison')
        results.append({'id':rule['id'],'status':'passed' if ok else 'failed','source':rule['source'],'left':x,'right':y,'unit':rule['unit']})
    return {'status':'failed' if any(r['status']=='failed' for r in results) else 'review_required' if any(r['status']=='review_required' for r in results) else 'declared_rules_satisfied',
        'results':results,'scope':'declared scalar rules only; native interference/motion remain independent'}
