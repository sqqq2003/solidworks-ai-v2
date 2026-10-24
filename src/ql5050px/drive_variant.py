"""Dimension and kinematic dependency graph; no string eval or implicit stretch."""
from math import hypot, pi, sqrt
from .assembly_builder import finite


def compute(rule, args):
    op = rule['op']
    if op=='copy':
        if len(args)!=1: raise ValueError('copy needs one argument')
        return args[0]
    if op=='sum': return sum(args)
    if op=='product':
        result = 1
        for arg in args: result*=arg
        return result
    if op=='difference':
        if len(args)!=2: raise ValueError('difference needs two arguments')
        return args[0]-args[1]
    if op=='scale':
        if len(args)!=1: raise ValueError('scale needs one argument')
        return args[0]*finite(rule['factor'])
    if op=='ratio':
        if len(args)!=2 or args[1]==0: raise ValueError('ratio requires nonzero denominator')
        return args[0]/args[1]
    if op=='center_distance':
        if len(args) not in {4,6}: raise ValueError('center_distance requires 2D/3D point pair')
        half = len(args)//2
        return sqrt(sum((args[i]-args[i+half])**2 for i in range(half)))
    if op=='open_belt_length':
        if len(args)!=3: raise ValueError('belt requires pitch D1,D2,center distance')
        d1,d2,c = args
        if min(args)<=0 or c<=(d1+d2)/2:
            raise ValueError('belt pulleys overlap or center distance invalid')
        return 2*c+pi*(d1+d2)/2+(d1-d2)**2/(4*c)
    if op=='chain_links':
        if len(args)!=4: raise ValueError('chain requires pitch,z1,z2,center')
        pitch,z1,z2,c = args
        if min(args)<=0 or any(int(z)!=z for z in (z1,z2)):
            raise ValueError('positive pitch/center and integer tooth counts required')
        return 2*c/pitch+(z1+z2)/2+((z2-z1)/(2*pi))**2*pitch/c
    if op=='belt_speed':
        if len(args)!=2: raise ValueError('speed requires pitch diameter mm and rpm')
        return pi*args[0]*args[1]/60
    raise ValueError('unsupported dependency operation: '+op)


def plan_drive(nodes, *, inputs=None, baseline=None, components=(), constraints=(), mate_dependencies=(),
               source_assembly=None, assembly_configuration=None):
    """Nodes declare unit, depends_on, rule, optional bounds/source/status.

    Protected components may move only with allow_reposition=true; their part
    dimensions never change. Formula units are declared and checked at input
    boundaries by callers; formulas are mechanical design rules, not OEM proof.
    """
    inputs,baseline = inputs or {},baseline or {}
    unknown = set(inputs)-set(nodes)
    if unknown: raise ValueError('unknown drive inputs: '+str(sorted(unknown)))
    order,visiting,done = [],set(),set()
    def visit(name):
        if name not in nodes: raise ValueError('missing dependency '+name)
        if name in visiting: raise ValueError('drive dependency cycle at '+name)
        if name in done: return
        visiting.add(name)
        for dep in nodes[name].get('depends_on',[]): visit(dep)
        visiting.remove(name)
        done.add(name)
        order.append(name)
    for name in nodes: visit(name)
    values,pending,conflicts,register = {},[],[],{}
    for name in order:
        node = nodes[name]
        if not node.get('unit'): raise ValueError('explicit unit required for '+name)
        deps = node.get('depends_on',[])
        value = None
        if name in inputs:
            if node.get('rule'): raise ValueError('cannot override derived drive node '+name)
            value = finite(inputs[name])
        elif node.get('rule') and all(values[d] is not None for d in deps):
            try: value = finite(compute(node['rule'],[values[d] for d in deps]))
            except ValueError as exc: conflicts.append({'parameter':name,'reason':str(exc)})
        elif node.get('status')=='confirmed' and node.get('source') and node.get('value') is not None:
            value = finite(node['value'])
        if value is None:
            pending.append({'parameter':name,'missing_dependencies':[d for d in deps if values[d] is None],
                            'status':'pending_mapping'})
        if value is not None and node.get('bounds') is not None:
            lo,hi = map(finite,node['bounds'])
            if lo>hi: raise ValueError('reversed bounds')
            if not lo<=value<=hi: conflicts.append({'parameter':name,'reason':'outside allowed range','value':value,'range':[lo,hi]})
        values[name] = value
        register[name] = {'unit':node['unit'],'depends_on':deps,'source':node.get('source'),
                          'status':'resolved_design' if value is not None else 'pending_mapping'}
    changed = {name for name in order if values[name] is not None and baseline.get(name)!=values[name]}
    modifications = []
    for component in components:
        kind = component.get('component_kind','editable')
        if kind not in {'editable','fixed','purchased'}: raise ValueError('invalid component_kind')
        edits = []
        for binding in component.get('bindings',[]):
            parameter = binding['parameter']
            if parameter not in values: raise ValueError('binding references unknown parameter')
            if parameter not in changed: continue
            role = binding.get('role','dimension')
            if role not in {'dimension','position','stroke','mate'}: raise ValueError('invalid binding role')
            if kind!='editable' and (role!='position' or not component.get('allow_reposition')):
                conflicts.append({'component':component['id'],'parameter':parameter,'reason':'fixed/purchased component cannot be stretched or reconfigured'})
                continue
            if not binding.get('target') or binding.get('mapping_status')!='confirmed':
                pending.append({'component':component['id'],'parameter':parameter,'field':'native_target','status':'pending_mapping'})
            edits.append({'parameter':parameter,'before':baseline.get(parameter),'after':values[parameter],
                          'unit':nodes[parameter]['unit'],'role':role,'target':binding.get('target'),
                          'mapping_status':binding.get('mapping_status','pending_mapping')})
        if edits:
            if not component.get('document') or not component.get('configuration'):
                pending.append({'component':component['id'],'field':'document/configuration','status':'pending_mapping'})
            modifications.append({'component':component['id'],'component_kind':kind,'edits':edits,
                                  'document':component.get('document'),'configuration':component.get('configuration')})
    for rule in constraints:
        a,b = values.get(rule['a']),values.get(rule['b'])
        if rule['a'] not in nodes or rule['b'] not in nodes: raise ValueError('unknown constraint parameter')
        if a is None or b is None:
            pending.append({'constraint':rule['id'],'status':'pending_mapping'})
            continue
        if nodes[rule['a']]['unit']!=nodes[rule['b']]['unit']: raise ValueError('constraint unit mismatch')
        margin = finite(rule.get('margin',0))
        op = rule['op']
        if op not in {'le','ge','equal'}: raise ValueError('unknown constraint operation')
        ok = a+margin<=b if op=='le' else (a>=b+margin if op=='ge' else abs(a-b)<=abs(margin))
        if not ok: conflicts.append({'constraint':rule['id'],'reason':'constraint violated','a':a,'b':b})
    mates = [m for m in mate_dependencies if set(m.get('depends_on',[]))&changed]
    for mate in mates:
        if not mate.get('document') or not mate.get('configuration') or not mate.get('native_mate'):
            pending.append({'mate':mate.get('id'),'field':'native_mate/document/configuration','status':'pending_mapping'})
    if not source_assembly or not assembly_configuration:
        pending.append({'field':'source_assembly/assembly_configuration','status':'pending_mapping'})
    return {'schema_version':1,'machine':'QL-5050PX','values':values,'parameter_register':register,
            'dependency_order':order,'changed_parameters':sorted(changed),'component_modifications':modifications,
            'affected_mates':mates,'pending_mapping':pending,'conflicts':conflicts,
            'source_assembly':source_assembly,'assembly_configuration':assembly_configuration,
            'status':'conflict' if conflicts else ('pending_mapping' if pending else 'ready_for_native'),
            'native_checks':{k:{'status':'unverified','evidence':None} for k in ('mates','motion','interference')},
            'cad_executed':False,'engineering_approval':False}


def execute_drive(plan, driver, destination):
    if plan['status']!='ready_for_native' or plan['pending_mapping'] or plan['conflicts']:
        raise ValueError('native drive execution requires resolved, conflict-free mappings')
    return driver.apply_drive(plan,destination)
