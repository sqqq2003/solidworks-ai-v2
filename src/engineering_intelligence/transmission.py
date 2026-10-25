"""Sourced steady conveyor drive calculations, reusing motor/conveyor kernels."""
import math
from ql5050px.mechanical_selection import calculate
from design_platform.catalogue import select_parts
from .common import quantity, result


def transmission(request):
    values=request['inputs']
    units={'diameter':'mm','speed':'m/s','force':'N','ratio':'ratio','efficiency':'ratio','safety':'ratio'}
    missing=[k for k in units if k not in values]
    if missing: return result({},issues=['missing_input:'+k for k in missing])
    v={k:quantity(values[k],u,minimum=0) for k,u in units.items()}
    if any(x<=0 for x in v.values()) or v['efficiency']>1 or v['safety']<1:
        raise ValueError('positive inputs, efficiency<=1 and safety>=1 required')
    rpm=v['speed']*60000/(math.pi*v['diameter']); motor_rpm=rpm*v['ratio']
    motor_inputs={k:values[k] for k in ('force','speed','efficiency','safety')}
    motor_inputs['rpm']={'value':motor_rpm,'unit':'rpm','source':'roller rpm * explicit motor/output ratio'}
    motor=calculate('motor',motor_inputs)
    speed=calculate('conveyor',{'diameter':values['diameter'],'rpm':{'value':rpm,'unit':'rpm','source':'target line speed and roller diameter'}})
    calculations={'roller_rpm':rpm,'motor_rpm':motor_rpm,'roller_design_torque_Nm':v['force']*v['diameter']/2000*v['safety'],
                  **motor['results'],'speed_mm_s':speed['results']['speed_mm_s']}
    selections=[]; pending=[]
    for selection in request.get('selection_requests',[]):
        req=list(selection['requirements'])
        if selection['category']=='motor':
            req += [{'field':'power','unit':'W','minimum':calculations['power_W']},
                    {'field':'torque','unit':'N*m','minimum':calculations['torque_Nm']},
                    {'field':'rpm','unit':'rpm','equal':motor_rpm}]
        if not req: raise ValueError('explicit sizing/interface requirements required')
        if 'catalogue' not in request: pending.append('catalogue_missing'); continue
        chosen=select_parts(request['catalogue'],selection['category'],req)
        selections.append(chosen)
        pending.append('selection_requires_engineer_review:'+selection['category'])
    return result({'inputs':values,'calculations':calculations,'selection':selections,
                   'assumptions':['steady horizontal transport; supplied force includes all resistance',
                                  'ratio=motor rpm/output rpm; startup, thermal duty, braking and belt/chain strength require review'],
                   'automatic_purchase':False},issues=pending)
