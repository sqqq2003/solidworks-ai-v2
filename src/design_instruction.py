"""Bounded Chinese request parser; unsupported language returns confirmation items."""
import re
import unicodedata


def parse_request(text):
    if not isinstance(text,str) or not text.strip():raise ValueError('nonempty design instruction required')
    matches=re.findall(r'(?:总长(?:度)?|总长度)\s*(?:改为|改成|为|=)?\s*(\d+(?:\.\d+)?)\s*(mm|毫米)',text,re.I)
    missing=[];target=None
    if len(matches)!=1:missing.append('one explicit overall length in mm')
    else:
        target=float(matches[0][0])
        if target<=0:raise ValueError('positive overall length required')
    if '滚筒' not in text:missing.append('supported machine/part identity')
    protections=[]
    if '轴径不变' in text:protections.append('shaft_diameter')
    if re.search(r'两端(?:安装)?结构不变',text):protections.append('shaft_end_installation_interfaces')
    if not protections:missing.append('explicit protected interface requirements')
    return {'part_kind':'roller' if '滚筒' in text else None,'target_overall_mm':target,'units':'mm','protected_requirements':protections,
        'source_text':text,'pending_confirmation':missing+['confirm native parameter bindings and actual interface inventory'],
        'status':'review_required','native_write_allowed':False,'cad_executed':False}


_NUM=r'(?P<v>\d+(?:\.\d+)?)'
_SEP=r'\s*(?:改为|改成|设为|设成|取|用|为|是|=|:)?\s*'
_LENGTH_UNIT=r'\s*(?P<u>mm|毫米|cm|厘米|米|m)?'
_ANGLE_UNIT=r'\s*(?P<u>°|度|rad|弧度)?'
_NOT_LETTER_BEFORE=r'(?<![A-Za-z])'

FIELD_LABELS={'thickness':('板厚','mm'),'radius':('内半径','mm'),'angle':('折弯角度','°'),'k_factor':('K 因子',''),
    'profile':('轮廓编号',''),'uniform_scale':('等比例倍数','倍'),'variant':('规格索引',''),
    'length':('目标长度','mm'),'width':('目标宽度','mm'),'height':('目标高度','mm'),
    'target_overall_mm':('滚筒总长','mm'),'machine':('整机型号','')}
KIND_LABELS={'sheet':'钣金零件','roller':'滚筒零件','turned':'车削零件','parametric':'整机目标包络'}

_FIELD_PATTERNS={
    'thickness':[r'(?:板厚|料厚|厚度|'+_NOT_LETTER_BEFORE+r't(?![A-Za-z]))'+_SEP+_NUM+_LENGTH_UNIT,
                 _NUM+_LENGTH_UNIT+r'\s*(?:板厚|料厚|厚)'],
    'radius':[r'(?:内半径|折弯半径|内圆角|'+_NOT_LETTER_BEFORE+r'R角|'+_NOT_LETTER_BEFORE+r'R(?![A-Za-z]))'+_SEP+_NUM+_LENGTH_UNIT],
    'angle':[r'(?:折弯角度|折弯角|角度)'+_SEP+_NUM+_ANGLE_UNIT,
             r'(?:折弯|折|弯)\s*'+_NUM+r'\s*(?P<u>°|度)',
             _NUM+r'\s*(?P<u>°|度)\s*(?:折弯|折|弯)'],
    'k_factor':[_NOT_LETTER_BEFORE+r'K\s*(?:因子|系数|值)?'+_SEP+_NUM],
    'profile':[r'轮廓(?:编号|序号)?'+_SEP+_NUM, r'第\s*'+_NUM+r'\s*个?轮廓'],
    'uniform_scale':[r'(?:等比例|按比例|整体)?\s*(?:缩放|放大)\s*(?:到|为|成)?\s*'+_NUM+r'\s*倍',
                     r'(?:等比例倍数|缩放倍数)'+_SEP+_NUM],
    'variant':[r'规格(?:索引|编号|序号)?'+_SEP+_NUM],
    'length':[r'(?<![总轴孔])长(?:度)?'+_SEP+_NUM+_LENGTH_UNIT],
    'width':[r'宽(?:度)?'+_SEP+_NUM+_LENGTH_UNIT],
    'height':[r'(?<![台面])高(?:度)?'+_SEP+_NUM+_LENGTH_UNIT],
}
_TRIPLE=re.compile(r'(?P<a>\d+(?:\.\d+)?)\s*[x×*]\s*(?P<b>\d+(?:\.\d+)?)\s*[x×*]\s*(?P<c>\d+(?:\.\d+)?)'+_LENGTH_UNIT,re.I)
_KIND_WORDS={
    'sheet':r'钣金|板件|折弯|展开|板厚|料厚',
    'roller':r'滚筒(?!线)',
    'turned':r'车件|车削|车床件|轴类|回转体',
    'parametric':r'整机|包络|外形尺寸|机架|输送线|滚筒线|QL\s*-?\s*5050|GT\s*-?\s*ZX',
}
_KIND_FIELDS={'sheet':('thickness','radius','angle','k_factor','profile','uniform_scale'),
    'roller':('variant',),'turned':('variant',),'parametric':('length','width','height')}
_INTEGER_FIELDS={'profile','variant'}


def _normalize(text):
    return unicodedata.normalize('NFKC',text)


def _collect(text,field):
    """Return every explicit (value, unit) the text states for one field."""
    found=[]
    for pattern in _FIELD_PATTERNS[field]:
        for match in re.finditer(pattern,text,re.I):
            unit=match.groupdict().get('u')
            found.append((float(match.group('v')),unit.lower() if unit else None))
    return found


def _detect_kinds(text,machine):
    kinds={kind for kind,pattern in _KIND_WORDS.items() if re.search(pattern,text,re.I)}
    if machine:kinds.add('parametric')
    return kinds


def _machine(text,pending):
    models=set()
    if re.search(r'QL\s*-?\s*5050\s*-?\s*PX',text,re.I):models.add('QL-5050PX')
    if re.search(r'GT\s*-?\s*ZX',text,re.I):models.add('GT-ZX')
    if len(models)>1:
        pending.append('同时提到了 QL-5050PX 和 GT-ZX，请只写一个整机型号')
        return None
    return next(iter(models),None)


def _accept(field,candidates,values,unit_notes,pending):
    """Fill a field only from one unambiguous, valid, explicitly stated number."""
    label,unit=FIELD_LABELS[field]
    if not candidates:return
    numbers={value for value,_ in candidates}
    if len(numbers)>1:
        pending.append(label+'出现了多个不同数值（'+'、'.join(f'{v:g}' for v in sorted(numbers))+'），请只保留一个')
        return
    value=numbers.pop();units={u for _,u in candidates}
    if unit=='mm' and units-{None,'mm','毫米'}:
        pending.append(label+'请使用 mm 填写，未自动换算')
        return
    if unit=='°' and units-{None,'°','度'}:
        pending.append(label+'请使用角度（°）填写，未自动换算')
        return
    if field in _INTEGER_FIELDS:
        if value!=int(value):
            pending.append(label+'必须是整数');return
        value=int(value)
        if field=='profile' and value<1:
            pending.append('轮廓编号从 1 开始');return
    elif field=='k_factor':
        if not 0<=value<=1:
            pending.append('K 因子需在 0 到 1 之间');return
    elif value<=0:
        pending.append(label+'必须大于 0');return
    values[field]=value
    if unit in {'mm','°'} and units=={None}:unit_notes.append(field)


def parse_design_text(text):
    """Read values the user explicitly typed; never supply defaults or confirm.

    The result only proposes form values for a human to review. Missing or
    ambiguous inputs are listed in ``pending_confirmation`` and left empty.
    """
    if not isinstance(text,str) or not text.strip():raise ValueError('nonempty design instruction required')
    plain=_normalize(text)
    pending=[];values={};unit_notes=[]
    machine=_machine(plain,pending)
    triple=list(_TRIPLE.finditer(plain))
    kinds=_detect_kinds(plain,machine)
    if not kinds:
        if triple:kinds={'parametric'}
        elif any(_collect(plain,field) for field in ('thickness','radius','k_factor')):kinds={'sheet'}
    if len(kinds)>1:
        names='、'.join(KIND_LABELS[k] for k in sorted(kinds))
        pending.append('同时提到了多种对象（'+names+'），请一次只描述一个任务')
        kind=None
    else:
        kind=next(iter(kinds),None)
    if kind is None and not pending:
        pending.append('没有识别到任务类型，请写明钣金、滚筒、车件或整机')
    candidates={field:_collect(plain,field) for field in _KIND_FIELDS.get(kind,())}
    if kind=='parametric':
        if len(triple)>1:
            pending.append('出现了多组 长×宽×高，请只保留一组')
        elif triple:
            match=triple[0];unit=(match.group('u') or '').lower() or None
            for field,group in (('length','a'),('width','b'),('height','c')):
                candidates[field].append((float(match.group(group)),unit))
    for field,found in candidates.items():
        _accept(field,found,values,unit_notes,pending)
    if kind=='parametric':
        if machine:values['machine']=machine
        else:pending.append('请写明整机型号（QL-5050PX 或 GT-ZX）')
        missing=[FIELD_LABELS[f][0] for f in ('length','width','height') if f not in values]
        if missing:pending.append('还缺少：'+'、'.join(missing))
    if kind=='sheet':
        if re.search(r'反向折弯|反折',plain):values['flip']=True
        if re.search(r'(?:圆)?孔(?:径)?(?:保持)?不变',plain):
            if 'uniform_scale' in values:values['preserve_circle_holes']=True
            else:pending.append('保持孔径不变需要同时写明缩放倍数')
        if re.search(r'缩小',plain):
            pending.append('“缩小”的倍数含义不明确，请写成“缩放到 0.5 倍”')
        missing=[FIELD_LABELS[f][0] for f in ('thickness','radius','angle','k_factor') if f not in values]
        if missing:pending.append('生成计划前还需填写：'+'、'.join(missing))
    if kind=='roller':
        legacy=parse_request(text)
        if legacy['target_overall_mm'] is not None:values['target_overall_mm']=legacy['target_overall_mm']
        values['protected_requirements']=legacy['protected_requirements']
        if legacy['target_overall_mm'] is None:pending.append('请写明一个滚筒总长（mm）')
        if not legacy['protected_requirements']:pending.append('请写明需要保持不变的接口，例如“轴径不变，两端安装结构不变”')
    return {'part_kind':kind,'values':values,'unit_assumed_mm':[f for f in unit_notes if FIELD_LABELS[f][1]=='mm'],
            'unit_assumed_degrees':[f for f in unit_notes if FIELD_LABELS[f][1]=='°'],
            'source_text':text,'pending_confirmation':pending,
            'status':'review_required','native_write_allowed':False,'cad_executed':False}


def form_updates(design):
    """Map a parsed design onto desktop form keys as strings and checkboxes."""
    kind=design.get('part_kind')
    if kind not in KIND_LABELS:return None
    values=design.get('values') or {}
    fields={'kind':kind}
    for key in _KIND_FIELDS[kind]+('machine',):
        if key in values:fields[key]=str(values[key]) if isinstance(values[key],(int,str)) else f'{values[key]:g}'
    flags={key:True for key in ('flip','preserve_circle_holes') if values.get(key) is True}
    return {'fields':fields,'flags':flags}


def describe_design(design):
    """Plain Chinese summary of what was read and what is still pending."""
    kind=design.get('part_kind');values=design.get('values') or {}
    lines=['任务类型：'+KIND_LABELS.get(kind,'未识别')]
    names={'shaft_diameter':'轴径','shaft_end_installation_interfaces':'两端安装结构'}
    assumed=set(design.get('unit_assumed_mm',[]))|set(design.get('unit_assumed_degrees',[]))
    for key,(label,unit) in FIELD_LABELS.items():
        if key not in values:continue
        value=values[key]
        shown=value if isinstance(value,str) else f'{value:g}'
        suffix='' if not unit else unit if unit=='°' else ' '+unit
        lines.append(label+'：'+shown+suffix+('（未写单位，按 '+unit+'）' if key in assumed else ''))
    if values.get('flip'):lines.append('折弯方向：反向')
    if values.get('preserve_circle_holes'):lines.append('圆孔孔径：保持不变')
    if values.get('protected_requirements'):
        lines.append('保持不变：'+'、'.join(names.get(k,k) for k in values['protected_requirements']))
    if design.get('pending_confirmation'):
        lines.append('待确认：'+'；'.join(design['pending_confirmation']))
    lines.append('只读取了文字中明确写出的数值，未补默认值，也未执行模型修改。')
    return '\n'.join(lines)


def instruction_request(request):
    import hashlib,json
    parsed=parse_request(request['text'])
    return {'parsed':parsed,'design':parse_design_text(request['text']),'native_write_allowed':False,'cad_executed':False,
            'status':'review_required','request_sha256':hashlib.sha256(json.dumps(request,ensure_ascii=False,sort_keys=True).encode()).hexdigest()}
