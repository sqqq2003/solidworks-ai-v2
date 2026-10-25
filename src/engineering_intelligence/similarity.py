"""Evidence-based duplicate candidates, never an automatic replacement command."""
from itertools import combinations
import re
from .common import number, index, result


def find_similar(request):
    parts=index(request['parts']); tolerance=request.get('dimension_tolerance_mm')
    if tolerance is None: raise ValueError('explicit comparison tolerance required')
    tolerance=number(tolerance,minimum=0); candidates=[]; pending=[]
    if not parts: pending.append('empty_parts')
    for a,b in combinations(parts.values(),2):
        differences=[]; comparable=True; dimensional_close=True; attributes_equal=True
        for row in (a,b):
            if row.get('unit')!='mm' or not row.get('source') or not row.get('dimensions'):
                comparable=False
        if not comparable: pending.append('missing_similarity_evidence:'+a['id']+':'+b['id']);continue
        keys=a['dimensions'].keys()|b['dimensions'].keys()
        for key in sorted(keys):
            av,bv=a['dimensions'].get(key),b['dimensions'].get(key)
            if av is None or bv is None or abs(number(av)-number(bv))>tolerance:
                dimensional_close=False
            if av != bv:
                differences.append({'field':'dimensions.'+key,'before':av,'after':bv})
        for key in ('material','features','interfaces'):
            if key not in a or key not in b:
                pending.append('missing_'+key+':'+a['id']+':'+b['id']);comparable=False
            if a.get(key)!=b.get(key):
                attributes_equal=False
                differences.append({'field':key,'before':a.get(key),'after':b.get(key)})
        exact=bool(re.fullmatch('[0-9a-f]{64}',a.get('sha256','')) and a.get('sha256')==b.get('sha256'))
        if exact or (dimensional_close and attributes_equal and comparable):
            candidates.append({'parts':[a['id'],b['id']],'kind':'identical_file_hash' if exact else 'declared_geometry_candidate',
                               'differences':differences,'metadata_complete':comparable,'replace_allowed':False})
    return result({'candidates':candidates,'comparisons':len(parts)*(len(parts)-1)//2,'automatic_replace':False},issues=pending)
