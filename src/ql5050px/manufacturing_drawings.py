"""Drawing register and native execution tasks derived from the assembly tree."""
from collections import Counter
import re
from .bom_tree import explode_bom
from .drawing_bom import drawing_model


def safe_name(value):
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]','_',str(value)).strip(' .')
    if not value or value.upper().split('.')[0] in {'CON','PRN','AUX','NUL',*[f'COM{i}' for i in range(1,10)],*[f'LPT{i}' for i in range(1,10)]}:
        raise ValueError('invalid drawing filename')
    return value


def plan_drawings(assembly_plan, *, part_parameters=None, settings=None):
    part_parameters,settings = part_parameters or {},settings or {}
    tree = assembly_plan['tree']
    catalog = tree['catalog']
    bom = explode_bom(catalog,tree['root'])
    tasks,pending = [],[]
    filenames = set()
    for index,ref in enumerate(assembly_plan['dependency_order'],1):
        node = catalog[ref]
        if node.get('component_kind')=='purchased' and not settings.get('draw_purchased',False):
            continue
        params = part_parameters.get(ref,{})
        number = node.get('part_number') or f'QL-PENDING-{index:03d}'
        filename = safe_name(number)+'-'+safe_name(settings.get('revision','DEV'))+'.SLDDRW'
        if filename.casefold() in filenames:
            filename = safe_name(number)+'-'+ref+'.SLDDRW'
        if filename.casefold() in filenames: raise ValueError('duplicate drawing output name')
        filenames.add(filename.casefold())
        template = settings.get('assembly_template' if node['type']=='assembly' else 'part_template')
        views = params.get('views',[])
        dimensions = params.get('dimensions',[])
        annotations = params.get('annotations',[])
        requirements = []
        for field,value in (('template',template),('views',views),('material',node.get('material')),
                            ('process',params.get('process')),('datum_scheme',params.get('datum_scheme')),
                            ('tolerance_scheme',params.get('tolerance_scheme'))):
            if not value: requirements.append(field)
        if not dimensions and node['type']=='part': requirements.append('dimensions')
        for i,dimension in enumerate(dimensions):
            if not dimension.get('references') or dimension.get('status')!='confirmed':
                requirements.append(f'dimensions[{i}].references')
        for i,view in enumerate(views):
            if view.get('kind') not in {'model','projected','flat'}:
                raise ValueError('view kind must be model/projected/flat')
            if view.get('kind')=='model' and not view.get('orientation'):
                requirements.append(f'views[{i}].orientation')
            if view.get('kind')=='projected' and not view.get('parent'):
                requirements.append(f'views[{i}].parent')
        if 'PENDING' in number.upper(): requirements.append('part_number')
        if node.get('sheet_metal') and not params.get('thickness_mm'):
            requirements.append('thickness_mm')
        model = drawing_model(number,material=node.get('material'),views=views,
            notes=params.get('notes',[]),bom=bom['bom'] if node['type']=='assembly' else [])
        task = {'id':'drawing-'+ref,'node':ref,'document_kind':node['type'],'filename':filename,
                'template':template,'sheet_format':settings.get('sheet_format'),
                'bom_template':settings.get('bom_template'),
                'width_mm':settings.get('width_mm',420),'height_mm':settings.get('height_mm',297),
                'scale':params.get('scale',settings.get('scale',[1,1])),'units':'mm',
                'drawing_model':model,'dimensions':dimensions,'annotations':annotations,
                'balloons':params.get('balloons',[]),'process':params.get('process'),
                'datum_scheme':params.get('datum_scheme'),'tolerance_scheme':params.get('tolerance_scheme'),
                'thickness_mm':params.get('thickness_mm'),
                'exports':['SLDDRW']+(['flat_DXF'] if node.get('sheet_metal') else []),
                'pending_mapping':requirements,'manufacturing_approved':False}
        tasks.append(task)
        if node['type']=='assembly' and not settings.get('bom_template'):
            requirements.append('bom_template')
        pending.extend({'drawing':task['id'],'field':field,'status':'pending_mapping'} for field in requirements)
    return {'schema_version':1,'machine':'QL-5050PX','tasks':tasks,'bom':bom['bom'],
            'pending_mapping':pending,'status':'pending_mapping' if pending else 'ready_for_native',
            'native_status':'unverified','manufacturing_approved':False}


def execute_drawings(plan, driver, assembly_receipt, destination):
    if plan['pending_mapping'] or plan['status']!='ready_for_native':
        raise ValueError('manufacturing export refuses incomplete drawing references/process data')
    return driver.export_manufacturing(plan,assembly_receipt,destination)
