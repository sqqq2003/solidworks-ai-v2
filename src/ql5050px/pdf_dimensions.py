"""Bind native dimension values/positions to real PDF word bounding boxes.

Single unrotated sheet pilot. No OCR, invented text bounds or numeric override.
Coordinates are millimetres, PDF top-left; native annotation XY is bottom-left.
"""
import hashlib
import math
from pathlib import Path
import re

from cad_checkpoint import digest_file,json_bytes


def _finite(value):
    return type(value) in (int,float) and math.isfinite(value)


def _native_rows(data):
    return [row for row in data.get('annotations',[]) if row.get('kind')=='model_dimension']


def native_dimension_id(row):
    return [row['requested']['view'],row['name'],row['model_dimension']['full_name']]


def native_dimension_digest(data):
    return hashlib.sha256(json_bytes(_native_rows(data))).hexdigest()


def _number(text,kind):
    value=str(text).strip().replace('\u2212','-')
    if kind==1 and value.endswith('°'):value=value[:-1]
    if not re.fullmatch(r'[+-]?\d+(?:[.,]\d+)?',value):return None
    result=float(value.replace(',','.'))
    return result if math.isfinite(result) else None


def _distance(point,box):
    return math.hypot(max(box[0]-point[0],0,point[0]-box[2]),max(box[1]-point[1],0,point[1]-box[3]))


def _overlap(a,b):
    return min(a[2],b[2])-max(a[0],b[0])>.1 and min(a[3],b[3])-max(a[1],b[1])>.1


def extract_axis_aligned_words(page):
    """Use glyph matrices to read vertical CAD labels in their true direction.

    PDF text-flow segmentation can split an upward 60 into separate 6 and 0.
    Never reverse digits to make a value match; derive order from glyph axes.
    """
    import pdfplumber
    groups={direction:[] for direction in ('ltr','rtl','btt','ttb')}
    if len(page.chars)>200000:raise ValueError('PDF text exceeds the single-sheet glyph budget')
    for char in page.chars:
        matrix=char.get('matrix',())
        if len(matrix)!=6 or any(not _finite(v) for v in matrix):raise ValueError('PDF glyph matrix unavailable')
        a,b=matrix[:2];length=math.hypot(a,b)
        if length<=0:raise ValueError('PDF glyph writing direction unavailable')
        if abs(b)<=length*1e-6:direction='ltr' if a>0 else 'rtl'
        elif abs(a)<=length*1e-6:direction='btt' if b>0 else 'ttb'
        else:raise ValueError('arbitrary-angle PDF text requires engineering review')
        groups[direction].append(char)
    result=[]
    for direction,chars in groups.items():
        if not chars:continue
        line='ttb' if direction in ('ltr','rtl') else 'ltr'
        result.extend(pdfplumber.utils.extract_words(chars,use_text_flow=False,
            line_dir=line,char_dir=direction,line_dir_rotated=line,char_dir_rotated=direction))
    return result


def match_dimension_words(rows,words,sheet_mm,*,frame=None,reserved=(),max_distance_mm=2.5,decimal_places=3):
    """Require a unique one-to-one assignment; numeric presence alone fails."""
    if (len(sheet_mm)!=2 or any(not _finite(v) or v<=0 for v in sheet_mm)
            or not _finite(max_distance_mm) or not 0<max_distance_mm<=3
            or type(decimal_places) is not int or not 0<=decimal_places<=6):
        raise ValueError('bounded sheet, text-anchor distance and precision required')
    width,height=sheet_mm
    result={'status':'pending_pdf_dimensions','associations':[],'issues':[],'native_count':len(rows),
            'max_distance_mm':max_distance_mm,'decimal_places':decimal_places,'manufacturing_approved':False}
    if not rows or len(rows)>128 or len(words)>100000:
        result['issues'].append('empty_or_oversized_dimension_text_set');return result
    ids=[native_dimension_id(row) for row in rows]
    if len({tuple(identity) for identity in ids})!=len(ids):
        result['issues'].append('duplicate_native_dimension_identity');return result
    for word in words:
        box=word.get('bbox_mm',[])
        if len(box)!=4 or any(not _finite(v) for v in box) or box[2]<=box[0] or box[3]<=box[1]:
            result['issues'].append('invalid_pdf_text_bounds');return result
    edges=[];points=[];values=[]
    tolerance=.5*10**(-decimal_places)+1e-9
    for row in rows:
        dim=row['model_dimension'];position=row['position_mm']
        if (len(position)!=3 or any(not _finite(v) for v in position)
                or dim.get('parameter_type') not in (0,1) or not _finite(dim.get('value_si'))
                or dim.get('overridden') is not False or dim.get('uses_document_units') is not True
                or dim.get('visibility_state')!=1 or row.get('reopened') is not True):
            result['issues'].append('native_dimension_not_verified_visible_and_unmodified');return result
        point=[position[0],height-position[1]]
        value=dim['value_si']*(1000 if dim['parameter_type']==0 else 180/math.pi)
        candidates=[]
        for index,word in enumerate(words):
            number=_number(word['text'],dim['parameter_type'])
            if number is not None and math.isclose(number,value,rel_tol=0,abs_tol=tolerance) and _distance(point,word['bbox_mm'])<=max_distance_mm:
                candidates.append(index)
        if not candidates or len(candidates)>32:
            result['issues'].append({'issue':'missing_or_excessive_pdf_dimension_candidates','native_id':native_dimension_id(row)})
        edges.append(candidates);points.append(point);values.append(value)
    if result['issues']:return result
    order=sorted(range(len(rows)),key=lambda i:len(edges[i]));solutions=[];steps=0
    def search(depth,chosen,used):
        nonlocal steps
        steps+=1
        if len(solutions)>=2 or steps>10000:return
        if depth==len(order):solutions.append(dict(chosen));return
        item=order[depth]
        for token in edges[item]:
            if token in used:continue
            chosen[item]=token;search(depth+1,chosen,used|{token});chosen.pop(item)
    search(0,{},set())
    if len(solutions)!=1 or steps>10000:
        result['issues'].append('ambiguous_or_non_unique_pdf_dimension_assignment');return result
    frame=[25,10,width-10,height-10] if frame is None else frame
    regions=[frame,*reserved]
    if any(len(box)!=4 or any(not _finite(v) for v in box) or box[2]<=box[0] or box[3]<=box[1] for box in regions):
        raise ValueError('valid frame and reserved rectangles required')
    pdf_frame=[frame[0],height-frame[3],frame[2],height-frame[1]]
    pdf_reserved=[[b[0],height-b[3],b[2],height-b[1]] for b in reserved]
    for item,token in sorted(solutions[0].items()):
        box=words[token]['bbox_mm']
        if box[0]<pdf_frame[0]-.1 or box[1]<pdf_frame[1]-.1 or box[2]>pdf_frame[2]+.1 or box[3]>pdf_frame[3]+.1:
            result['issues'].append({'issue':'dimension_text_outside_frame','native_id':ids[item]})
        if any(_overlap(box,area) for area in pdf_reserved):
            result['issues'].append({'issue':'dimension_text_in_reserved_area','native_id':ids[item]})
        conflicts=[other for other,word in enumerate(words) if other!=token and _overlap(box,word['bbox_mm'])]
        if conflicts:result['issues'].append({'issue':'dimension_text_collision','native_id':ids[item],'other_word_indexes':conflicts[:20]})
        result['associations'].append({'native_id':ids[item],'parameter':rows[item]['model_dimension']['parameter'],
            'value':values[item],'unit':'mm' if rows[item]['model_dimension']['parameter_type']==0 else 'deg',
            'pdf_word_index':token,'text':words[token]['text'],'bbox_mm':box,'native_anchor_pdf_mm':points[item],
            'anchor_distance_mm':_distance(points[item],box)})
    if not result['issues']:result['status']='verified'
    return result


def correlate_pdf_dimensions(path,data):
    """Read-only PDF extraction; missing backend or unsupported pages stay pending."""
    path=Path(path)
    base={'status':'pending_pdf_dimensions','associations':[],'issues':[],
          'pdf_sha256':digest_file(path),'native_source_sha256':data.get('source',{}).get('sha256'),
          'native_dimensions_sha256':native_dimension_digest(data),'manufacturing_approved':False}
    from .model_dimensions import dimension_import_verified
    if not dimension_import_verified(data):base['issues']=['native_dimension_evidence_incomplete'];return base
    if path.stat().st_size>64*1024*1024:base['issues']=['pdf_too_large_for_single_sheet_pilot'];return base
    try:import pdfplumber
    except ImportError:base['issues']=['pdfplumber_backend_missing'];return base
    try:
        with pdfplumber.open(path) as pdf:
            if len(pdf.pages)!=1:base['issues']=['single_sheet_pdf_required'];return base
            page=pdf.pages[0]
            if page.rotation or any(abs(float(v))>.1 for v in page.bbox[:2]):
                base['issues']=['rotated_or_offset_pdf_requires_review'];return base
            factor=25.4/72;size=[float(page.width)*factor,float(page.height)*factor]
            native_size=data['layout_readback']['sheet_size_mm']
            if any(abs(a-b)>.2 for a,b in zip(size,native_size)):
                base['issues']=['pdf_sheet_size_differs_from_native'];return base
            extracted=extract_axis_aligned_words(page)
            words=[{'text':word['text'],'bbox_mm':[float(word[key])*factor for key in ('x0','top','x1','bottom')]} for word in extracted]
            task=data.get('pdf_dimension_options',{})
            reserved=task.get('reserved_rectangles_mm',[[size[0]-180,0,size[0],60]])
            matched=match_dimension_words(_native_rows(data),words,size,
                frame=data['layout_readback'].get('frame_bounds_mm'),reserved=reserved,
                decimal_places=task.get('decimal_places',3))
            return {**base,**matched,'backend':'pdfplumber '+pdfplumber.__version__,'page_count':1,'pdf_word_count':len(words)}
    except Exception as error:
        return {**base,'issues':['pdf_dimension_extraction_failed'],'error':type(error).__name__+': '+str(error)}


def pdf_dimension_correlation_verified(data,*,reextract=False):
    try:
        proof=data.get('pdf_dimension_correlation') or {};rows=_native_rows(data)
        ids={tuple(native_dimension_id(row)) for row in rows};links=proof.get('associations',[])
        valid=(bool(rows) and proof.get('status')=='verified' and not proof.get('issues')
            and proof['pdf_sha256']==data['artifacts']['pdf']['sha256']
            and proof['native_source_sha256']==data['source']['sha256']
            and proof['native_dimensions_sha256']==native_dimension_digest(data)
            and len(links)==len(rows) and {tuple(link['native_id']) for link in links}==ids
            and len({link['pdf_word_index'] for link in links})==len(links))
        if not valid:return False
        if reextract:
            current=correlate_pdf_dimensions(data['artifacts']['pdf']['path'],data)
            return current['status']=='verified' and current['pdf_sha256']==proof['pdf_sha256'] and current['associations']==links
        return True
    except (KeyError,TypeError,ValueError,OSError):return False
