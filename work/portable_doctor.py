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
    for name in ('tkinter','ezdxf','numpy','pypdf','pythoncom','win32com.client','comtypes','desktop_ui','app_logging','capability_registry','PIL.Image','PIL._imaging','ezdxf.addons.drawing'):
        try:importlib.import_module(name);checks[name]='ok'
        except Exception as error:checks[name]=str(error)
    try:
        import tkinter as tk
        root=tk.Tk();root.withdraw();root.update();root.destroy();checks['tk_window']='ok'
    except Exception as error:checks['tk_window']=str(error)
    try:
        import os
        import ezdxf
        from dxf_annotation_layout import fit_single_line_mtext,rendered_mtext_extent
        doc=ezdxf.new()
        font=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts/arial.ttf'
        if not font.is_file():raise RuntimeError('Windows Arial font unavailable')
        doc.styles.new('Doctor',dxfattribs={'font':str(font)})
        text=doc.modelspace().add_mtext('Part 640mm',dxfattribs={'char_height':12,'style':'Doctor'})
        fit_single_line_mtext(text,(0,0,60,14),padding=2,minimum_height=2,
                              extent_reader=rendered_mtext_extent)
        box=rendered_mtext_extent(text)
        if not (box.has_data and box.extmin.x>=2-1e-7 and box.extmax.x<=58+1e-7
                and box.extmin.y>=2-1e-7 and box.extmax.y<=12+1e-7):
            raise RuntimeError('rendered glyph fit exceeded the test cell')
        checks['drawing_glyph_fit']='ok'
    except Exception as error:checks['drawing_glyph_fit']=str(error)
    report={'python':sys.version,'executable':sys.executable,'bits':struct.calcsize('P')*8,'checks':checks,'cad_executed':False,'status':'pass' if all(v=='ok' for v in checks.values()) else 'failed'}
    journal.record('doctor_completed',level='INFO' if report['status']=='pass' else 'ERROR',report=report)
    (ROOT/'runtime/doctor-latest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0 if report['status']=='pass' else 1


if __name__=='__main__':raise SystemExit(main())
