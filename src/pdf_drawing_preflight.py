"""Read-only PDF text preflight; never substitutes for native dimension evidence."""
import hashlib
from pathlib import Path
import re


def inspect_pdf(path,*,required_fields=None):
    from pypdf import PdfReader
    path=Path(path).resolve(strict=True)
    if path.suffix.lower()!='.pdf' or not path.is_file():raise ValueError('请选择工程图PDF。')
    def digest():
        with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
    before=digest();reader=PdfReader(path)
    fields={} if required_fields is None else required_fields
    if not isinstance(fields,dict) or any(not isinstance(k,str) or not isinstance(v,str) or not v.strip() for k,v in fields.items()):
        raise ValueError('应填字段必须为明确的非空文字。')
    result={'source':str(path),'sha256':before,'pages':[], 'blockers':[],
            'required_text_presence':{},'title_region_verified':False,
            'dimension_pdf_association':'unverified','production_approved':False}
    texts=[]
    if reader.is_encrypted:result['blockers'].append('PDF已加密，文字未核验')
    else:
        for index,page in enumerate(reader.pages):
            text=page.extract_text() or '';texts.append(text)
            quoted=re.findall(r'[“\"]\s*(图样代号|图样名称|图号|名称)\s*[”\"]',text)
            tokens=re.findall(r'\{\{[^{}\n]{1,100}\}\}',text)
            placeholders=sorted(set(quoted+tokens))
            if not text.strip():result['blockers'].append(f'第{index+1}页文字无法回读')
            if placeholders:result['blockers'].append(f'第{index+1}页仍有标题或模板占位')
            result['pages'].append({'page':index+1,'text_characters':len(text),
                'placeholders':placeholders,'page_mm':[round(float(page.mediabox.width)*25.4/72,3),
                                                       round(float(page.mediabox.height)*25.4/72,3)]})
    normalized=re.sub(r'\s+','','\n'.join(texts))
    for key,value in fields.items():
        found=re.sub(r'\s+','',value) in normalized
        result['required_text_presence'][key]=found
        if not found:result['blockers'].append('未读到应填文字：'+key)
    if not result['pages'] and not reader.is_encrypted:result['blockers'].append('PDF没有图纸页')
    if digest()!=before:raise ValueError('PDF读取时已变化，请重新核验。')
    result['source_unchanged']=True
    result['status']='blocked' if result['blockers'] else 'text_checks_only_pending_dimension_association'
    result['limitations']=['文字存在不证明标题栏位置或业务内容正确。',
                           '尚未关联原生CAD尺寸、PDF文字边界和制造要求。']
    return result
