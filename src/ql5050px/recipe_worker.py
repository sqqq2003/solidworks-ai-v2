"""Explicit native recipe dispatch inside existing proved-owned STA workers."""
import json,sys,traceback,hashlib
from pathlib import Path
from .part_recipes import compile_recipe,approval_digest


def run_recipe_job(job,output_dir):
    if sys.platform!='win32':raise RuntimeError('native recipe requires Windows')
    plan=compile_recipe(job['recipe'],job.get('bindings'))
    if plan['pending_confirmation']:raise ValueError('recipe requires confirmation: '+str(plan['pending_confirmation']))
    if job.get('reviewed_digest')!=plan['approval_digest']:raise ValueError('reviewed recipe/bindings digest missing or stale')
    if job.get('bindings',{}).get('template_sha256'):
        template=Path(job['bindings']['template'])
        if hashlib.sha256(template.read_bytes()).hexdigest()!=job['bindings']['template_sha256']:raise ValueError('template changed after review')
    if plan['backend']=='feature_ir':
        from .native_part_host import run_native_part
        return run_native_part(job['sw_exe'],job['bindings']['template'],plan,output_dir)
    from sw_session import run_on_task_sta,current_lease
    from sw_owned_launch import owned_solidworks
    from .staged_modeling import Journal,atomic_checkpoint
    def work():
        root=Path(output_dir).resolve();root.mkdir(parents=True,exist_ok=False)
        journal=Journal(root/'stages.jsonl');result={'modeling':'not_started','cleanup':'not_started','native_acceptance':'pending_windows_validation'}
        try:
            with owned_solidworks(Path(job['sw_exe'])):
                journal.record('session','owned',backend=plan['backend'])
                if plan['backend']=='turned_generator':
                    from turned_part import TurnedPartPlan,generate_turned_part
                    from part_verification import verify_saved_part
                    from .native_machine import NativeMachineDriver
                    import solidworks_generator as sw
                    driver=NativeMachineDriver(current_lease(),root);driver.guard()
                    p=plan['payload']
                    turned=TurnedPartPlan(p['axis'],0,'explicit reviewed recipe',tuple(tuple(x) for x in p['profile_mm']),(),())
                    output=root/'part.SLDPRT'
                    result['last_durable_phase']='before_turned_generator'
                    atomic_checkpoint(root/'checkpoint.json',result)
                    journal.record('generator','started')
                    generate_turned_part(turned,str(output))
                    if not output.is_file() or not output.stat().st_size:raise RuntimeError('turned generator produced no saved artifact')
                    result.update(output=str(output),modeling='saved_pending_reopen',sha256=hashlib.sha256(output.read_bytes()).hexdigest(),last_durable_phase='generator_returned_saved_artifact')
                    atomic_checkpoint(root/'checkpoint.json',result)
                    journal.record('save','saved',sha256=result['sha256'],bytes=output.stat().st_size)
                    journal.record('reopen_verification','started')
                    diameter=max(point[1] for point in p['profile_mm'])*2
                    length=max(point[0] for point in p['profile_mm'])
                    verify=verify_saved_part(output,expected_dims_mm=[length,diameter,diameter],expected_body_count=1)
                    result.update(output=str(output),readback=verify)
                else:
                    import ezdxf
                    from cad_analyzer import analyze_cad_file
                    from sheet_metal_pipeline import build_plan,run_plan
                    from sheet_metal_windows import WindowsSheetMetalPort
                    p=plan['payload'];source=root/'synthetic-recipe.dxf'
                    doc=ezdxf.new('R2010');doc.units=4;space=doc.modelspace()
                    space.add_lwpolyline([(0,0),(p['length_mm'],0),(p['length_mm'],p['width_mm']),(0,p['width_mm'])],close=True)
                    doc.layers.new('BEND',dxfattribs={'color':1})
                    for x in p['bend_positions_mm']:space.add_line((x,0),(x,p['width_mm']),dxfattribs={'layer':'BEND'})
                    doc.saveas(source);analysis=analyze_cad_file(source)
                    native_plan=build_plan(analysis,profile_index=0,thickness_mm=p['thickness_mm'],radius_mm=p['radius_mm'],
                        angle_degrees=p['angle_deg'],k_factor=p['k_factor'],flip_direction=p['flip_direction'],
                        units_confirmed=True,bends_confirmed=True,relief_bend_indices=p['relief_bend_indices'])
                    if len(native_plan['bend_indices'])!=2:raise RuntimeError('analyzer did not resolve the exact two recipe bends')
                    receipt=run_plan(analysis,native_plan,root/'sheet',WindowsSheetMetalPort())
                    if receipt.get('status')!='native_features_verified':raise RuntimeError('sheet pipeline not natively verified')
                    result.update(output=str(Path(receipt['output_dir'])/'part.SLDPRT'),sheet=receipt)
                    journal.record('sheet','saved_reopened_flat_exported',result=receipt)
                result.update(modeling='saved_reopened',cleanup='owned_document_closed')
                journal.record('modeling','saved_reopened')
                # Write before session exit: exit failures cannot erase modeling evidence.
                result['process_exit']='pending_external_observation'
                atomic_checkpoint(root/'checkpoint.json',result)
            journal.record('session_context','returned')
        except Exception as exc:
            result.update(error=str(exc),modeling='failed' if result['modeling']!='saved_reopened' else result['modeling'],cleanup='needs_review')
            journal.record('worker','failed',error=str(exc),last_durable_phase=result.get('last_durable_phase'),traceback=traceback.format_exc())
        finally:
            atomic_checkpoint(root/'checkpoint.json',result)
        return result
    return run_on_task_sta(work,timeout=900,task_name='reviewed-recipe')

