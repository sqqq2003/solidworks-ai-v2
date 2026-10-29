"""Five-sheet presentation export with immutable inputs and recoverable outputs.

The manifest binds explicit model handles and paper cells to source hashes.
No coordinate-based recognition or manufacturing approval is inferred here.
"""
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import uuid

from five_sheet_plan import SHEETS

NAMES=tuple(name for name,_ in SHEETS)
STATE='preview-state.json'


def file_hash(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def _json_write(path,value):
    temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    with temporary.open('x',encoding='utf-8') as stream:
        json.dump(value,stream,ensure_ascii=False,indent=2,allow_nan=False)
    os.replace(temporary,path)


def read_manifest(path):
    path=Path(path).resolve(strict=True)
    if path.stat().st_size>5_000_000:raise ValueError('五图清单超过大小限制。')
    raw=path.read_bytes();data=json.loads(raw.decode('utf-8-sig'))
    if data.get('schema_version')!=1 or not isinstance(data.get('sheets'),list):
        raise ValueError('请选择版本1的五图分区清单。')
    rows=data['sheets']
    if len(rows)!=5 or sorted(r.get('name','') for r in rows)!=sorted(NAMES):
        raise ValueError('清单必须各包含一张钣金图、方管图、明细图、总图和三视图。')
    for row in rows:
        source=Path(row['source'])
        if not source.is_absolute():source=path.parent/source
        source=source.resolve(strict=True)
        if source.suffix.lower()!='.dxf' or not source.is_file():
            raise ValueError('分区清单中的输入必须是DXF文件。')
        if file_hash(source)!=row.get('source_sha256'):
            raise ValueError('源图已变化，需重新核对分区清单：'+row['name'])
        row['source']=str(source)
        groups,cells=row.get('groups'),row.get('cells')
        if not isinstance(groups,dict) or not groups or not isinstance(cells,dict) or not cells:
            raise ValueError('每张图必须明确分区实体和纸面位置。')
        for handles in groups.values():
            if not isinstance(handles,list) or any(not isinstance(h,str) or not h for h in handles):
                raise ValueError('分区实体必须为明确的句柄清单。')
        size=row.get('page_mm',[594,420])
        if len(size)!=2 or not all(isinstance(v,(int,float)) and math.isfinite(v) and 50<=v<=2000 for v in size):
            raise ValueError('图幅尺寸无效。')
        row['page_mm']=size
        for cell in cells.values():
            if len(cell)!=4 or not all(isinstance(v,(int,float)) and math.isfinite(v) for v in cell):
                raise ValueError('纸面分区坐标无效。')
            if not (10<=cell[0]<cell[2]<=size[0]-10 and 20<=cell[1]<cell[3]<=size[1]-25):
                raise ValueError('纸面分区需为页眉和页脚留出位置。')
    return path,hashlib.sha256(raw).hexdigest(),data


def model_fingerprint(doc):
    """Include block geometry, vertex payloads and text; ignore only layer tags."""
    from ezdxf.lldxf.tagwriter import TagCollector
    def normalized(value):
        if isinstance(value,float):return round(value,7)
        if isinstance(value,(int,str)):return value
        try:return [normalized(v) for v in value]
        except TypeError:return str(value)
    entities=list(doc.modelspace())
    for block in doc.blocks:
        if not block.name.startswith(('*Model_Space','*Paper_Space')):entities.extend(block)
    records=[(e.dxf.handle,[(t.code,normalized(t.value)) for t in TagCollector.dxftags(e)
                           if t.code!=8]) for e in entities]
    return hashlib.sha256(json.dumps(records,ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def _prepare(row,job_id,title):
    import ezdxf
    from dxf_paper_layout import add_partitioned_layout
    source=Path(row['source'])
    if file_hash(source)!=row['source_sha256']:raise ValueError('源图读取前已变化。')
    doc=ezdxf.readfile(source);before=model_fingerprint(doc)
    by_handle={e.dxf.handle:e for e in doc.modelspace()}
    try:groups={key:[by_handle[h] for h in handles] for key,handles in row['groups'].items()}
    except KeyError as error:raise ValueError('分区句柄不存在：'+str(error)) from error
    name='SWAI_PREVIEW_'+job_id[:12]
    paper,layout=add_partitioned_layout(doc,groups,row['cells'],name=name,
        page_size=row['page_mm'],layer_prefix='PRINT_'+job_id[:12])
    w,h=row['page_mm']
    doc.styles.new(name,dxfattribs={'font':'msyh.ttc'})
    def text(value,point,height):
        paper.add_text(value,dxfattribs={'insert':point,'height':height,'style':name,'color':7})
    paper.add_lwpolyline([(8,8),(w-8,8),(w-8,h-8),(8,h-8)],close=True)
    text(str(title)[:120]+' · '+row['name']+' · 版式预览',(12,h-17),4)
    text('待工程复核；尺寸及物料以批准文件为准。',(12,12),3)
    labels={'view':'三视图','views':'三视图','fang':'方管下料','tube':'方管下料',
            'bom':'明细表','sheet_metal':'钣金展开'}
    for group,cell in row['cells'].items():
        if group!='title':text(labels.get(group,group),(cell[0],cell[3]+4),3)
    if model_fingerprint(doc)!=before:raise ValueError('分区准备意外改动了模型实体。')
    if file_hash(source)!=row['source_sha256']:raise ValueError('源图读取时已变化。')
    return {'doc':doc,'layout':layout,'fingerprint':before,'row':row}


def export_sheet(prepared,folder):
    """Local preview renderer: PDF text remains glyph paths, not dimension proof."""
    from ezdxf.addons.drawing.matplotlib import qsave
    from ezdxf.addons.drawing.config import Configuration,ColorPolicy,BackgroundPolicy
    row=prepared['row'];base=folder/row['name'];doc=prepared['doc']
    doc.saveas(base.with_suffix('.dxf'))
    paper=doc.layouts.get(prepared['layout']['layout'])
    config=Configuration(color_policy=ColorPolicy.BLACK,background_policy=BackgroundPolicy.WHITE)
    for suffix in ('.pdf','.png'):
        qsave(paper,base.with_suffix(suffix),bg='#ffffff',config=config,dpi=100,
              size_inches=tuple(v/25.4 for v in row['page_mm']))


def _verify(folder,row,fingerprint):
    import ezdxf
    from PIL import Image
    from pypdf import PdfReader
    files={ext:folder/(row['name']+'.'+ext) for ext in ('dxf','pdf','png')}
    doc=ezdxf.readfile(files['dxf'])
    if model_fingerprint(doc)!=fingerprint:raise ValueError('保存重开后模型实体核对失败。')
    audit=doc.audit()
    if audit.has_errors or audit.has_fixes:raise ValueError('输出DXF结构需要修复，未放行预览。')
    pdf=PdfReader(files['pdf'])
    if len(pdf.pages)!=1:raise ValueError('PDF预览页数不正确。')
    box=pdf.pages[0].mediabox
    if any(abs(a-b)>.05 for a,b in zip((float(box.width)*25.4/72,float(box.height)*25.4/72),row['page_mm'])):
        raise ValueError('PDF图幅与清单不一致。')
    with Image.open(files['png']) as image:image.verify()
    return {ext:file_hash(path) for ext,path in files.items()}


@contextmanager
def _lock(folder):
    stream=(folder/'.preview.lock').open('a+b')
    try:
        stream.seek(0,2)
        if stream.tell()==0:stream.write(b'0');stream.flush()
        stream.seek(0)
        if os.name=='nt':
            import msvcrt
            try:msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
            except OSError as error:raise ValueError('此输出目录已有任务正在执行。') from error
        else:
            import fcntl
            try:fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except OSError as error:raise ValueError('此输出目录已有任务正在执行。') from error
        yield
    finally:stream.close()  # OS releases the lock even after a process crash.


class PreviewRunFailed(RuntimeError):
    def __init__(self,message,state):super().__init__(message);self.state=state


def generate(manifest,output,*,resume=False,exporter=None):
    from app_logging import get_journal
    journal=get_journal();manifest,digest,plan=read_manifest(manifest)
    output=Path(output).resolve()
    if not resume:output.mkdir(parents=True,exist_ok=False)
    elif not output.is_dir():raise ValueError('恢复目录不存在。')
    with _lock(output):
        if resume:
            state=json.loads((output/STATE).read_text(encoding='utf-8'))
            if (state.get('schema_version')!=1 or state.get('manifest_sha256')!=digest
                    or state.get('manifest')!=str(manifest) or state.get('production_approved') is not False):
                raise ValueError('恢复清单与原任务不一致，请使用新输出目录。')
        else:
            state={'schema_version':1,'job_id':uuid.uuid4().hex,'manifest':str(manifest),
                   'manifest_sha256':digest,'status':'preflight','sheets':{},
                   'production_approved':False,'issues':plan.get('issues',[])}
            _json_write(output/STATE,state)
        current=None
        try:
            journal.record('five_sheet_preview_started',output=str(output),resume=resume,job_id=state['job_id'])
            prepared=[_prepare(row,state['job_id'],plan.get('machine_name','五图')) for row in plan['sheets']]
            state['status']='running';state.pop('error',None);_json_write(output/STATE,state)
            for item in prepared:
                row=item['row'];current=row['name'];destination=output/current
                if file_hash(row['source'])!=row['source_sha256']:raise ValueError('源图在执行期间变化。')
                if destination.exists():
                    receipt=json.loads((destination/'receipt.json').read_text(encoding='utf-8'))
                    if (receipt.get('job_id')!=state['job_id'] or receipt.get('manifest_sha256')!=digest
                            or receipt.get('source_sha256')!=row['source_sha256']):
                        raise ValueError('已有输出不属于此任务，拒绝覆盖：'+current)
                    hashes=_verify(destination,row,item['fingerprint'])
                    if hashes!=receipt.get('sha256'):raise ValueError('已有输出被修改，拒绝自动恢复：'+current)
                    state['sheets'][current]={'status':'completed_preview','sha256':hashes,'reused':True}
                    _json_write(output/STATE,state)
                    journal.record('five_sheet_preview_reused',sheet=current,job_id=state['job_id'])
                    continue
                staging=output/('.stage-'+state['job_id']+'-'+current+'-'+uuid.uuid4().hex[:8])
                staging.mkdir()
                state['sheets'][current]={'status':'rendering','staging':str(staging)}
                _json_write(output/STATE,state)
                journal.record('five_sheet_preview_sheet_started',sheet=current,job_id=state['job_id'])
                (exporter or export_sheet)(item,staging)
                hashes=_verify(staging,row,item['fingerprint'])
                if file_hash(row['source'])!=row['source_sha256']:raise ValueError('导出时源图发生变化。')
                _json_write(staging/'receipt.json',{'job_id':state['job_id'],'manifest_sha256':digest,
                    'source_sha256':row['source_sha256'],'sha256':hashes,'layout':item['layout'],
                    'pdf_dimension_association':'unverified_glyph_preview','production_approved':False})
                staging.rename(destination)
                state['sheets'][current]={'status':'completed_preview','sha256':hashes,'reused':False}
                _json_write(output/STATE,state)
                journal.record('five_sheet_preview_sheet_finished',sheet=current,job_id=state['job_id'])
            if any(file_hash(row['source'])!=row['source_sha256'] for row in plan['sheets']):
                raise ValueError('任务结束时源图已变化。')
            state['status']='completed_preview';state['cad_executed']=False
            _json_write(output/STATE,state)
            journal.record('five_sheet_preview_finished',output=str(output),job_id=state['job_id'])
            return state
        except Exception as error:
            state.update(status='failed',error=str(error),failed_sheet=current)
            _json_write(output/STATE,state)
            journal.exception('five_sheet_preview_failed',error,sheet=current,output=str(output),job_id=state['job_id'])
            raise PreviewRunFailed(str(error),state) from error
