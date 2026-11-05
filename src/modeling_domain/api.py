"""Attach to one running SolidWorks and model in a new directory.

Existing user documents stay open. This entry does not start another
SLDWORKS, call ExitApp, or terminate a process.
"""
from copy import deepcopy
from pathlib import Path
import sys
import platform
import struct
from importlib.metadata import version, PackageNotFoundError

from cad_checkpoint import digest_file
from cad_run import note_owned_process, run_receipted_cad
from drawing_review import atomic_json
from .contract import analyze_draft
from .transaction import run_transaction, observe, body_clearance


def runtime_environment():
    """Record runtime versions without collecting user environment variables."""
    try:
        pywin32_version=version('pywin32')
    except PackageNotFoundError:
        pywin32_version=None
    return {'python':platform.python_version(), 'implementation':platform.python_implementation(),
            'python_bits':struct.calcsize('P')*8, 'os':platform.system(),
            'os_release':platform.release(), 'os_version':platform.version(),
            'machine':platform.machine(), 'pywin32':pywin32_version}


def implementation_hashes():
    root = Path(__file__).resolve().parents[1]
    names = ['cad_run.py', 'cad_checkpoint.py', 'cad_receipts.py', 'sw_session.py',
             'sw_owned_launch.py', 'sw_feature_calls.py', 'solidworks_generator.py',
             'sw_compat/com_access.py', 'ql5050px/native_part_host.py',
             'ql5050px/native_machine.py', 'ql5050px/editable_features.py',
             'ql5050px/feature_operations.py', 'ql5050px/com_selection.py',
             'a01_next/native_production.py', 'profile_sanitize.py',
             'modeling_domain/contract.py', 'modeling_domain/transaction.py',
             'modeling_domain/native.py', 'modeling_domain/dimension_edit.py', 'modeling_domain/api.py']
    return {name: digest_file(root / name) for name in names}


def run_native_modeling(plan, sw_exe, template, output_dir, *, expected_template_sha256,
                        reviewed_plan_sha256, request_key, camera='isometric',
                        clearance_pairs=(), state_db=None, timeout=900):
    if sys.platform != 'win32':
        raise RuntimeError('Windows SolidWorks required; cloud results are simulations only')
    draft = analyze_draft(plan)
    if draft['status'] != 'draft_ready' or reviewed_plan_sha256 != draft['plan_sha256']:
        raise ValueError('conflict-free reviewed plan SHA256 required')
    template = Path(template).expanduser().resolve()
    if not template.is_file() or template.suffix.lower() != '.prtdot':
        raise ValueError('explicit existing empty part template required')
    if digest_file(template) != expected_template_sha256:
        raise ValueError('template changed since review')
    if not isinstance(request_key, str) or not request_key.strip():
        raise ValueError('explicit request key required')
    if camera not in {'front', 'top', 'right', 'isometric'}:
        raise ValueError('camera outside whitelist')
    plan = deepcopy(draft['plan'])
    pairs = list(clearance_pairs)
    names = set(plan['features'][-1]['expected']['body_names'])
    if len(pairs) > 16 or any(not isinstance(p, (list, tuple)) or len(p) != 2
                              or p[0] == p[1] or not set(p) <= names for p in pairs):
        raise ValueError('up to sixteen explicit final named body pairs required')
    root = Path(output_dir).expanduser().resolve()
    if root == template:
        raise ValueError('output cannot be the template')
    originals = {str(template): expected_template_sha256}
    payload = {'domain': 'modeling', 'plan': plan, 'reviewed_plan_sha256': reviewed_plan_sha256,
               'expected_template_sha256': expected_template_sha256, 'output_dir': str(root),
               'sw_exe': str(Path(sw_exe).resolve()), 'camera': camera, 'clearance_pairs': pairs}

    def job():
        from sw_session import current_lease
        # CloseDoc-only acceptance attaches to one existing SLDWORKS.
        # It does not start another process.
        from sw_owned_launch import attached_solidworks
        from ql5050px.native_part_host import NativePartHost
        from .native import NativeModelingPort
        if digest_file(template) != expected_template_sha256:
            raise ValueError('template changed before launch')
        root.mkdir(parents=True, exist_ok=False)
        atomic_json(root / 'runtime-environment.json', runtime_environment(), exclusive=True)
        with attached_solidworks(Path(sw_exe)) as binding:
            lease = current_lease()
            note_owned_process(lease)
            port = NativeModelingPort(NativePartHost(lease, root, template), originals=originals)
            try:
                revision = port.initialize()
                baseline_draft = analyze_draft(plan, revision=revision, inventory=port.inventory())
                atomic_json(root / 'analysis.json', baseline_draft, exclusive=True)
                result = run_transaction(plan, port, expected_revision=revision,
                                         reviewed_plan_sha256=reviewed_plan_sha256)
                # Persist the geometry/save/reopen outcome before optional view
                # work, so a camera failure cannot hide successful model readback.
                atomic_json(root / 'model-transaction-result.json', result, exclusive=True)
                if result['status'] == 'native_readback_pending_review':
                    result['observation'] = observe(port, expected_revision=result['revision'],
                                                    directory=root / 'observation', camera=camera)
                    result['clearances'] = [body_clearance(port, *pair,
                        expected_revision=result['revision']) for pair in pairs]
                result['baseline_revision'] = revision
                result['reviewed_plan_sha256'] = reviewed_plan_sha256
                result['template_sha256'] = expected_template_sha256
                result['model_sha256'] = digest_file(port.path)
                result['model_path'] = str(port.path)
            except BaseException as error:
                import traceback
                failure={'error':type(error).__name__+': '+str(error),
                         'traceback':traceback.format_exc(),
                         'camera_comparison':getattr(port,'camera_comparison',None),
                         'manufacturing_approved':False}
                atomic_json(root / 'native-failure.json',failure,exclusive=True)
                raise
            finally:
                if port.host.model is not None:
                    if sys.exc_info()[0] is not None:
                        # Preserve the primary error if the quarantined lease
                        # also refuses cleanup. Never relax its write guard.
                        try:port.close_for_restore({str(port.path.resolve())})
                        except Exception as cleanup:
                            atomic_json(root/'cleanup-failure.json',{'error':str(cleanup)},exclusive=True)
                    else:port.close_for_restore({str(port.path.resolve())})
        result['session'] = binding.evidence()
        atomic_json(root / 'native-result.json', result, exclusive=True)
        return result

    return run_receipted_cad(template, originals, payload, job, timeout=timeout,
        task_name='bounded-modeling', implementation_hashes=implementation_hashes(),
        success_statuses={'native_readback_pending_review'}, state_db=state_db, key=request_key)
