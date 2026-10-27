"""Shared project jobs for desktop UI and serial batch runner. No shell scripts."""
from __future__ import annotations
import csv
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
import uuid
import threading

ROOT = Path(__file__).resolve().parents[1]
MODES = {'sheet','roller','turned'}


def uses_native_session(job):
    """DWG analysis may import/export in SW even without generating a part."""
    return job.get('kind') in MODES and (job.get('action') in ('generate', 'batch', 'reviewed_batch') or (
        Path(job.get('source', '')).suffix.casefold() == '.dwg' and bool(job.get('sw_exe'))))


def confirm_job(job):
    """Bind review to input bytes and every generation option; return a copy."""
    job = dict(job)
    job['source_sha256'] = hashlib.sha256(Path(job['source']).read_bytes()).hexdigest()
    if job.get('action') == 'reviewed_batch':
        from batch_review_manifest import file_hash, load_manifest
        from parameter_ledger import digest
        manifest_path = Path(job['review_manifest']).resolve(strict=True)
        job['review_manifest'] = str(manifest_path)
        job['review_manifest_sha256'] = file_hash(manifest_path)
        job['review_sha256'] = digest(load_manifest(manifest_path))
    job['confirmed'] = True
    job['confirmation_digest'] = confirmation_digest(job)
    return job


def confirmation_digest(job):
    payload = {k:v for k,v in job.items() if k not in {'confirmed','confirmation_digest','name'}}
    return hashlib.sha256(json.dumps(payload,sort_keys=True,allow_nan=False).encode()).hexdigest()


def bounded_run(command, *, cwd, timeout, **kwargs):
    """Bound UI waiting without killing Python or an owned/unknown SW process.

    A timeout leaves the worker running and a persistent recovery marker. All
    subsequent native jobs refuse until the operator resolves the marker.
    """
    folder = Path(cwd)/'runtime'/'project-workers'
    folder.mkdir(parents=True,exist_ok=True)
    token = uuid.uuid4().hex
    stdout_path, stderr_path = folder/(token+'.stdout'),folder/(token+'.stderr')
    marker = folder/'native.pending.json'
    native = '--sw-exe' in command
    if native:
        try:
            # Reserve before launch; concurrent workbenches cannot both start.
            with marker.open('x',encoding='utf-8') as stream:
                json.dump({'state':'launching','command':command},stream)
        except FileExistsError:
            raise RuntimeError('unresolved native worker: inspect runtime/project-workers before continuing')
    with stdout_path.open('x',encoding='utf-8') as out, stderr_path.open('x',encoding='utf-8') as err:
        try:
            process = subprocess.Popen(command,cwd=cwd,stdout=out,stderr=err,shell=False)
            from app_logging import get_journal
            get_journal().record('worker_started',worker_pid=process.pid,native=native,stdout_file=str(stdout_path),stderr_file=str(stderr_path))
        except Exception:
            if native:
                marker.unlink()
            raise
        if native:
            marker.write_text(json.dumps({'pid':process.pid,'command':command,
                'stdout':str(stdout_path),'stderr':str(stderr_path)}),encoding='utf-8')
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            # Reap only the child process; never terminate it or SolidWorks.
            threading.Thread(target=process.wait,daemon=True).start()
            exc.worker_pid = process.pid
            exc.stdout_path,exc.stderr_path = str(stdout_path),str(stderr_path)
            exc.recovery_marker = str(marker) if native else None
            raise
        else:
            if native:
                marker.unlink()
    return subprocess.CompletedProcess(command,process.returncode,
        stdout_path.read_text(encoding='utf-8',errors='replace'),
        stderr_path.read_text(encoding='utf-8',errors='replace'))


def capabilities():
    return {'project':'SolidWorks AI V2', 'scope':'whole_project',
        'modules':[
            {'id':'cad','state':'implemented','entry':'src/cad_analyzer.py'},
            {'id':'sheet','state':'native_implemented_partial_live','entry':'src/sw_tool_cli.py --mode sheet'},
            {'id':'roller','state':'native_implemented_pending_live','entry':'src/sw_tool_cli.py --mode roller'},
            {'id':'turned','state':'native_implemented_pending_live','entry':'src/sw_tool_cli.py --mode turned'},
            {'id':'parametric','state':'offline_implemented_pending_mapping','entry':'src.a01_parametric.cli'},
            {'id':'ql5050px','state':'offline_implemented_pending_mapping','entry':'work/project.py ql'},
            {'id':'ql_assembly_bom_drawing','state':'offline_implemented_pending_native','entry':'ql5050px.workflow'},
            {'id':'assembly_mates_motion','state':'scaffold_pending_native','entry':'src/a01_next/mate_check.py'},
            {'id':'native_engineering_drawings','state':'scaffold_pending_native','entry':'src/a01_next/drawing_export.py'},
            {'id':'desktop','state':'implemented_pending_desktop_test','entry':'app.py'},
        ], 'mechanical_acceptance':'unverified','pending_original_feature_contracts':36}


def doctor():
    def available(name):
        try:
            return importlib.util.find_spec(name) is not None
        except (ValueError,ModuleNotFoundError):
            return False
    return {'platform':platform.system(),'python':platform.python_version(),
        'python_executable':sys.executable,'ezdxf_available':available('ezdxf'),
        'tkinter_available':available('tkinter'),
        'pywin32_available':available('pythoncom'),
        'sw_started':False,'cad_executed':False,'desktop_display_tested':False,
        'note':'Import availability is not SolidWorks installation or ownership proof.'}


def number(value, name):
    if type(value) not in (float,int) or not math.isfinite(value) or value <= 0:
        raise ValueError(name+' must be finite positive numeric')
    return str(value)


def build_command(job: dict, *, root=ROOT):
    kind = job.get('kind')
    if kind == 'ql5050px' or (kind == 'parametric' and job.get('machine') == 'QL-5050PX'):
        from ql5050px.workflow import ACTIONS
        action = job.get('action','plan')
        if action not in ACTIONS:
            raise ValueError('QL action must be plan/assembly/bom/drawing/pipeline')
        cmd = [sys.executable,'-X','utf8',str(Path(root)/'work/ql5050px.py'),'--action',action]
        if job.get('config'):
            if 'request' in job:
                raise ValueError('choose QL config file or request, not both')
            config = Path(job['config']).expanduser().resolve()
            if not config.is_file() or config.suffix.lower()!='.json':
                raise ValueError('QL configuration must be an existing JSON file')
            cmd.extend(['--config',str(config)])
        else:
            request = job.get('request',{})
            if kind=='parametric':
                request = {'machine':'QL-5050PX','envelope':{k:float(number(job.get(k),k)) for k in ('length','width','height')}}
            if not isinstance(request,dict):
                raise ValueError('QL request must be an object')
            cmd.extend(['--request-json',json.dumps(request,ensure_ascii=False,allow_nan=False)])
        if job.get('output_dir'):
            output = Path(job['output_dir']).expanduser().resolve()
            if output.exists() and not (action=='pipeline' and job.get('resume') is True):
                raise ValueError('QL output directory already exists')
            cmd.extend(['--output-dir',str(output)])
        elif action in {'pipeline','machine_package'}:
            raise ValueError('QL pipeline/machine_package requires output_dir')
        if job.get('resume'):
            if action!='pipeline':
                raise ValueError('QL resume requires pipeline action')
            cmd.append('--resume')
        return cmd
    if kind == 'parametric':
        if job.get('machine') != 'GT-ZX':
            raise ValueError('legacy parametric planner requires machine=GT-ZX; QL-5050PX uses the separate QL pipeline (PR #7)')
        cmd = [sys.executable,'-X','utf8','-m','src.a01_parametric.cli']
        for key in ('length','width','height'):
            cmd.extend(['--'+key,number(job.get(key),key)])
        return cmd  # Parameter planning only; never silently run a live assembly.
    if kind not in MODES:
        raise ValueError('unknown job kind')
    action = job.get('action','analyze')
    if action not in {'analyze','plan','generate','batch','reviewed_batch'}:
        raise ValueError('unknown action')
    source = Path(job['source']).expanduser().resolve()
    if not source.is_file() or source.suffix.casefold() not in {'.dwg','.dxf'}:
        raise ValueError('source must be an existing DWG/DXF file')
    if action == 'reviewed_batch':
        from batch_review_manifest import file_hash, load_manifest, validate_manifest
        from parameter_ledger import digest
        if kind != 'sheet' or source.suffix.casefold() != '.dxf':
            raise ValueError('reviewed batch requires sheet kind and DXF')
        if (job.get('confirmed') is not True or job.get('source_sha256') != file_hash(source)
                or job.get('confirmation_digest') != confirmation_digest(job)):
            raise ValueError('reviewed source/options changed; confirm current job')
        manifest_path = Path(job['review_manifest']).resolve(strict=True)
        manifest = load_manifest(manifest_path)
        if job.get('review_manifest_sha256') != file_hash(manifest_path) or job.get('review_sha256') != digest(manifest):
            raise ValueError('review manifest changed after confirmation')
        review = validate_manifest(manifest, source=source)
        if review['blockers']:
            raise ValueError('review manifest incomplete: ' + ', '.join(review['blockers']))
        executable = Path(job.get('sw_exe', '')).resolve()
        if not executable.is_file() or executable.name.casefold() != 'sldworks.exe':
            raise ValueError('installed SLDWORKS.exe required for reviewed batch')
        if not job.get('output_dir') or Path(job['output_dir']).resolve().exists():
            raise ValueError('reviewed batch requires a new output directory')
        return [sys.executable, '-X', 'utf8', str(Path(root) / 'work/run_reviewed_batch.py'),
                '--manifest', str(manifest_path), '--source', str(source),
                '--out-dir', str(Path(job['output_dir']).resolve()), '--review-sha256', job['review_sha256'],
                '--execute-reviewed', '--sw-exe', str(executable),
                '--timeout-seconds', number(job.get('timeout_seconds', 600), 'timeout_seconds')]
    cmd = [sys.executable,'-X','utf8',str(Path(root)/'src/sw_tool_cli.py'),
           '--mode',kind,'--input',str(source)]
    if action == 'batch':
        # 一键批量导出：串行导出整张图的全部钣金外轮廓到新目录。
        if kind != 'sheet':
            raise ValueError('batch action only supports sheet kind')
        if job.get('confirmed') is not True:
            raise ValueError('review identified geometry and parameters before native batch export')
        if (not job.get('source_sha256') or
                hashlib.sha256(source.read_bytes()).hexdigest() != job['source_sha256'] or
                job.get('confirmation_digest') != confirmation_digest(job)):
            raise ValueError('source or options changed since review; confirm the current job again')
        executable = Path(job.get('sw_exe','')).expanduser().resolve()
        if not executable.is_file() or executable.name.casefold() != 'sldworks.exe':
            raise ValueError('native batch export requires installed SLDWORKS.exe')
        out_dir = job.get('output_dir')
        if not out_dir:
            raise ValueError('batch export requires output_dir')
        out_path = Path(out_dir).expanduser().resolve()
        if out_path.exists() and any(out_path.iterdir()):
            raise ValueError('batch output directory already exists and is not empty')
        cmd.extend(['--batch','--batch-out-dir',str(out_path),
                    '--sw-exe',str(executable)])
        for key in ('thickness','radius','angle'):
            cmd.extend(['--'+key,number(job.get(key),key)])
        k = job.get('k_factor')
        if k is not None:
            if type(k) not in (int,float) or not math.isfinite(k) or not 0 <= k <= 1:
                raise ValueError('explicit K factor from 0 to 1 required for batch')
            cmd.extend(['--k-factor', str(k)])
        labels = job.get('selected_labels')
        if labels is not None:
            if not isinstance(labels, (list, tuple)) or not labels or any(not isinstance(x, str) or not x for x in labels):
                raise ValueError('nonempty explicit batch selection required')
            for label in labels:
                cmd.extend(['--batch-label', label])
        if 'uniform_scale' in job:
            cmd.extend(['--uniform-scale', number(job['uniform_scale'], 'uniform_scale')])
        if job.get('preserve_circle_holes') is True:
            if 'uniform_scale' not in job:
                raise ValueError('circle preservation requires explicit scale')
            cmd.append('--preserve-circle-holes')
        if job.get('flip') is True:
            cmd.append('--flip')
        return cmd
    if action == 'analyze':
        cmd.append('--analyze-only')
    elif action == 'plan':
        cmd.append('--plan-only')
    else:
        if job.get('confirmed') is not True:
            raise ValueError('review identified geometry and parameters before native generation')
        if (not job.get('source_sha256') or
                hashlib.sha256(source.read_bytes()).hexdigest() != job['source_sha256'] or
                job.get('confirmation_digest') != confirmation_digest(job)):
            raise ValueError('source or options changed since review; confirm the current job again')
        executable = Path(job.get('sw_exe','')).expanduser().resolve()
        if not executable.is_file() or executable.name.casefold() != 'sldworks.exe':
            raise ValueError('native generation requires installed SLDWORKS.exe')
        output = Path(job['output']).expanduser().resolve()
        if output == source or output.exists() or output.suffix.casefold() != '.sldprt':
            raise ValueError('output must be a new .SLDPRT path, distinct from source')
        cmd.extend(['--out',str(output),'--sw-exe',str(executable),'--verify-reopen'])
    if action in {'analyze','plan'} and source.suffix.casefold() == '.dwg' and job.get('sw_exe'):
        executable = Path(job['sw_exe']).expanduser().resolve()
        if not executable.is_file() or executable.name.casefold() != 'sldworks.exe':
            raise ValueError('DWG conversion requires an installed SLDWORKS.exe, or clear the path to use LibreDWG/DXF')
        cmd.extend(['--sw-exe',str(executable)])
    if kind == 'sheet' and action != 'analyze':
        for key in ('thickness','radius','angle'):
            cmd.extend(['--'+key,number(job.get(key),key)])
        k = job.get('k_factor')
        if type(k) not in (int,float) or not math.isfinite(k) or not 0 <= k <= 1:
            raise ValueError('explicit K factor from 0 to 1 required')
        cmd.extend(['--k-factor',str(k)])
        if type(job.get('profile')) is not int or job['profile'] < 1:
            raise ValueError('sheet profile is one-based, positive integer')
        cmd.extend(['--profile',str(job['profile'])])
        if 'uniform_scale' in job:
            factor=job['uniform_scale']
            if type(factor) not in (int,float) or not math.isfinite(factor) or factor<=0:
                raise ValueError('等比例缩放倍数必须大于零')
            cmd.extend(['--uniform-scale',str(factor)])
        if job.get('preserve_circle_holes') is True:
            if 'uniform_scale' not in job:raise ValueError('保持孔径需要填写缩放倍数')
            cmd.append('--preserve-circle-holes')
        if job.get('flip') is True:
            cmd.append('--flip')
    if kind == 'roller' and job.get('allow_inferred') is True:
        cmd.append('--allow-inferred')
    if kind in {'roller','turned'}:
        variant = job.get('variant',0)
        if type(variant) is not int or variant < 0:
            raise ValueError('variant is a nonnegative zero-based integer')
        cmd.extend(['--variant',str(variant)])
    return cmd


def execute_job(job, *, root=ROOT, runner=bounded_run):
    from app_logging import get_journal
    journal=get_journal();job_id=uuid.uuid4().hex[:16];journal.record('job_started',job_id=job_id,job=job)
    started = time.monotonic()
    base = {'name':job.get('name',job.get('kind','job')),'kind':job.get('kind'),
            'mechanical_acceptance':'unverified','cad_verified':False}
    try:
        command = build_command(job,root=root)
        native = uses_native_session(job)
        if native and sys.platform != 'win32':
            raise RuntimeError('native SolidWorks conversion/generation requires Windows; use DXF or LibreDWG on cloud')
        # No shell interpolation, environment dump or automatic native-process kill.
        timeout = job.get('timeout_seconds',600)
        number(timeout,'timeout_seconds')
        completed = runner(command,cwd=root,capture_output=True,text=True,encoding='utf-8',errors='replace',shell=False,timeout=timeout)
        events, raw = [], []
        for line in completed.stdout.splitlines():
            try:
                event = json.loads(line)
                if isinstance(event,dict):
                    events.append(event)
                else:
                    raw.append(line)
            except ValueError:
                raw.append(line)
        if job.get('kind') == 'parametric' and not events:
            try:
                payload = json.loads(completed.stdout)
                if isinstance(payload,dict) and isinstance(payload.get('plan'),dict):
                    events.append({'event':'plan','kind':'parametric','plan':payload['plan'],'cad_executed':False})
            except ValueError:
                pass
        errors = [e for e in events if e.get('event') == 'error']
        done = next((e for e in reversed(events) if e.get('event') in {'done','plan','analysis'}),None)
        if completed.returncode not in (0,3) or errors:
            status = 'failed'
        elif done is not None and done.get('kind')=='ql5050px':
            status = 'pending_mapping' if done.get('status')=='pending_mapping' else 'review_required'
        elif job.get('kind') == 'parametric' and done is not None:
            status = 'review_required' if completed.returncode == 3 else 'planned'
        elif done is None:
            status = 'failed'  # No success from rc=0 alone.
        elif done.get('event') == 'analysis':
            status = 'analyzed'
        elif done.get('event') == 'plan':
            status = 'review_required' if completed.returncode == 3 else 'planned'
        elif done.get('status') == 'degraded' or completed.returncode == 3:
            status = 'review_required'
        else:
            status = 'generated_unverified'
            if (done.get('reopen') or {}).get('status') == 'reopen_geometry_verified':
                status = 'reopen_geometry_verified'
        result = {**base,'status':status,'returncode':completed.returncode,'events':events,
                  'stderr':completed.stderr,'non_json_output':raw,'command':command,
                  'elapsed_seconds':round(time.monotonic()-started,3)}
        if job.get('action') == 'generate' and job.get('kind') in MODES and status != 'failed':
            output = Path(job['output']).resolve()
            if not output.is_file() or output.stat().st_size == 0:
                raise RuntimeError('generation reported success without a nonempty product')
            result['artifact'] = {'path':str(output),'sha256':hashlib.sha256(output.read_bytes()).hexdigest()}
            result['cad_verified'] = status == 'reopen_geometry_verified'
        journal.record('job_finished',job_id=job_id,level='ERROR' if status=='failed' else 'INFO',status=status,returncode=completed.returncode,
                       elapsed_seconds=result['elapsed_seconds'],artifact=result.get('artifact'),stderr=completed.stderr,errors=errors)
        return result
    except subprocess.TimeoutExpired as exc:
        journal.exception('job_timed_out',exc,job_id=job_id,worker_pid=getattr(exc,'worker_pid',None))
        return {**base,'status':'timed_out','error':'worker wait limit reached; worker was NOT terminated',
                'worker_pid':getattr(exc,'worker_pid',None),
                'stdout_file':getattr(exc,'stdout_path',None),'stderr_file':getattr(exc,'stderr_path',None),
                'recovery_marker':getattr(exc,'recovery_marker',None),'worker_may_be_running':True,
                'elapsed_seconds':round(time.monotonic()-started,3)}
    except Exception as exc:
        journal.exception('job_failed',exc,job_id=job_id)
        return {**base,'status':'failed','error':str(exc),'elapsed_seconds':round(time.monotonic()-started,3)}


def run_batch(jobs, *, execute=execute_job, stop_requested=lambda:False):
    if not isinstance(jobs,list) or not jobs:
        raise ValueError('nonempty jobs array required')
    # Preflight every command before the first native side effect.
    outputs = set()
    for job in jobs:
        build_command(job)
        if job.get('output_dir'):
            output = str(Path(job['output_dir']).resolve()).casefold()
            if output in outputs:
                raise ValueError('duplicate output directory in batch')
            outputs.add(output)
        if job.get('action') == 'generate':
            output = str(Path(job['output']).resolve()).casefold()
            if output in outputs:
                raise ValueError('duplicate native output path in batch')
            outputs.add(output)
    results = []
    blocked = False
    for job in jobs:
        if blocked or stop_requested():
            results.append({'name':job.get('name',job['kind']),'kind':job['kind'],
                'status':'not_run','reason':'queue stopped after current job','cad_verified':False})
            continue
        result = execute(job)
        results.append(result)
        # Never continue CAD writes after an unknown native failure.
        if result['status'] == 'timed_out' or (uses_native_session(job) and result['status'] == 'failed'):
            blocked = True
    counts = {state:sum(r['status']==state for r in results) for state in sorted({r['status'] for r in results})}
    return {'schema_version':1,'status':'failed' if counts.get('failed') or counts.get('timed_out') else (
        'review_required' if counts.get('review_required') or counts.get('pending_mapping') or counts.get('not_run') else 'completed'),
        'results':results,'counts':counts,'mechanical_acceptance':'unverified'}


def write_report(report, folder):
    folder = Path(folder).resolve()
    folder.mkdir(parents=True,exist_ok=True)
    path = folder/('project-report-'+uuid.uuid4().hex+'.json')
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    with path.with_suffix('.csv').open('w',newline='',encoding='utf-8-sig') as stream:
        writer = csv.writer(stream)
        writer.writerow(['name','kind','status','returncode','artifact','cad_verified'])
        for row in report.get('results',[]):
            values = [row.get('name',''),row.get('kind',''),row['status'],row.get('returncode',''),
                      row.get('artifact',{}).get('path',''),row.get('cad_verified',False)]
            writer.writerow(["'"+v if isinstance(v,str) and v.startswith(('=','+','-','@')) else v for v in values])
    # Export real parameter-register entries only. Unmapped values stay blank.
    with path.with_name(path.stem+'-parameters.csv').open('w',newline='',encoding='utf-8-sig') as stream:
        writer = csv.writer(stream)
        writer.writerow(['job','parameter','value_mm','unit','confirmation','source'])
        for row in report.get('results',[]):
            for event in row.get('events',[]):
                plan = event.get('plan',{})
                register = plan.get('parameter_register',{})
                for parameter,metadata in register.items():
                    value = plan.get('values_mm',{}).get(parameter)
                    cells = [row.get('name',''),parameter,'' if value is None else value,
                        metadata.get('unit',''),metadata.get('confirmation_status',metadata.get('status','')),metadata.get('source','')]
                    writer.writerow(["'"+v if isinstance(v,str) and v.startswith(('=','+','-','@')) else v for v in cells])
    return path

