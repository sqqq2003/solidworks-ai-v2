"""Reuse BOM/drawing planning and add cross-document manufacturing consistency."""
from pathlib import Path
import json
from math import isfinite
from ql5050px.drawing_bom import build_bom,export_bom_csv
from ql5050px.manufacturing_drawings import plan_drawings


def consistency(register, revision, *, bom=None):
    """Audit declared manufacturing data; never grants manufacturing approval.

    Optional BOM is the actual build_bom output, not a second caller estimate.
    Drawing rows bind model_source/model_revision to a registered part or sheet.
    Paths are opaque identity strings here; this does not inspect native files.
    """
    rows = list(register)
    issues, seen, groups = [], set(), {}
    def issue(number, reason):
        issues.append({'part': number, 'reason': reason})
    def finite(value):
        return type(value) in (int, float) and isfinite(value)
    if not rows:
        issue(None, 'empty_manufacturing_register')
    if not isinstance(revision, str) or not revision.strip():
        issue(None, 'missing_release_revision')
    for row in rows:
        number = row.get('part_number')
        identity = (number, row.get('configuration', ''))
        key = (*identity, row.get('kind'))
        if not isinstance(number, str) or not number.strip():
            issue(number, 'missing_part_number')
        if row.get('kind') not in {'part', 'sheet', 'drawing', 'bom', 'assembly'}:
            issue(number, 'unknown_document_kind')
        if key in seen:
            issue(number, 'duplicate_document_identity')
        seen.add(key)
        groups.setdefault(identity, []).append(row)
        if row.get('revision') != revision:
            issue(number, 'revision_mismatch')
        for field in ('material', 'source'):
            if not row.get(field):
                issue(number, 'missing_' + field)
        if row.get('kind') == 'sheet':
            limits = {'thickness_mm': lambda v: v > 0, 'radius_mm': lambda v: v >= 0,
                      'angle_degrees': lambda v: 0 < abs(v) < 180,
                      'k_factor': lambda v: 0 <= v <= 1}
            for field, valid in limits.items():
                value = row.get(field)
                if value is None:
                    issue(number, 'missing_per_job_' + field)
                elif not finite(value) or not valid(value):
                    issue(number, 'invalid_' + field)
            if row.get('direction') not in {'normal', 'reverse'}:
                issue(number, 'missing_or_invalid_bend_direction')
    for (number, configuration), documents in groups.items():
        if len({r['material'] for r in documents if r.get('material')}) > 1:
            issue(number, 'model_drawing_bom_material_mismatch')
        models = [r for r in documents if r.get('kind') in {'part', 'sheet', 'assembly'}]
        for drawing in (r for r in documents if r.get('kind') == 'drawing'):
            if len(models) != 1:
                issue(number, 'drawing_requires_unique_registered_model')
            elif not drawing.get('model_source') or drawing['model_source'] != models[0].get('source'):
                issue(number, 'drawing_model_reference_mismatch')
            if drawing.get('model_revision') != revision:
                issue(number, 'drawing_model_revision_mismatch')
    if bom is not None:
        actual = {}
        for row in bom:
            identity = (row['part_number'], row.get('configuration', ''))
            if identity in actual:
                issue(identity[0], 'ambiguous_bom_identity')
            actual[identity] = row
        for identity, documents in groups.items():
            declarations = [r for r in documents if r.get('kind') == 'bom']
            if identity not in actual:
                issue(identity[0], 'registered_item_missing_from_bom')
                continue
            if len(declarations) != 1:
                issue(identity[0], 'missing_or_ambiguous_bom_declaration')
            for declaration in declarations:
                quantity = declaration.get('quantity')
                if type(quantity) is not int or quantity <= 0 or quantity != actual[identity]['quantity']:
                    issue(identity[0], 'bom_quantity_mismatch')
            for document in documents:
                if document.get('material') != actual[identity].get('material'):
                    issue(identity[0], 'generated_bom_material_mismatch')
        for identity in actual.keys() - groups.keys():
            issue(identity[0], 'bom_item_missing_from_register')
    # Duplicate findings from cross-document checks are emitted once.
    issues = [dict(part=number, reason=reason) for number, reason in
              dict.fromkeys((r['part'], r['reason']) for r in issues)]
    return {'status': 'review_required' if issues else 'declared_data_consistent',
            'issues': issues, 'bom_cross_checked': bom is not None,
            'native_references_verified': False, 'manufacturing_approved': False}


def export_manufacturing(components,register,revision,destination,*,assembly_plan=None,part_parameters=None,settings=None):
    components=list(components);register=list(register)
    root=Path(destination);root.mkdir(parents=True,exist_ok=False)
    bom=build_bom(components);export_bom_csv(bom,root/'bom.csv')
    audit=consistency(register,revision,bom=bom)
    drawings=plan_drawings(assembly_plan,part_parameters=part_parameters,settings=settings) if assembly_plan else {'status':'pending_mapping','reason':'native drawing model/reference plan required'}
    operations=[{'part_number':r['part_number'],'material':r.get('material'),'revision':r.get('revision'),'operations':r.get('operations',[]),
        'process_status':'declared_input' if r.get('operations') else 'pending_confirmation'} for r in register if r['kind'] in {'part','sheet'}]
    for name,data in [('drawing-tasks.json',drawings),('manufacturing-consistency.json',audit),('machining-list.json',operations)]:
        (root/name).write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    return {'bom':bom,'drawings':drawings,'consistency':audit,'operations':operations,'manufacturing_approved':False}
