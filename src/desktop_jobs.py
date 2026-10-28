"""Presentation labels and desktop job adapter; no Tk/COM side effects."""
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
            for key in ('target_length','target_width'):
                value=str(values.get(key,'')).strip()
                if value:job[key]=float(value)
            if preserve_circle_holes:job['preserve_circle_holes']=True
        if kind in {'roller','turned'}:job['variant']=int(values['variant'])
        if action=='generate' and confirmed:job=confirm_job(job)
    build_command(job)
    return job
