"""Evidence-linked repair proposals. No guessed geometry or automatic COM writes."""

def propose_repairs(assessment):
    actions=[]
    templates={
        'owned_session':('prepare_dedicated_owned_session','preserve operator work; rerun existing owned launcher; never attach an arbitrary active session'),
        'dimensions':('review_dimension_mapping','compare mapped native dimensions, units and intended overall length before proposing any edit'),
        'protected_interfaces':('restore_isolated_copy_from_baseline','discard/archive only the failed isolated variant; preserve source; review protected mappings'),
        'feature_tree':('inspect_failed_feature','use feature ID and chained traceback to locate the failed feature; do not suppress rebuild errors'),
        'rebuild':('inspect_failed_feature','review native rebuild errors and stable references before rebuilding an isolated copy'),
        'references':('recreate_isolated_dependency_set','repeat reviewed Pack-and-Go/reference audit into a new directory'),
        'save_reopen':('inspect_saved_artifact_and_session','retain saved bytes and checkpoint; inspect reopen error and process ownership before retry'),
        'process_exit':('investigate_owned_process_lifecycle','retain exit code, PID and phase logs; no process-name kill or guessed success'),
        'sheet_parameters':('confirm_per_job_bend_inputs','verify explicit thickness/radius/angle/K or approved BA/BD; never fill shop defaults'),
        'flat_pattern':('inspect_native_flat_pattern','review native bend/flat failures and geometric readback; no cosmetic substitute'),
        'mates':('review_mate_references','review the affected mate entities/configuration and native status'),
        'interference':('review_collision_pairs','inspect component pairs and collision volumes before planning a geometry change'),
        'motion':('review_motion_constraints','review limits, drive relationships and samples; discrete checks do not prove continuous motion'),
        'manufacturing':('review_manufacturing_data','confirm materials, datum/tolerance, drawing references and BOM revision consistency')}
    for row in assessment.get('checks',[]):
        if row.get('status') in {'passed','not_applicable'}:continue
        method,detail=templates.get(row['id'],('manual_evidence_review','inspect the missing or failing evidence before proposing a repair'))
        actions.append({'check':row['id'],'trigger_status':row.get('status'),'action':method,'instruction':detail,
            'evidence_reason':row.get('reason'),'requires_review':True,'automatic_execution_allowed':False})
    return {'status':'review_required' if actions else 'no_repair_proposed','proposals':actions,
        'run_id':assessment.get('run_id'),'source_revision':assessment.get('source_revision'),
        'cad_executed':False,'scope':'repair proposals only; no native corrective action executed'}
