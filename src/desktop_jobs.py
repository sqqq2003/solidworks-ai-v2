"""Presentation labels and desktop job adapter; no Tk/COM side effects."""
import math
from pathlib import Path
from project_workbench import build_command, confirm_job

MODES = {
    'sheet': ('钣金零件', '从二维图纸识别轮廓，审核折弯参数并生成零件。'),
    'roller': ('滚筒零件', '识别滚筒规格，规划尺寸并生成独立工作副本。'),
    'turned': ('车削零件', '识别回转轮廓与尺寸，审核后生成可编辑零件。'),
    'ql5050px': ('整机设计', 'QL-5050PX 参数、装配、传动与制造任务。'),
    'parametric': ('参数规划', '根据目标包络进行参数预检，不直接修改整机。'),
}
ACTIONS = {'识别图纸':'analyze', '生成计划':'plan', '原生生成':'generate'}
QL_ACTIONS = {'参数计划':'plan', '装配预检':'assembly', 'BOM 清单':'bom', '工程图规划':'drawing',
              '参数与交付':'pipeline', '自动装配计划':'auto_assembly', '传动改型':'drive',
              '制造任务':'manufacturing', '整机交付包':'machine_package', '智能识别':'intelligence',
              '建模批处理':'modeling_batch', '配方交付包':'modeling_delivery', 'CAD 特征计划':'cad_features',
              '统一改型计划':'integrated', '制造交付包':'production_package'}
# Show only actions implemented by the current, validated backend.
from ql5050px.workflow import ACTIONS as BACKEND_ACTIONS
QL_ACTIONS={label:action for label,action in QL_ACTIONS.items() if action in BACKEND_ACTIONS}
STATUS_LABELS = {'passed':'通过','failed':'失败','review_required':'待复核','pending_mapping':'待映射',
    'planned':'已规划','analyzed':'已识别','generated_unverified':'已生成 · 待验收',
    'reopen_geometry_verified':'已重开验证','degraded':'部分完成','timed_out':'等待超时',
    'not_run':'未运行','ready_for_native':'待原生验收','completed':'完成','cancelled':'已停止',
    'unverified':'待验证','stopped':'已停止'}


def build_desktop_job(values, action='plan', *, confirmed=False, flip=False, allow_inferred=False, preserve_circle_holes=False):
    kind=values['kind']
    if kind not in MODES:raise ValueError('请选择有效的任务类型')
    if kind=='unified':
        job={'kind':kind,'config':values['source'],'output_dir':values['output'],'name':'统一项目交付'}
    elif kind=='parametric':
        job={'kind':kind,'machine':values['machine'],**{k:float(values[k]) for k in ('length','width','height')}}
    elif kind=='ql5050px':
        job={'kind':kind,'machine':'QL-5050PX','action':values['ql_action'],'config':values['source'],
             'name':'整机 · '+next((label for label,key in QL_ACTIONS.items() if key==values['ql_action']),values['ql_action'])}
        if values['output']:job['output_dir']=values['output']
    else:
        job={'kind':kind,'action':action,'name':Path(values['source']).name,
             'source':values['source'],'output':values['output'],'sw_exe':values['sw_exe'],
             'confirmed':confirmed,'flip':flip,'allow_inferred':allow_inferred}
        if kind=='sheet' and action!='analyze':
            labels={'thickness':'板厚','radius':'内半径','angle':'折弯角度','k_factor':'K 因子'}
            for key,label in labels.items():
                if not str(values[key]).strip():raise ValueError('请填写本次任务的'+label)
                job[key]=float(values[key])
            job['profile']=int(values['profile'])
            scale=str(values.get('uniform_scale','')).strip()
            if scale:job['uniform_scale']=float(scale)
            if preserve_circle_holes:job['preserve_circle_holes']=True
        if kind in {'roller','turned'}:job['variant']=int(values['variant'])
        if action=='generate' and confirmed:job=confirm_job(job)
    build_command(job)
    return job


def number_text(value):
    """Stable form text for a queued number. Booleans and non-finite values are refused."""
    if isinstance(value,bool) or not isinstance(value,(int,float)):
        raise ValueError('任务里的数值无法显示')
    if isinstance(value,float) and not math.isfinite(value):
        raise ValueError('任务里的数值无法显示')
    if isinstance(value,float) and value.is_integer() and abs(value)<1e15:
        return str(int(value))
    return format(value,'.12g')


def form_state_from_job(job):
    """Map one queued job onto the task form. Native approval is never copied."""
    if not isinstance(job,dict) or job.get('kind') not in MODES:
        raise ValueError('这项任务无法载入设置')
    kind=job['kind']
    fields={'kind':kind,'source':'','output':'','sw_exe':'','machine':'QL-5050PX','ql_action':'plan',
            'profile':'1','variant':'0','thickness':'','radius':'','angle':'','k_factor':'','uniform_scale':'',
            'length':'1800','width':'900','height':'1500'}
    flags={'flip':False,'allow_inferred':False,'preserve_circle_holes':False,'confirmed':False}
    action_label=None;ql_label=None
    if kind=='parametric':
        machine=job.get('machine')
        if machine not in {'QL-5050PX','GT-ZX'}:raise ValueError('这项任务的机型无法载入当前设置')
        fields['machine']=machine
        for key in ('length','width','height'):fields[key]=number_text(job[key])
    elif kind=='ql5050px':
        action=job.get('action')
        labels=[label for label,key in QL_ACTIONS.items() if key==action]
        if len(labels)!=1:raise ValueError('这项整机任务的处理方式无法载入当前设置')
        ql_label=labels[0];fields['ql_action']=action;fields['machine']='QL-5050PX'
        fields['source']=str(job.get('config') or '');fields['output']=str(job.get('output_dir') or '')
    else:
        action=job.get('action')
        labels=[label for label,key in ACTIONS.items() if key==action]
        if len(labels)!=1:raise ValueError('这项任务的处理方式无法载入当前设置')
        action_label=labels[0]
        fields['source']=str(job.get('source') or '');fields['output']=str(job.get('output') or '')
        fields['sw_exe']=str(job.get('sw_exe') or '')
        flags['flip']=job.get('flip') is True
        flags['allow_inferred']=job.get('allow_inferred') is True
        flags['preserve_circle_holes']=job.get('preserve_circle_holes') is True
        if kind=='sheet':
            keys=('thickness','radius','angle','k_factor','profile')
            if action!='analyze':
                for key in keys:fields[key]=number_text(job[key])
                if 'uniform_scale' in job:fields['uniform_scale']=number_text(job['uniform_scale'])
            else:
                for key in keys+('uniform_scale',):
                    if key in job and job[key] not in ('',None):fields[key]=number_text(job[key])
        if kind in {'roller','turned'}:fields['variant']=number_text(job['variant'])
    return {'fields':fields,'flags':flags,'action_label':action_label,'ql_label':ql_label}


def job_copy_for_queue(job):
    """A second pending entry with the same inputs. Native approval is not copied.

    A native generation copy is refused: it would be unconfirmed, and the queue
    preflight would then block every other job.
    """
    if not isinstance(job,dict) or job.get('kind') not in MODES:
        raise ValueError('这项任务无法再排一份')
    copy={key:value for key,value in job.items() if key not in {'confirmation_digest','source_sha256'}}
    if 'confirmed' in copy:copy['confirmed']=False
    try:build_command(copy)
    except (OSError,ValueError,KeyError,TypeError) as exc:
        if job.get('action') in {'generate','batch'}:
            raise ValueError('原生生成的核对不能复制。请载入设置，改好新的输出路径并重新勾选核对后再加入队列。') from exc
        raise
    return copy
