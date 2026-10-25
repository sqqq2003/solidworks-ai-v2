"""Versioned, user-supplied standard parts and mechanism installation interfaces."""
from copy import deepcopy
from .calculations import number
from design_review.impact import review_digest

CATEGORIES={'bearing','motor','roller','cylinder','guide','timing_belt','pulley','sprocket','gearbox','mechanism'}


def validate_catalogue(catalogue):
    seen=set()
    for row in catalogue['items']:
        if row['id'] in seen:raise ValueError('duplicate catalogue identity')
        seen.add(row['id'])
        if row['category'] not in CATEGORIES or not all(row.get(k) for k in ('model','source','revision','part_number')):raise ValueError('sourced versioned catalogue identity required')
        for name,spec in row.get('specifications',{}).items():
            number(spec['value'])
            if not spec.get('unit') or not spec.get('source'):raise ValueError('catalogue spec unit/source required: '+name)
    return catalogue


def select_parts(catalogue,category,requirements):
    validate_catalogue(catalogue);candidates=[];rejected=[]
    if category not in CATEGORIES:raise ValueError('unsupported part category')
    for row in catalogue['items']:
        if row['category']!=category:continue
        reasons=[]
        for req in requirements:
            field=req['field'];spec=row.get('specifications',{}).get(field)
            if not spec or spec['unit']!=req['unit']:reasons.append(field+': missing or incompatible unit');continue
            value=number(spec['value'])
            if 'minimum' in req and value<number(req['minimum']):reasons.append(field+': below minimum')
            if 'maximum' in req and value>number(req['maximum']):reasons.append(field+': above maximum')
            if 'equal' in req and value!=number(req['equal']):reasons.append(field+': interface mismatch')
        if not row.get('interfaces'):reasons.append('installation interfaces missing')
        item={'item':deepcopy(row),'reasons':reasons}
        (rejected if reasons else candidates).append(item)
    return {'status':'review_required','category':category,'candidates':candidates,'rejected':rejected,
        'catalogue_sha256':review_digest(catalogue),'engineering_approved':False,'automatic_purchase':False}


def selected_bom_rows(catalogue,selections):
    validate_catalogue(catalogue);items={row['id']:row for row in catalogue['items']};rows=[]
    for choice in selections:
        row=items[choice['id']]
        if choice.get('reviewed') is not True or not choice.get('source') or choice.get('catalogue_sha256')!=review_digest(catalogue):raise ValueError('current sourced selection approval required')
        qty=choice['quantity']
        if type(qty) is not int or qty<=0:raise ValueError('positive BOM quantity required')
        rows.append({'id':row['id'],'part_number':row['part_number'],'configuration':row.get('configuration',''),
            'material':row.get('material'),'quantity':qty,'purchased':True,'catalogue_revision':row['revision'],'selection_source':choice['source']})
    return rows
