"""Bounded Chinese request parser; unsupported language returns confirmation items."""
import re


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
