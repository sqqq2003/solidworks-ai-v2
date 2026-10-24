"""QL assembly occurrence tree, dependency ordering and native operation plans."""
from copy import deepcopy
from math import isfinite
from pathlib import PurePath
import re

MODULES = ('frame','conveyor','left_drive','right_drive','sealing','interfaces','standard_parts')


def machine_tree():
    """Unmapped machine architecture. No guessed CAD paths or mate references."""
    catalog = {'machine':{'id':'machine','type':'assembly','module':'machine',
        'part_number':'QL-5050PX-PENDING','component_kind':'editable',
        'source_path':None,'template':None,'configuration':None,
        'children':[{'id':module,'ref':module,'transform_mm':None} for module in MODULES]}}
    for module in MODULES:
        catalog[module] = {'id':module,'type':'assembly','module':module,
            'part_number':'QL-'+module.upper()+'-PENDING','component_kind':'editable',
            'source_path':None,'template':None,'configuration':None,'children':[],
            'structure_status':'pending_mapping','material':None}
    return {'schema_version':1,'machine':'QL-5050PX','units':'mm','root':'machine',
            'catalog':catalog,'mates':[],'mate_inventory_status':'pending_mapping'}


def finite(value):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not isfinite(value):
        raise ValueError('finite numeric value required')
    return float(value)


def validate_transform(value):
    """Rotation row-major 3x3 + translation mm + scale; SW ArrayData convention."""
    if len(value)!=16:
        raise ValueError('transform requires 16 SW ArrayData values')
    result = [finite(v) for v in value]
    if abs(result[12]-1)>1e-8 or any(abs(v)>1e-8 for v in result[13:]):
        raise ValueError('rigid transform requires unit scale and zero unused entries')
    rows = [result[i:i+3] for i in (0,3,6)]
    for i in range(3):
        for j in range(3):
            if abs(sum(a*b for a,b in zip(rows[i],rows[j]))-(1 if i==j else 0))>1e-7:
                raise ValueError('transform rotation is not orthonormal')
    determinant = (rows[0][0]*(rows[1][1]*rows[2][2]-rows[1][2]*rows[2][1])
        -rows[0][1]*(rows[1][0]*rows[2][2]-rows[1][2]*rows[2][0])
        +rows[0][2]*(rows[1][0]*rows[2][1]-rows[1][1]*rows[2][0]))
    if determinant<0:
        raise ValueError('reflection is not a placement rotation')
    return result


def plan_assembly(tree=None, *, values_mm=None, baseline=None):
    tree = deepcopy(tree if tree is not None else machine_tree())
    if tree.get('machine')!='QL-5050PX' or tree.get('units')!='mm':
        raise ValueError('QL-5050PX mm assembly contract required')
    catalog = tree['catalog']
    pending,operations,order,visiting,done = [],[],[],set(),set()
    def missing(path,field):
        pending.append({'path':path,'field':field,'status':'pending_mapping'})
    def visit(ref):
        if ref in visiting:
            raise ValueError('assembly cycle at '+ref)
        if ref in done:
            return
        if ref not in catalog:
            raise ValueError('unknown assembly reference: '+ref)
        if not re.fullmatch(r'[A-Za-z0-9_-]+',ref):
            raise ValueError('unsafe catalog identifier')
        visiting.add(ref)
        node = catalog[ref]
        if node['type'] not in {'part','assembly'} or node.get('component_kind') not in {'editable','fixed','purchased'}:
            raise ValueError('invalid node type or component kind')
        if not node.get('configuration'):
            missing(ref,'configuration')
        if node.get('structure_status')=='pending_mapping':
            missing(ref,'children')
        children = node.get('children',[])
        if node['type']=='part' and children:
            raise ValueError('part node cannot have child components')
        seen = set()
        for occurrence in children:
            if not re.fullmatch(r'[A-Za-z0-9_-]+',occurrence['id']) or occurrence['id'] in seen:
                raise ValueError('occurrence ids must be unique and safe per assembly')
            seen.add(occurrence['id'])
            if node.get('source_path') and not occurrence.get('native_name'):
                missing(ref+'/'+occurrence['id'],'native_name_in_source_assembly')
            visit(occurrence['ref'])
            if occurrence.get('transform_mm') is None:
                missing(ref+'/'+occurrence['id'],'transform_mm')
            else:
                validate_transform(occurrence['transform_mm'])
        source = node.get('source_path')
        if source:
            operations.append({'op':'isolate_pack_and_go','node':ref,'source':source})
        elif node['type']=='assembly' and node.get('template'):
            operations.append({'op':'create_assembly','node':ref,'template':node['template']})
        elif node['type']=='part' and node.get('generation'):
            operations.append({'op':'generate_part','node':ref,'generation':node['generation']})
        else:
            missing(ref,'source_path_or_generation_template')
        for occurrence in children:
            operations.append({'op':'insert_component','assembly':ref,**occurrence})
        operations.append({'op':'rebuild_save_reopen','node':ref,'expected_occurrences':len(children)})
        visiting.remove(ref)
        done.add(ref)
        order.append(ref)
    visit(tree['root'])
    if tree.get('mate_inventory_status')!='confirmed':
        missing(tree['root'],'mate_inventory')
    mate_ids = set()
    for mate in tree.get('mates',[]):
        if mate['id'] in mate_ids:
            raise ValueError('duplicate mate id')
        mate_ids.add(mate['id'])
        owner = mate.get('assembly',tree['root'])
        if owner not in catalog or catalog[owner]['type']!='assembly':
            raise ValueError('mate owner must be an assembly node')
        occurrences = {o['id'] for o in catalog[owner].get('children',[])}
        refs = mate.get('references',[])
        if len(refs)!=2:
            missing(mate['id'],'two_mate_references')
        for reference in refs:
            if reference.get('occurrence') not in occurrences:
                raise ValueError('mate references unknown sibling occurrence')
            if not reference.get('entity') or not reference.get('entity_type'):
                missing(mate['id'],'entity_reference')
        if mate.get('status')!='confirmed' or not mate.get('source'):
            missing(mate['id'],'confirmed_reference_source')
        operations.append({'op':'upsert_mate',**mate,'assembly':owner})
    before = (baseline or {}).get('catalog',{})
    differences = [{'node':key,'before':before.get(key),'after':catalog[key]}
                   for key in order if before.get(key)!=catalog[key]]
    return {'schema_version':1,'machine':'QL-5050PX','tree':tree,'dependency_order':order,
            'operations':operations,'differences':differences,'values_mm':values_mm or {},
            'pending_mapping':pending,'status':'pending_mapping' if pending else 'ready_for_native',
            'native_acceptance':'unverified','cad_executed':False}


def execute_assembly(plan, driver, destination):
    """Owned host runs the full transaction, leaving failed files for diagnosis."""
    if plan['status']!='ready_for_native' or plan['pending_mapping']:
        raise ValueError('assembly execution refuses unresolved OEM mapping')
    return driver.build_assembly(plan,destination)
