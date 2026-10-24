"""Conservative p248 evidence gate; never edits accept records."""
GOLDEN={'profile_1based':299,'thickness_mm':2.5,'radius_mm':1.0,'angle_degrees':90.0}


def evaluate_p248(accept,verification=None):
    params=accept.get('params',{});issues=[]
    for name,value in GOLDEN.items():
        if params.get(name)!=value:issues.append({'field':name,'expected':value,'observed':params.get(name)})
    if params.get('bend_indices')!=[106,107,108,109] or params.get('bend_index_base')!=0:
        issues.append({'field':'bend_indices','reason':'explicit zero-based golden indices required'})
    if params.get('deepen') is not False:issues.append({'field':'deepen','reason':'golden step0 must not deepen'})
    if accept.get('completed_bend_count')!=4:issues.append({'field':'completed_bend_count','reason':'4 required'})
    if accept.get('rebuild') is not True:issues.append({'field':'rebuild','reason':'explicit native success missing'})
    exit_code=accept.get('exit_code')
    verification=verification or {}
    process='abnormal_exit' if exit_code in (139,-11,-1073741819,3221225477) else ('normal_exit_reported' if exit_code==0 else 'unknown')
    reopen=verification.get('job_outcome')=='ok' and verification.get('rebuilt') is True
    return {'golden_parameters_match':not issues,'issues':issues,
            'generation_evidence':'reported_4_of_4' if accept.get('completed_bend_count')==4 else 'insufficient',
            'reopen_evidence':'separate_verification_reported' if reopen else 'not_established_for_this_artifact',
            'process_evidence':process,'accept_reconstructed':bool(accept.get('accept_reconstruction')),
            'source_equivalence':'unverified_local_patches_not_uploaded',
            'native_regression_gate':'review_required','mechanical_approval':False,
            'note':'Reported evidence is not independent binary/model verification; separate artifact association must be reviewed.'}
