"""Explicit signed mm dimension DAG; no geometric or OEM inference."""
import math
from .common import index, number, quantity, result


def solve_chain(request):
    rows = index(request['dimensions']); targets = request.get('targets', {})
    before, after, pending, errors, order = {}, {}, [], [], []
    if not rows:
        return result({}, issues=['empty_dimension_chain'])
    for key, row in rows.items():
        if row.get('unit') != 'mm' or not row.get('datum') or not row.get('source'):
            raise ValueError('dimension requires mm, datum and source')
        if row.get('role') not in {'adjustable', 'interface', 'fixed', 'purchased'}:
            raise ValueError('explicit dimension role required')
        for term in row.get('terms', []):
            if term.get('direction') not in (-1, 1) or type(term.get('direction')) is not int:
                raise ValueError('term direction must be +1 or -1')
            if term['dimension'] not in rows:
                errors.append('missing_reference:'+term['dimension'])
            elif rows[term['dimension']]['datum'] != row['datum']:
                errors.append('datum_mismatch:'+key)
    active, done = set(), set()
    def visit(key):
        if key in active:
            raise ValueError('dimension dependency cycle')
        if key in done: return
        active.add(key)
        for term in rows[key].get('terms', []):
            if term['dimension'] in rows: visit(term['dimension'])
        active.remove(key); done.add(key); order.append(key)
    for key in rows: visit(key)
    def evaluate(overrides):
        values = {}
        for key in order:
            row = rows[key]
            if row.get('terms'):
                if any(t['dimension'] not in values for t in row['terms']): continue
                value = sum(t['direction']*values[t['dimension']] for t in row['terms'])
                if row.get('value') is not None and not overrides and abs(number(row['value'])-value)>1e-7:
                    errors.append('overconstrained_baseline:'+key)
            elif key in overrides: value = overrides[key]
            elif row.get('value') is not None: value = number(row['value'])
            else: continue
            values[key] = value
        return values
    before = evaluate({}); overrides = {}
    for key, target in targets.items():
        if key not in rows: raise ValueError('unknown target dimension')
        value = quantity(target, 'mm', minimum=0)
        row = rows[key]
        if row['role'] != 'adjustable':
            if key not in before or before[key] != value: errors.append('protected_target:'+key)
            continue
        if not row.get('terms'): overrides[key] = value; continue
        solve_for = row.get('solve_for')
        terms = row['terms']; selected = [t for t in terms if t['dimension'] == solve_for]
        if len(selected) != 1 or solve_for not in rows or rows[solve_for].get('terms') or rows[solve_for]['role'] != 'adjustable':
            errors.append('explicit_single_adjustable_leaf_required:'+key); continue
        if any(t['dimension'] not in before for t in terms if t['dimension'] != solve_for):
            pending.append('missing_target_dependencies:'+key); continue
        proposed = (value-sum(t['direction']*before[t['dimension']] for t in terms if t['dimension'] != solve_for))/selected[0]['direction']
        if solve_for in overrides and overrides[solve_for] != proposed: errors.append('conflicting_targets:'+solve_for)
        overrides[solve_for] = proposed
    after = evaluate(overrides)
    for key, row in rows.items():
        if key not in before or key not in after:
            pending.append('missing_dimension:'+key); continue
        value = after[key]
        if 'minimum_mm' in row and value < number(row['minimum_mm']): errors.append('below_minimum:'+key)
        if 'maximum_mm' in row and value > number(row['maximum_mm']): errors.append('above_maximum:'+key)
        if row['role'] != 'adjustable' and value != before[key]: errors.append('protected_changed:'+key)
    for key, target in targets.items():
        if key in after and abs(after[key]-target['value'])>1e-7: errors.append('target_not_satisfied:'+key)
    changes = [{'parameter':k,'before':before[k],'after':after[k],'unit':'mm','source':rows[k]['source'], 'datum':rows[k]['datum']}
               for k in order if k in before and k in after and before[k] != after[k]]
    return result({'before_mm':before,'after_mm':after,'order':order,'changes':changes,
                   'protected':{k:before.get(k) for k,r in rows.items() if r['role']!='adjustable'},
                   'write_allowed':False}, issues=pending, failed=errors)


def tolerance_stack(request):
    """Worst-case signed stack. Explicit asymmetric deviations, no guessed fits."""
    rows = index(request['dimensions']); low = high = nominal = 0.; missing = []
    for term in request['terms']:
        row = rows[term['dimension']]; sign = term['direction']
        if type(sign) is not int or sign not in (-1,1): raise ValueError('signed direction required')
        if row.get('datum') != request['datum']: raise ValueError('common explicit datum required')
        value = quantity(row, 'mm'); nominal += sign*value
        tol = row.get('tolerance')
        if not tol or not tol.get('source') or tol.get('unit') != 'mm':
            missing.append('missing_manufacturing_tolerance:'+term['dimension']); continue
        lo, hi = number(tol['lower']), number(tol['upper'])
        if lo > hi: raise ValueError('lower tolerance exceeds upper')
        a,b = sign*(value+lo),sign*(value+hi); low+=min(a,b); high+=max(a,b)
    if not request['terms']: missing.append('empty_tolerance_stack')
    failures=[]
    interval=None if missing else {'minimum_mm':low,'maximum_mm':high}
    if interval and 'required_interval_mm' in request:
        a,b = map(number, request['required_interval_mm'])
        if a>b: raise ValueError('invalid required interval')
        if (low<a and not math.isclose(low,a,rel_tol=0,abs_tol=1e-12)) or (high>b and not math.isclose(high,b,rel_tol=0,abs_tol=1e-12)): failures.append('worst_case_outside_required_interval')
    return result({'nominal_mm':nominal,'worst_case':interval,'method':'extreme_values',
                   'assumptions':['signed linear stack; repeated/correlated terms may overestimate bounds; not statistical RSS']},issues=missing,failed=failures)
