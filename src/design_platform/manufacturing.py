"""Reuse BOM/drawing planning and add cross-document manufacturing consistency."""
from pathlib import Path
import json
from ql5050px.drawing_bom import build_bom,export_bom_csv
from ql5050px.manufacturing_drawings import plan_drawings


def consistency(register,revision):
    issues=[];seen=set()
    for row in register:
        key=(row['part_number'],row.get('configuration',''),row['kind'])
        if key in seen:issues.append({'part':row['part_number'],'reason':'duplicate_document_identity'})
        seen.add(key)
        if row.get('revision')!=revision:issues.append({'part':row['part_number'],'reason':'revision_mismatch'})
        for field in ('material','source'):
            if not row.get(field):issues.append({'part':row['part_number'],'reason':'missing_'+field})
        if row['kind']=='sheet' and any(row.get(k) is None for k in ('thickness_mm','radius_mm','angle_degrees','k_factor')):
            issues.append({'part':row['part_number'],'reason':'missing_per_job_sheet_parameters'})
    groups={}
    for row in register:groups.setdefault((row['part_number'],row.get('configuration','')),[]).append(row)
    for (number,_),rows in groups.items():
        if len({r['material'] for r in rows if r.get('material')})>1:issues.append({'part':number,'reason':'model_drawing_bom_material_mismatch'})
    return {'status':'review_required' if issues else 'declared_data_consistent','issues':issues,'manufacturing_approved':False}


def export_manufacturing(components,register,revision,destination,*,assembly_plan=None,part_parameters=None,settings=None):
    root=Path(destination);root.mkdir(parents=True,exist_ok=False)
    bom=build_bom(components);export_bom_csv(bom,root/'bom.csv')
    audit=consistency(register,revision)
    drawings=plan_drawings(assembly_plan,part_parameters=part_parameters,settings=settings) if assembly_plan else {'status':'pending_mapping','reason':'native drawing model/reference plan required'}
    operations=[{'part_number':r['part_number'],'material':r.get('material'),'revision':r.get('revision'),'operations':r.get('operations',[]),
        'process_status':'declared_input' if r.get('operations') else 'pending_confirmation'} for r in register if r['kind'] in {'part','sheet'}]
    for name,data in [('drawing-tasks.json',drawings),('manufacturing-consistency.json',audit),('machining-list.json',operations)]:
        (root/name).write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    return {'bom':bom,'drawings':drawings,'consistency':audit,'operations':operations,'manufacturing_approved':False}
