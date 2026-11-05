"""Callable native inspect/apply entries with the existing durable CAD runner."""
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
import sys
import traceback
import math

from cad_checkpoint import digest_file
from cad_run import run_receipted_cad, note_owned_process
from drawing_review import atomic_json
from sw_api.mapping import load_mappings
from .workflow import verify_edit_workspace, checked_approval


def implementation_hashes():
    from modeling_domain.api import implementation_hashes as existing
    result=existing();root=Path(__file__).resolve().parents[1]
    for p in Path(__file__).parent.glob('*.py'):
        result[p.relative_to(root).as_posix()]=digest_file(p)
    for name in ('parametric_workspace.py','design_platform/native.py','design_review/impact.py',
                 'sw_api/transaction.py','sw_api/mapping.py'):
        result[name]=digest_file(root/name)
    return result


def _preflight(sw_exe, source, configuration, output, request_key, session_mode):
    if sys.platform!='win32':raise RuntimeError('Windows SolidWorks required; cloud only prepares and simulates')
    source=Path(source).expanduser().resolve(strict=True)
    if not source.is_file() or source.suffix.casefold()!='.sldprt':raise ValueError('existing standalone SLDPRT required')
    if not isinstance(configuration,str) or not configuration.strip():raise ValueError('explicit active configuration required')
    if not isinstance(request_key,str) or not request_key.strip():raise ValueError('explicit request key required')
    executable=Path(sw_exe).expanduser().resolve(strict=True)
    if not executable.is_file() or executable.name.casefold()!='sldworks.exe':raise ValueError('installed SLDWORKS.exe required')
    if session_mode not in {'auto','dedicated','idle_existing'}:raise ValueError('explicit native session mode required')
    return executable,source,Path(output).expanduser().resolve()


def _close(port):
    if port.host.model is not None:port.close_for_restore({str(port.path.resolve())})


def inspect_native_part(source_document, configuration, sw_exe, output, *, request_key,
                        dimension_names=(), session_mode='auto', state_db=None):
    executable,source,root=_preflight(sw_exe,source_document,configuration,output,request_key,session_mode)
    names=list(dimension_names)
    if len(names)>128 or any(not isinstance(n,str) or '@' not in n for n in names):
        raise ValueError('at most 128 explicit dimension names')
    originals={str(source):digest_file(source)}
    payload={'kind':'parametric_inspection','configuration':configuration,'dimensions':names,
             'output':str(root),'session_mode':session_mode,'sw_exe':str(executable)}
    def job():
        from sw_session import current_lease
        from ql5050px.native_part_host import NativePartHost
        from .native import FunctionModelPort
        from .session import modeling_session
        root.mkdir(parents=True,exist_ok=False)
        with modeling_session(executable,session_mode) as binding:
            lease=current_lease();note_owned_process(lease)
            port=FunctionModelPort(NativePartHost(lease,root,source),originals=originals)
            try:
                port.isolate(source,configuration)
                snapshot=port.inspect(source,configuration,names)
                atomic_json(root/'inspection.json',snapshot,exclusive=True)
                result={'status':'inspection_complete','inspection':snapshot,'cad_executed':False,
                        'parameter_write_attempted':False,'manufacturing_approved':False}
            except Exception as error:
                result={'status':'inspection_failed_no_writes','error':str(error),
                        'traceback':traceback.format_exc(),'parameter_write_attempted':False,
                        'cad_executed':False,'manufacturing_approved':False}
            finally:_close(port)
        result['session']=binding.evidence()
        atomic_json(root/'inspection-result.json',result,exclusive=True)
        return result
    return run_receipted_cad(source,originals,payload,job,timeout=900,task_name='parameter-dimension-inspect',
        implementation_hashes=implementation_hashes(),success_statuses={'inspection_complete'},
        safe_failure_statuses={'inspection_failed_no_writes'},state_db=state_db,key=request_key)


def _native_mappings(edit, original_payload):
    result=[]
    changed={c['parameter'] for c in edit['changes'] if c['protected'] or not math.isclose(c['before_mm'],c['after_mm'],rel_tol=0,abs_tol=1e-9)}
    for mapping in load_mappings(original_payload):
        if mapping.parameter not in changed:continue
        row=asdict(mapping)
        row['unit']='mm'
        row['allowed_range']=next(c['allowed_range'] for c in edit['changes'] if c['parameter']==mapping.parameter)
        result.append(row)
    return {'schema_version':1,'parameters':result}


def execute_edit_workspace(directory, sw_exe, output, *, approval_sha256, request_key,
                           session_mode='auto', state_db=None, fault_test=None):
    root,manifest,edit,impact,inspection=verify_edit_workspace(directory)
    approval=checked_approval(root,manifest,impact,approval_sha256)
    if inspection.get('simulated_only') is not False:raise ValueError('a simulated inspection cannot authorize native execution')
    executable,source,destination=_preflight(sw_exe,edit['source_document'],edit['configuration'],output,request_key,session_mode)
    if destination==root or root.is_relative_to(destination) or destination.is_relative_to(root):
        raise ValueError('native output must be a separate new directory outside the review workspace')
    from project_delivery import read_json
    mappings=_native_mappings(edit,read_json(root/'mappings.json'))
    originals={str(source):edit['source_sha256']}
    payload={'kind':'reviewed_parameter_edit','workspace_id':manifest['workspace_id'],
             'approval_sha256':approval_sha256,'edit':edit,'output':str(destination),
             'session_mode':session_mode,'sw_exe':str(executable)}
    if fault_test is not None:
        if fault_test!='after_saved_parameter_batch':raise ValueError('unknown explicit fault test')
        payload['fault_test']=fault_test
    def job():
        from sw_session import current_lease
        from ql5050px.native_part_host import NativePartHost
        from design_platform.native import execute_reviewed_transaction
        from modeling_domain.transaction import feature_map
        from .native import FunctionModelPort,DimensionExecutionPort
        from .session import modeling_session
        verify_edit_workspace(root)
        destination.mkdir(parents=True,exist_ok=False)
        adapter=None
        with modeling_session(executable,session_mode) as binding:
            lease=current_lease();note_owned_process(lease)
            port=FunctionModelPort(NativePartHost(lease,destination,source),originals=originals)
            try:
                port.isolate(source,edit['configuration'])
                baseline=port.inspect(source,edit['configuration'],[c['dimension'] for c in edit['changes']])
                # Full inspection can include more dimension candidates; compare
                # the entire feature/body baseline plus every selected dimension.
                if baseline['inventory']!=inspection['inventory']:
                    raise ValueError('native geometry/tree baseline changed since review')
                measured={r['name']:r for r in baseline['dimensions']}
                original={r['name']:r for r in inspection['dimensions']}
                if any(measured.get(c['dimension'])!=original.get(c['dimension']) for c in edit['changes']):
                    raise ValueError('native mapped dimension baseline changed since review')
                adapter=DimensionExecutionPort(port,edit,baseline)
                result=execute_reviewed_transaction(edit,edit['design_intentions'],approval,mappings,
                                                     adapter,str(port.path))
                if adapter.rollback is not None:result['rollback']=adapter.rollback
                if result.get('execution_status')=='readback_verified':
                    result.update(status='native_parameter_edit_pending_review',revision=port.revision(),
                                  inventory=adapter.verify_inventory(),model_path=str(port.path),
                                  model_sha256=digest_file(port.path))
                elif result.get('execution_status')=='no_changes':result['status']='edit_preflight_failed_no_writes'
                result['workspace_id']=manifest['workspace_id']
                result['review_sha256']=impact['review_sha256']
            except Exception as error:
                if adapter is None:
                    result={'status':'edit_preflight_failed_no_writes','error':str(error),
                            'traceback':traceback.format_exc(),'cad_executed':False}
                else:
                    # Errors outside the existing transaction may have unknown
                    # side effects; never claim rollback based on appearance.
                    port.quarantine('OUTCOME_UNKNOWN')
                    atomic_json(destination/'unresolved-error.json',{'error':str(error),'traceback':traceback.format_exc()},exclusive=True)
                    raise
            finally:_close(port)
        result.update(session=binding.evidence(),manufacturing_approved=False,delivery_accepted=False,
                      mechanical_acceptance='unverified',acceptance_state='reviewing')
        atomic_json(destination/'parameter-edit-result.json',result,exclusive=True)
        return result
    return run_receipted_cad(source,originals,payload,job,timeout=900,task_name='reviewed-parameter-edit',
        implementation_hashes=implementation_hashes(),success_statuses={'native_parameter_edit_pending_review'},
        safe_failure_statuses={'edit_preflight_failed_no_writes'},state_db=state_db,key=request_key)
