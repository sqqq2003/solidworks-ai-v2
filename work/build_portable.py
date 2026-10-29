"""Build a local Windows x64 Python/Tk/COM test bundle, excluding customer data."""
import argparse
import hashlib
import json
import shutil
import site
import struct
import sys
from pathlib import Path


def imports(path):
    """Read PE import names without executing a binary."""
    data=path.read_bytes()
    if data[:2]!=b'MZ':return []
    pe=struct.unpack_from('<I',data,60)[0]
    if data[pe:pe+4]!=b'PE\0\0':return []
    sections=struct.unpack_from('<H',data,pe+6)[0];opt_size=struct.unpack_from('<H',data,pe+20)[0];opt=pe+24
    directory=opt+(112 if struct.unpack_from('<H',data,opt)[0]==0x20b else 96)
    rva,size=struct.unpack_from('<II',data,directory+8)
    if not rva:return []
    table=[]
    for i in range(sections):
        start=opt+opt_size+i*40;virtual_size,address,raw_size,offset=struct.unpack_from('<IIII',data,start+8)
        table.append((address,max(virtual_size,raw_size),offset))
    def file_offset(address):
        for base,length,offset in table:
            if base<=address<base+length:return offset+address-base
        raise ValueError('unmapped PE RVA')
    result=[];cursor=file_offset(rva)
    while any(data[cursor:cursor+20]):
        name=struct.unpack_from('<I',data,cursor+12)[0];start=file_offset(name);end=data.index(b'\0',start)
        result.append(data[start:end].decode('ascii'));cursor+=20
    return result


def build(output):
    repo=Path(__file__).resolve().parents[1];base=Path(sys.base_prefix)
    if sys.platform!='win32':raise RuntimeError('Windows runtime packaging requires Windows; use work/delivery.py candidate on cloud')
    import subprocess
    if subprocess.check_output(['git','status','--porcelain','--untracked-files=no'],cwd=repo).strip():
        raise ValueError('commit tracked source changes before portable packaging')
    revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo).decode().strip()
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=False)
    runtime=output/'runtime';runtime.mkdir();app=output/'app';app.mkdir()
    ignored=shutil.ignore_patterns('__pycache__','*.pyc','test','tests','idlelib','ensurepip','site-packages')
    shutil.copytree(base/'Lib',runtime/'Lib',ignore=ignored)
    shutil.copytree(base/'DLLs',runtime/'DLLs',ignore=shutil.ignore_patterns('*test*','__pycache__'))
    for name in ('python.exe','pythonw.exe','python3.dll','python314.dll','vcruntime140.dll','vcruntime140_1.dll','vcruntime140_threads.dll','LICENSE.txt'):
        if (base/name).is_file():shutil.copy2(base/name,runtime/name)
    packages=Path(site.getsitepackages()[-1])
    shutil.copytree(packages,runtime/'Lib/site-packages',ignore=shutil.ignore_patterns('__pycache__','*.pyc','pip','pip-*.dist-info'))
    tcl=base/'Library/lib'
    for name in ('tcl9','tcl9.0','tk9.0','dde1.4','registry1.3'):
        if (tcl/name).exists():shutil.copytree(tcl/name,runtime/'Library/lib'/name,ignore=shutil.ignore_patterns('__pycache__'))
    # Collect runtime dependencies of the shipped binaries, not all of Anaconda.
    lookup={p.name.casefold():p for folder in [base,base/'DLLs',base/'Library/bin'] for p in folder.glob('*.dll')}
    for name in ('msvcp140.dll','concrt140.dll'):
        path=Path('C:/Windows/System32')/name
        if path.is_file():lookup.setdefault(name,path)
    queue=[p for p in runtime.rglob('*') if p.suffix.lower() in ('.dll','.pyd','.exe')];done=set();native=[]
    while queue:
        path=queue.pop()
        if path in done:continue
        done.add(path)
        for name in imports(path):
            source=lookup.get(name.casefold())
            if source is None:continue  # Windows OS DLL or a package-local library.
            target=runtime/'DLLs'/source.name
            if not target.exists():shutil.copy2(source,target);queue.append(target);native.append(source.name)
    (runtime/'python314._pth').write_text('Lib\nDLLs\nLib/site-packages\n../app\n../app/src\nimport site\n',encoding='utf-8')
    (runtime/'Lib/sitecustomize.py').write_text('''import os,sys
from pathlib import Path
_root=Path(sys.executable).resolve().parent
_handles=[]
for _path in (_root/'DLLs',_root/'Lib/site-packages/pywin32_system32'):
    if _path.is_dir():_handles.append(os.add_dll_directory(str(_path)))
os.environ['TCL_LIBRARY']=str(_root/'Library/lib/tcl9.0')
os.environ['TK_LIBRARY']=str(_root/'Library/lib/tk9.0')
''',encoding='utf-8')
    from prepare_test_handoff import collect
    for relative in collect(repo):
        target=app/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(repo/relative,target)
    examples=app/'examples';examples.mkdir(exist_ok=True)
    import ezdxf
    document=ezdxf.new();document.units=4
    document.modelspace().add_lwpolyline([(0,0),(100,0),(100,60),(0,60)],close=True);document.saveas(examples/'synthetic-100x60.dxf')
    (output/'启动工作台.cmd').write_bytes(b'@echo off\r\ncd /d "%~dp0"\r\nstart "" "%~dp0runtime\\pythonw.exe" -X utf8 "%~dp0app\\app.py"\r\n')
    (output/'运行环境检查.cmd').write_bytes(b'@echo off\r\ncd /d "%~dp0"\r\n"%~dp0runtime\\python.exe" -X utf8 "%~dp0app\\work\\portable_doctor.py"\r\npause\r\n')
    (output/'build-info.json').write_text(json.dumps({'source_revision':revision,'sw_live_acceptance':'not_run','python':sys.version,'architecture':'Windows x64','runtime_origin':'local verified Python/Tk/pywin32/comtypes environment','bundled_additional_dlls':sorted(set(native)),'customer_cad_included':False,'solidworks_included':False,'host_runtime_paths_required':False,'source_files':[{'path':str(p.relative_to(app)),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in app.rglob('*') if p.is_file()]},ensure_ascii=False,indent=2),encoding='utf-8')
    return output


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);args=parser.parse_args()
    print(build(args.output))
