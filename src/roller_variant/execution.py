"""Isolated transaction shared by the native host and explicitly fake checks."""
import json,math,os,traceback
from pathlib import Path
from .planning import plan_variant


def execute_variant(request,driver,destination):
    root=Path(destination).resolve();root.mkdir(parents=True,exist_ok=False)
    report={'schema_version':1,'status':'running','phases':[],'cad_executed':False,
        'native_acceptance':'pending_windows_validation','mechanical_acceptance':'unverified','process_exit':'pending_external_observation'}
    def record(name,data):
        report['phases'].append({'name':name,'result':data})
        temporary=root/'checkpoint.new'
        with temporary.open('w',encoding='utf-8') as f:
            json.dump(report,f,ensure_ascii=False,indent=2,allow_nan=False);f.flush();os.fsync(f.fileno())
        temporary.replace(root/'checkpoint.json')
    checkpoint=None
    try:
        record('queued',{'source_unchanged':True})
        driver.isolate(request,root/'isolated');record('isolated',{'status':'copied'})
        before=driver.read_all();features=driver.feature_inventory();mechanics=driver.mechanical_inventory()
        plan=plan_variant(request,before);report['plan']=plan
        if plan['status']!='ready_for_native':raise ValueError('roller native execution requires complete mappings/interfaces/dependencies')
        record('planned_from_native_readback',{'plan_sha256':plan['plan_sha256']})
        if hasattr(driver,'checkpoint'):
            checkpoint=driver.checkpoint()
            record('rollback_checkpoint_sealed',{'manifest_sha256':checkpoint.manifest_sha256})
        elif not driver.simulated:
            raise RuntimeError('native writes require a byte checkpoint')
        for change in plan['changes']:
            report['write_attempted']=True
            report['cad_write_attempted']=not driver.simulated
            driver.write(change);report['cad_executed']=not driver.simulated;record('dimension_written',{'parameter':change['parameter'],'after_mm':change['after_mm']})
        driver.rebuild_save();record('rebuilt_saved',{'status':'saved_pending_reopen'})
        driver.reopen();record('reopened',{'status':'opened'})
        after=driver.read_all()
        expected={name:before[name] for name in plan['protected_parameters']}
        expected.update({c['parameter']:c['after_mm'] for c in plan['changes']})
        expected.update(overall_length=plan['target_overall_mm'],left_projection=before['left_projection'],right_projection=before['right_projection'])
        for name,value in expected.items():
            if name not in after or not math.isclose(after[name],value,abs_tol=.01,rel_tol=0):raise RuntimeError('reopened dimension mismatch: '+name)
        if driver.feature_inventory()!=features:raise RuntimeError('feature inventory changed unexpectedly')
        if driver.mechanical_inventory()!=mechanics:raise RuntimeError('mate inventory/status changed; review required')
        envelope=driver.axial_extent(request['axis'])
        if not math.isclose(envelope,plan['target_overall_mm'],abs_tol=.05,rel_tol=0):raise RuntimeError('native axial envelope does not match total length')
        report.update(status='simulated_only' if driver.simulated else 'saved_reopened_readback',cad_executed=not driver.simulated,
            after_mm=after,axial_extent_mm=envelope,verification_scope='mapped_dimensions_feature_inventory_mate_states_and_axis_bounds')
        record('verified',{'overall_mm':after['overall_length'],'axis_bounds_mm':envelope})
    except Exception as exc:
        report.update(status='failed',error=str(exc),traceback=traceback.format_exc(),recovery='preserve isolated output and reconcile request receipt before another write')
        if checkpoint is not None and report.get('write_attempted'):
            try:
                report['rollback']=driver.restore(checkpoint)
            except Exception as recovery:
                report['rollback']={'state':'ROLLBACK_UNCONFIRMED','error':str(recovery),
                                    'manifest_sha256':checkpoint.manifest_sha256}
        record('failed',{'error_type':type(exc).__name__})
    finally:
        try:driver.close();report['cleanup']='owned_documents_closed'
        except Exception as exc:
            report.update(cleanup='needs_review',cleanup_error=str(exc))
            if report['status']!='failed':report.update(prior_status=report['status'],status='needs_review')
        try:
            if hasattr(driver,'artifacts'):report['artifacts']=driver.artifacts()
        except Exception as exc:report['artifact_inventory_error']=str(exc)
        record('cleanup',{'status':report['cleanup']})
    return report
