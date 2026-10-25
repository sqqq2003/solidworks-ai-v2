"""Review gate around the existing transaction protocol, no COM session creation."""
from design_review import analyze_impact,record_approval
from sw_api.mapping import load_mappings
from sw_api.transaction import execute
from .calculations import number


def execute_reviewed_transaction(plan,intentions,approval,mappings,port,destination):
    review=analyze_impact(plan,intentions)
    record_approval(review,reviewer=approval['reviewer'],review_sha256=approval['review_sha256'])
    if approval.get('plan_sha256')!=review['plan_sha256'] or approval.get('intent_sha256')!=review['intent_sha256']:raise ValueError('native review changed')
    rows=load_mappings(mappings);mapped={r.parameter:r for r in rows}
    if any(r.status!='confirmed' or r.unit!='mm' for r in rows):raise ValueError('confirmed mm transaction mappings required')
    edits={row['parameter']:row for row in review['changes']}
    protected={row['parameter'] for row in review['protected_readbacks']}
    for row in rows:
        target=plan.get('values_mm',{}).get(row.parameter)
        if target is None:raise ValueError('native target value missing')
        if row.component_kind=='editable' and row.parameter not in protected:
            edit=edits.get(row.parameter)
            if edit is None or number(edit['after'])!=number(target):raise ValueError('unreviewed editable transaction target')
            if (edit.get('document'),edit.get('configuration'),edit.get('dimension'))!=(row.document,row.configuration,row.dimension):raise ValueError('physical mapping differs from reviewed change')
    # The supplied native port must already be in an owned isolated host. Its
    # writer/preflight remain the authority; a review hash grants no COM rights.
    if not protected<=set(mapped):raise ValueError('protected interface mappings missing')
    baseline={}
    with port.writer():
        port.preflight(rows,destination)
        for name in protected:
            baseline[name]=port.read(mapped[name])
            if number(plan['values_mm'][name])!=number(baseline[name]):raise ValueError('protected target differs from native baseline')
        for name,edit in edits.items():
            if name not in mapped or abs(number(port.read(mapped[name]))-edit['before'])>1e-9:raise ValueError('native baseline changed after review')
    result=execute(plan,mappings,port,destination)
    if result.get('execution_status') in {'readback_verified','simulated_pass'}:
        with port.writer():
            if any(number(port.read(mapped[name]))!=number(value) for name,value in baseline.items()):
                result.update(status='failed',error='protected interface changed',recovery_status='review_isolated_work_copy')
    result.update(impact_review_sha256=review['review_sha256'],mechanical_acceptance='unverified')
    return result
