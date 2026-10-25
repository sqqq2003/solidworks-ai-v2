"""Bridge dimension leaves to the existing reviewed transaction. No COM creation."""
from design_review import analyze_impact
from sw_api.mapping import load_mappings
from .dimensions import solve_chain


def prepare_native_review(request):
    solved=solve_chain(request['chain'])
    if solved['status']!='passed': raise ValueError('dimension chain has unresolved conflicts/inputs')
    rows={r['id']:r for r in request['chain']['dimensions']}
    mappings=load_mappings(request['mappings']); by_name={r.parameter:r for r in mappings}
    required=set(solved['protected'])|{r['parameter'] for r in solved['changes'] if not rows[r['parameter']].get('terms')}
    if set(by_name)!=required: raise ValueError('exact changed-leaf and protected-interface mappings required')
    intentions=request['intentions']; values={}; changes=[]
    for key,mapping in by_name.items():
        row=rows[key]
        protected=key in solved['protected']
        if (protected and mapping.component_kind not in {'fixed','purchased'}) or (not protected and mapping.component_kind!='editable'):
            raise ValueError('mapping write role conflicts with protected/adjustable dimension')
        if row.get('terms'): raise ValueError('derived dimension must be read back, not written as a second driving dimension')
        if mapping.status!='confirmed' or mapping.unit!='mm': raise ValueError('confirmed physical mm mapping required')
        intent=intentions.get('parameters',{}).get(key,{})
        if intent.get('role')!=row['role']: raise ValueError('mechanical role differs from reviewed intent')
        values[key]=solved['after_mm'][key]
        if key not in solved['protected']:
            changes.append({'parameter':key,'before':solved['before_mm'][key],'after':values[key],
                            'unit':'mm','source':row['source'],'document':mapping.document,
                            'configuration':mapping.configuration,'dimension':mapping.dimension})
    plan={'status':'ready_for_review','values_mm':values,'changes':changes}
    review=analyze_impact(plan,intentions)
    return {'plan':plan,'review':review,'chain':solved,'derived_readback_required':
            {k:v for k,v in solved['after_mm'].items() if rows[k].get('terms')},
            'native_status':'pending_windows_validation','native_write_allowed':False}


def execute_native_review(request, approval, port, destination):
    """Caller supplies already owned/isolated transaction port and named approval.

    Native output is NOT final roller acceptance: all derived dimensions and
    interface geometry still require existing roller/native verification.
    """
    from design_platform.native import execute_reviewed_transaction
    prepared=prepare_native_review(request)
    execution=execute_reviewed_transaction(prepared['plan'],request['intentions'],approval,
                                           request['mappings'],port,destination)
    return {'execution':execution,'derived_readback_required':prepared['derived_readback_required'],
            'status':'failed' if execution.get('status')=='failed' or execution.get('execution_status')=='failed' else 'review_required','native_acceptance':'derived_geometry_and_engineering_review_required',
            'manufacturing_approved':False}
