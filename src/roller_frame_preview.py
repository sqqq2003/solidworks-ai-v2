"""Adapt the user's reviewed frame math to the existing parameter workspace."""
from dataclasses import asdict
import math

from roller_frame_math.geometry import build_plan
from roller_frame_math.drive_side import plan_drive_side
from sw_api.mapping import mapping_template


def frame_plan(config, *, length, width, height):
    def number(key, optional=False):
        value=config.get(key)
        if value is None and optional:return None
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not .001<=value<=1e6:
            raise ValueError('滚筒机架规则需要有效的 '+key+'（mm），不能用占位值补齐')
        return value
    pitch=number('pitch_mm')
    if not math.isclose(pitch,88.9,rel_tol=0,abs_tol=1e-8):
        raise ValueError('本次导入规则的孔距应为88.9 mm；其他节距需另行核对')
    baseline={key:number('mother_'+key+'_mm') for key in ('length','width','height')}
    # Bound iteration/output allocation in the imported integer-mm algorithm.
    if max(length,baseline['length'])/pitch>10000:
        raise ValueError('孔位计算超过10000档，请拆分规则后计算')
    if any(value<.001 or value>1e6 for value in (length,width,height,*baseline.values())):
        raise ValueError('目标或母体尺寸超出当前计算精度/规模范围（0.001至1000000 mm）；这不是生产尺寸范围')
    geometry=build_plan(width_mm=width,length_mm=length,height_mm=height,pitch_mm=pitch,
        mother_width_mm=baseline['width'],mother_length_mm=baseline['length'],mother_height_mm=baseline['height'],
        mother_margin_start_mm=number('mother_margin_start_mm',True),
        mother_margin_end_mm=number('mother_margin_end_mm',True),
        mother_side_plate_height_mm=number('mother_side_plate_height_mm',True),
        mother_side_plate_thickness_mm=number('mother_side_plate_thickness_mm',True),
        mother_shaft_stickout_mm=number('mother_shaft_stickout_mm',True))
    side=plan_drive_side(requested=config.get('drive_side'),mother_gear_side=config.get('mother_drive_side'))
    holes=geometry.holes
    values={'length':length,'inner_clear_width':width,'height':height,
            'side_plate_height':geometry.height.side_plate_height_mm,
            'leg_length':geometry.height.leg_length_mm,'leg_delta':geometry.height.leg_delta_mm,
            'hole_pitch':pitch,'hole_count':holes.count if holes else None,
            'margin_start':holes.margin_start_mm if holes else None,
            'margin_end':holes.margin_end_mm if holes else None,
            'side_plate_thickness':geometry.width.side_plate_thickness_mm,
            'shaft_stickout':geometry.width.shaft_stickout_each_side_mm,
            'outer_width':geometry.width.overall_outer_width_mm}
    dependencies={'leg_length':['height','side_plate_height'],'leg_delta':['leg_length'],
        'hole_count':['length','hole_pitch','margin_start','margin_end'],
        'outer_width':['inner_clear_width','side_plate_thickness','shaft_stickout']}
    register={key:{'unit':'count' if key=='hole_count' else 'mm',
                   'source':'user_target' if key in {'length','inner_clear_width','height'} else 'imported_frame_rules_not_reverified',
                   'depends_on':dependencies.get(key,[]),'confirmation_status':'pending_mapping',
                   'confirmed_range_mm':None,'production_approved':False}
              for key in values}
    warnings=['此包只处理机架，不包括滚筒零件；规则里的历史测量值尚未在当前模型上复核。',
              'W是侧板内侧净距，不是整机外宽；H默认通过支腿调整。']
    drive=config.get('geometry_drive') or {}
    if not isinstance(drive,dict):raise ValueError('geometry_drive 必须是规则对象')
    measured_span=drive.get('mother_inner_span_mm')
    if measured_span is not None:
        if isinstance(measured_span,bool) or not isinstance(measured_span,(int,float)) or not math.isfinite(measured_span) or measured_span<=0:
            raise ValueError('mother_inner_span_mm 无效')
        if not math.isclose(measured_span,baseline['width'],abs_tol=.001):
            warnings.append(f"原包名义W={baseline['width']:g}与实测内档{measured_span:g} mm不一致，确认含义前禁止驱动真实模型。")
    if drive.get('length_mode')=='pattern_only':
        warnings.append('原包仅映射了孔阵列，尚不能证明侧板总长会随L改变。')
    if side.action=='swap':warnings.append('换边必须联动齿轮侧、两端短辊固定板和挡板；原包未实现完整换边，禁止执行。')
    plan={'machine_id':'roller_frame','scope':'roller_frame_parameter_preview_only','units':'mm',
          'status':'review_required','cad_executed':False,'cad_release_approved':False,
          'target_frame_dimensions_mm':{'L':length,'W_inner_clear':width,'H':height},
          'mother_dimensions_mm':baseline,'width_definition':'side_plate_inner_clear_span',
          'values_mm':values,'parameter_register':register,
          'unresolved':[{'parameter':name,'reason':'模型尺寸绑定与历史测量值待复核'} for name in values],
          'geometry':asdict(geometry),'drive_side':asdict(side),'warnings':warnings,
          'hole_centers_mm':list(holes.centers_mm) if holes else None}
    return plan,mapping_template(plan)
