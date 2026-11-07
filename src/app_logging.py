"""Per-process work journals and local diagnostic export; no CAD contents."""
import atexit
import hashlib
from datetime import datetime
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import platform
import re
import sys
import threading
import traceback
import uuid
import zipfile

_SECRET_KEYS={'password','api_key','secret','access_token','authorization','refresh_token'}


def scrub(value):
    if isinstance(value,dict):return {str(k):('[REDACTED]' if str(k).casefold() in _SECRET_KEYS else scrub(v)) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [scrub(v) for v in value]
    if isinstance(value,str):
        return re.sub(r'\b(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,})\b','[REDACTED]',value)
    if value is None or isinstance(value,(bool,int,float)):return value
    return str(value)


class _JsonFormatter(logging.Formatter):
    def format(self,record):return json.dumps(record.work_event,ensure_ascii=False,default=str)


class _TextFormatter(logging.Formatter):
    def format(self,record):
        event=record.work_event;details=dict(event['details']);trace=details.pop('traceback',None)
        return f"{event['time']} [{event['level']}] {event['event']} "+json.dumps(details,ensure_ascii=False,default=str)+('\n'+trace if trace else '')


class WorkJournal:
    def __init__(self,folder,component='workbench'):
        self.folder=Path(folder);self.folder.mkdir(parents=True,exist_ok=True)
        self.run_id=datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+str(os.getpid())+'-'+uuid.uuid4().hex[:8]
        self.component=component;self.logger=logging.getLogger('swai.'+self.run_id)
        self.logger.setLevel(logging.INFO);self.logger.propagate=False
        for suffix,formatter in (('jsonl',_JsonFormatter()),('log',_TextFormatter())):
            handler=RotatingFileHandler(self.folder/(self.run_id+'.'+suffix),maxBytes=2*1024*1024,backupCount=2,encoding='utf-8')
            handler.setFormatter(formatter);self.logger.addHandler(handler)
        self.record('session_started',python=sys.version,platform=platform.platform(),component=component)

    def record(self,event,level='INFO',**details):
        payload={'time':datetime.now().astimezone().isoformat(timespec='milliseconds'),'run_id':self.run_id,
                 'pid':os.getpid(),'thread':threading.current_thread().name,'component':self.component,
                 'event':event,'level':level,'details':scrub(details)}
        self.logger.log(getattr(logging,level,logging.INFO),event,extra={'work_event':payload})

    def exception(self,event,error,**details):
        self.record(event,level='ERROR',error_type=type(error).__name__,error=str(error),
                    traceback=''.join(traceback.format_exception(type(error),error,error.__traceback__)),**details)

    def events(self,limit=200):
        records=[]
        for path in sorted(self.folder.glob('*.jsonl'))[-30:]:
            for line in path.read_text(encoding='utf-8',errors='replace').splitlines():
                try:records.append(json.loads(line))
                except ValueError:continue
        return sorted(records,key=lambda row:row.get('time',''))[-limit:]

    def export(self,destination):
        destination=Path(destination)
        with zipfile.ZipFile(destination,'x',compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(self.folder.iterdir()):
                if path.is_file() and re.fullmatch(r'\d{8}-\d{6}-\d+-[0-9a-f]{8}\.(?:log|jsonl)(?:\.\d+)?',path.name):
                    archive.write(path,'logs/'+path.name)
            archive.writestr('README.txt','Local diagnostic logs only. CAD/drawing files are not included. File names and local paths may appear in logs.\n')
        self.record('diagnostics_exported',destination=str(destination))
        return destination

    def close(self):
        for handler in list(self.logger.handlers):handler.close();self.logger.removeHandler(handler)


class _NullJournal:
    def record(self,*args,**kwargs):pass
    def exception(self,*args,**kwargs):pass


_journal=_NullJournal()


def get_journal():return _journal


def bootstrap(root,component='workbench'):
    global _journal
    if isinstance(_journal,WorkJournal):return _journal
    try:_journal=WorkJournal(Path(root)/'runtime/logs',component)
    except OSError:_journal=WorkJournal(Path(os.environ.get('LOCALAPPDATA',Path.home()))/'SolidWorksAI/logs',component)
    fingerprints={}
    for name in ('app.py','src/desktop_ui.py','src/project_workbench.py','src/solidworks_generator.py','src/roller_geometry.py','src/sheet_metal_geometry.py','src/sw_session.py'):
        path=Path(root)/name
        if path.is_file():fingerprints[name]=hashlib.sha256(path.read_bytes()).hexdigest()
    _journal.record('code_identified',sha256=fingerprints)
    manifest=Path(root).parent/'build-info.json'
    if manifest.is_file():
        _journal.record('package_identified',manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest())
    sys.excepthook=lambda kind,error,tb:_journal.exception('unhandled_exception',error)
    threading.excepthook=lambda args:_journal.exception('worker_unhandled_exception',args.exc_value,worker=args.thread.name)
    atexit.register(lambda:_journal.record('session_finished'))
    return _journal


def install_tk_hook(root):
    def callback(kind,error,tb):
        get_journal().exception('ui_callback_exception',error)
        from tkinter import messagebox
        messagebox.showerror('操作未完成','错误已写入运行日志。请从“运行记录”导出诊断包。',parent=root)
    root.report_callback_exception=callback
