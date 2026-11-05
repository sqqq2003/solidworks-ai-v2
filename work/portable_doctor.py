"""Portable runtime self-check; no SolidWorks activation."""
import importlib
import json
import struct
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'src')]


def main():
    from app_logging import bootstrap
    journal=bootstrap(ROOT,'portable-doctor')
    checks={}
    for name in ('tkinter','ezdxf','numpy','pypdf','pdfplumber','pythoncom','win32com.client','comtypes','desktop_ui','app_logging','capability_registry'):
        try:importlib.import_module(name);checks[name]='ok'
        except Exception as error:checks[name]=str(error)
    try:
        import tkinter as tk
        root=tk.Tk();root.withdraw();root.update();root.destroy();checks['tk_window']='ok'
    except Exception as error:checks['tk_window']=str(error)
    report={'python':sys.version,'executable':sys.executable,'bits':struct.calcsize('P')*8,'checks':checks,'cad_executed':False,'status':'pass' if all(v=='ok' for v in checks.values()) else 'failed'}
    journal.record('doctor_completed',level='INFO' if report['status']=='pass' else 'ERROR',report=report)
    (ROOT/'runtime/doctor-latest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0 if report['status']=='pass' else 1


if __name__=='__main__':raise SystemExit(main())
