"""Model-neutral tools. All CAD execution remains in project_workbench."""
from __future__ import annotations
import threading
from pathlib import Path
from . import project_workbench as project

JOB_SCHEMA = {'type':'object','properties':{
    'kind':{'enum':['sheet','roller','turned','parametric']},
    'machine':{'enum':['GT-ZX','QL-5050PX']},
    'action':{'enum':['analyze','plan','generate'],'default':'analyze'},
    'source':{'type':'string'},'output':{'type':'string'},
    'confirmed':{'type':'boolean'},'allow_inferred':{'type':'boolean'},
    'profile':{'type':'integer','minimum':1},'variant':{'type':'integer','minimum':0},
    'flip':{'type':'boolean'},'name':{'type':'string'},
    **{k:{'type':'number','exclusiveMinimum':0} for k in
       ('length','width','height','thickness','radius','angle')},
    'k_factor':{'type':'number','minimum':0,'maximum':1}},
    'required':['kind'],'additionalProperties':False}
TOOLS = [
    {'name':'solidworks_capabilities','description':'Discover implemented and pending project capabilities. Does not start CAD.',
     'inputSchema':{'type':'object','properties':{},'additionalProperties':False}},
    {'name':'solidworks_doctor','description':'Inspect execution environment without starting SolidWorks.',
     'inputSchema':{'type':'object','properties':{},'additionalProperties':False}},
    {'name':'solidworks_run_job','description':'Analyze CAD, plan a part, or generate a reviewed part. Paths are relative to the configured workspace. Native generation requires server opt-in and confirmed parameters. Mechanical acceptance remains unverified.',
     'inputSchema':{'type':'object','properties':{'job':JOB_SCHEMA},'required':['job'],'additionalProperties':False}}
]

class Gateway:
    def __init__(self, workspace, *, sw_exe=None, execute=project.execute_job):
        self.workspace = Path(workspace).resolve(strict=True)
        if not self.workspace.is_dir():
            raise ValueError('workspace must be a directory')
        self.sw_exe = str(Path(sw_exe).resolve(strict=True)) if sw_exe else None
        self.execute = execute
        self.lock = threading.Lock()

    def path(self, value):
        if not isinstance(value,str) or not value:
            raise ValueError('nonempty workspace-relative path required')
        relative = Path(value)
        if relative.is_absolute():
            raise ValueError('paths must be workspace-relative')
        resolved = (self.workspace / relative).resolve()
        if not resolved.is_relative_to(self.workspace):
            raise ValueError('path escapes configured workspace')
        return str(resolved)

    def call(self, name, arguments):
        if not isinstance(arguments,dict):
            raise ValueError('arguments must be an object')
        if name in {'solidworks_capabilities','solidworks_doctor'}:
            if arguments:
                raise ValueError('this tool accepts no arguments')
            data = project.capabilities() if name == 'solidworks_capabilities' else project.doctor()
            return {**data,'native_enabled':bool(self.sw_exe),
                'session_policy':{'mode':'task_owned_separate_process',
                    'attach_user_session':False,'close_user_documents':False,
                    'exit_user_application':False,'fallback_on_isolation_failure':'refuse',
                    'desktop_focus_isolation':'not_guaranteed'}}
        if name != 'solidworks_run_job':
            raise ValueError('unknown tool')
        if set(arguments) != {'job'} or not isinstance(arguments['job'],dict):
            raise ValueError('exactly one job object required')
        job = dict(arguments['job'])
        if set(job) - set(JOB_SCHEMA['properties']):
            raise ValueError('unknown job fields')
        for field in ('confirmed','allow_inferred','flip'):
            if field in job and type(job[field]) is not bool:
                raise ValueError(field+' must be boolean')
        if job.get('kind') == 'parametric' and job.get('action','plan') != 'plan':
            raise ValueError('parametric supports planning only')
        for field in ('source','output'):
            if field in job:
                job[field] = self.path(job[field])
        if job.get('action') == 'generate':
            if not self.sw_exe:
                raise ValueError('native generation disabled; configure --sw-exe on the host')
            job['sw_exe'] = self.sw_exe
            if job.get('confirmed') is True:
                job = project.confirm_job(job)
        # Both transports share one lock: refuse overlap rather than queue hidden CAD writes.
        if not self.lock.acquire(blocking=False):
            raise ValueError('executor busy; inspect the current task before retrying')
        try:
            project.build_command(job)
            report_folder = self.path('reports')
            result = self.execute(job)
            report = project.write_report({'schema_version':1,'results':[result]},report_folder)
            return {**result,'report':str(report.relative_to(self.workspace))}
        finally:
            self.lock.release()
