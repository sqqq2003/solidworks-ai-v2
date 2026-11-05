"""Source-driven parametric DAG, reusing the project's dependency ordering."""
from copy import deepcopy
import math

from a01 import topological_order
from .expressions import NAME, FUNCTIONS, CONSTANTS, UNITS, Quantity, compile_expression, evaluate, quantity, converted, finite


def solve_functions(specification, inputs=None):
    spec = deepcopy(specification)
    if spec.get('kind') != 'parametric_functions' or spec.get('schema_version') != 1:
        raise ValueError('parametric_functions schema_version 1 required')
    source = spec.get('source')
    if not isinstance(source,str) or not source.strip():raise ValueError('rule source required')
    nodes = {**spec.get('inputs',{}), **spec.get('parameters',{})}
    if set(spec.get('inputs',{})) & set(spec.get('parameters',{})):
        raise ValueError('input and formula parameter names collide')
    if not nodes or len(nodes)>128:raise ValueError('1..128 named parameters required')
    supplied = dict(inputs or {})
    if set(supplied)-set(spec.get('inputs',{})):raise ValueError('unknown supplied input')
    trees, graph = {}, {}
    for name,row in nodes.items():
        if not isinstance(name,str) or not NAME.fullmatch(name) or name in FUNCTIONS or name in CONSTANTS:
            raise ValueError('invalid or reserved parameter name')
        if not isinstance(row,dict):raise ValueError('parameter rule must be an object')
        if row.get('unit') not in UNITS:raise ValueError('explicit supported parameter unit required: '+name)
        if name in spec.get('parameters',{}):
            tree,deps=compile_expression(row.get('expression'))
            if row.get('depends_on') is not None and set(row['depends_on'])!=deps:
                raise ValueError('declared dependencies differ from expression: '+name)
            trees[name]=tree
        else:deps=set()
        graph[name]={'depends_on':sorted(deps)}
    order=topological_order(graph)
    values,quantities,register,unresolved={},{},{},[]
    for name in order:
        row=nodes[name];unit=row.get('unit')
        dependencies=graph[name]['depends_on']
        if name in trees:
            value=None if any(d not in quantities for d in dependencies) else evaluate(trees[name],quantities)
            if value is not None and not isinstance(value,Quantity):raise ValueError('parameter formula must return a number')
            result=None if value is None else converted(value,unit)
        else:
            result=supplied.get(name,row.get('value'))
            value=None if result is None else quantity(result,unit)
            if value is not None:result=converted(value,unit)
        bounds=row.get('range')
        if bounds is not None:
            if not isinstance(bounds,list) or len(bounds)!=2 or finite(bounds[0])>finite(bounds[1]):
                raise ValueError('ordered explicit parameter range required')
            if result is not None and not bounds[0]<=result<=bounds[1]:raise ValueError('parameter outside rule range: '+name)
        if result is None:unresolved.append({'parameter':name,'reason':'input or upstream parameter missing'})
        else:quantities[name]=value
        values[name]=result
        register[name]={'unit':unit,'source':row.get('source',source),'depends_on':dependencies,
                        'expression':row.get('expression'),'preserve_interface':row.get('preserve_interface',False),
                        'confirmation_status':'pending_mapping','rule_range':bounds}
    constraints=spec.get('constraints',[])
    if not isinstance(constraints,list) or len(constraints)>64:raise ValueError('at most 64 explicit constraints')
    checks=[]
    for row in constraints:
        tree,deps=compile_expression(row.get('expression'))
        if not deps<=set(nodes):raise ValueError('constraint has unknown parameter')
        result=None if not deps<=set(quantities) else evaluate(tree,quantities)
        if result is not None and type(result) is not bool:raise ValueError('constraint must be a comparison')
        checks.append({'expression':row['expression'],'satisfied':result,'message':row.get('message','rule constraint')})
    conflicts=[r for r in checks if r['satisfied'] is False]
    if any(r['satisfied'] is None for r in checks):unresolved.append({'reason':'constraint inputs missing'})
    return {'machine_id':spec.get('machine_id','user_function_model'),'units':'explicit_per_parameter',
            'status':'blocked' if conflicts else 'review_required','parameter_order':order,
            'values_mm':values,'parameter_values':values,'parameter_register':register,
            'unresolved':unresolved,'conflicts':conflicts,'constraint_checks':checks,
            'cad_executed':False,'manufacturing_approved':False,
            'scope':'numeric_parameter_functions_not_native_model_acceptance'}
