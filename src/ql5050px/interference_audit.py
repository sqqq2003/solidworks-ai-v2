"""Strict comparison of legacy and native interference evidence; no COM."""
import math
from collections import defaultdict


def component_names(record):
    components=record.get('components')
    if not isinstance(components,list) or not components:
        raise ValueError('nonempty interference component list required')
    names=[]
    for item in components:
        name=item.get('name') if isinstance(item,dict) else item
        if not isinstance(name,str) or not name.strip():
            raise ValueError('interference component has no valid name')
        names.append(name)
    return names


def compare_overlap_groups(expected,actual,*,families,abs_tol_mm3=.0001,rel_tol=1e-7):
    """Compare family-keyed volume multisets, retaining all internal body overlaps.

    Use only for unchanged geometry; remove explicitly intended changed pairs
    before calling. Family names must come from the verified source baseline.
    """
    for tolerance in (abs_tol_mm3,rel_tol):
        if isinstance(tolerance,bool) or not isinstance(tolerance,(int,float)) or not math.isfinite(tolerance) or tolerance<0:
            raise ValueError('finite nonnegative comparison tolerances required')
    families=sorted(set(families),key=len,reverse=True)
    if not families or any(not isinstance(f,str) or not f for f in families):
        raise ValueError('verified nonempty component families required')
    def family(name):
        leaf=name.rsplit('/',1)[-1]
        matches=[f for f in families if leaf==f or any(leaf.startswith(f+suffix) for suffix in ('_', '.step', '-'))]
        if not matches:raise ValueError('unmapped component family: '+leaf)
        return matches[0]
    def groups(records):
        grouped=defaultdict(list)
        for row in records:
            names=component_names(row)
            keys=[key for key in ('volume_mm3','volume_m3') if key in row]
            if len(keys)!=1:raise ValueError('one explicit interference volume unit required')
            value=row[keys[0]]
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<0:
                raise ValueError('invalid interference volume')
            volume=value*(1e9 if keys[0]=='volume_m3' else 1)
            if not math.isfinite(volume):raise ValueError('interference volume conversion overflow')
            grouped[tuple(sorted(family(n) for n in names))].append(volume)
        return {key:sorted(values) for key,values in grouped.items()}
    left,right=groups(expected),groups(actual)
    differences=[];compared=0;maximum=0.
    for key in sorted(left.keys()|right.keys()):
        a,b=left.get(key,[]),right.get(key,[])
        if len(a)!=len(b):
            differences.append({'families':list(key),'reason':'pair_multiplicity_changed','expected':len(a),'actual':len(b)})
            continue
        for previous,current in zip(a,b):
            compared+=1;maximum=max(maximum,abs(previous-current))
            if not math.isclose(previous,current,abs_tol=abs_tol_mm3,rel_tol=rel_tol):
                differences.append({'families':list(key),'reason':'volume_changed','previous_mm3':previous,'actual_mm3':current,'delta_mm3':current-previous})
    return {'status':'pass' if not differences else 'fail','compared':compared,
            'differences':differences,'max_delta_mm3':maximum,
            'abs_tol_mm3':abs_tol_mm3,'rel_tol':rel_tol}
