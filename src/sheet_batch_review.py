"""Read-only preflight for batch sheet extraction; never writes CAD."""
from dataclasses import asdict
from pathlib import Path
import hashlib


def inspect_sheet_batch(path):
    from cad_analyzer import analyze_cad_file,primitive_bounds
    from batch_export import discover_sheet_parts
    from sheet_safety import bend_note_warning
    source=Path(path).resolve(strict=True)
    if source.suffix.casefold()!='.dxf':
        raise ValueError('批量预检目前需要 DXF；DWG 请先转换为 DXF 工作副本。')
    before=hashlib.sha256(source.read_bytes()).hexdigest()
    analysis=analyze_cad_file(source)
    jobs=discover_sheet_parts(analysis)
    rows=[]
    for job in jobs:
        b=primitive_bounds(analysis.profiles[job.profile_index])
        text_inside=[t.text for t in analysis.text_entities if b[0]<=t.x<=b[2] and b[1]<=t.y<=b[3]]
        row=asdict(job)
        row.update(bounds_mm=list(b), text_inside=text_inside,
                   quantity_detected=bool(job.quantity_source),
                   quantity_confirmed=False, thickness_confirmed=False,
                   review_status='可能是文字框，需排除或确认' if text_inside else '候选零件，需确认')
        rows.append(row)
    if hashlib.sha256(source.read_bytes()).hexdigest()!=before:raise ValueError('图纸读取期间发生变化，请重新检查。')
    warning=bend_note_warning(analysis)
    return {'source':str(source),'source_sha256':before,'layout':analysis.layout_name,
            'status':'review_required','production_approved':False,'cad_written':False,
            'candidates':rows,'warnings':[warning] if warning else [],
            'note':'候选包含轮廓和可能的文字框；数量、板厚和折弯须逐件确认，不能直接批量生成。'}


def format_batch_review(report):
    lines=['钣金批量预检 · 未生成模型',f"图纸：{report['source']}",
           f"布局：{report['layout']}    候选：{len(report['candidates'])} 项",'']
    for row in report['candidates']:
        quantity=(str(row['quantity']) if row['quantity_confirmed'] else
                  str(row['quantity'])+'（图纸候选，未确认）' if row.get('quantity_detected') else '未确认')
        thickness=str(row['thickness_mm'])+' mm（图纸候选，未确认）' if row['thickness_mm'] is not None else '未确认'
        lines.append(f"{row['label']} | {row['size_hint']} | 数量：{quantity} | 板厚：{thickness} | {row['review_status']}")
        if row['text_inside']:lines.append('  框内文字：'+'；'.join(row['text_inside'][:3]))
    lines.extend(['',*report['warnings'],report['note']])
    return '\n'.join(lines)
