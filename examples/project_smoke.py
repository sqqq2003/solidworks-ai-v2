"""Whole-project offline smoke using synthetic drawings; never starts SolidWorks."""
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT),str(ROOT/'src')]
import ezdxf
from project_workbench import run_batch, write_report


def make(path,points,*,axis=False):
    if path.exists():
        return
    doc = ezdxf.new('R2010')
    doc.units = ezdxf.units.MM
    m = doc.modelspace()
    m.add_lwpolyline(points,close=True)
    if axis:
        doc.layers.new('中心线')
        m.add_line((-5,0),(125,0),dxfattribs={'layer':'中心线'})
    doc.saveas(path)


def main():
    folder = ROOT/'runtime/whole-project-smoke'
    folder.mkdir(parents=True,exist_ok=True)
    plate,shaft,roller = folder/'synthetic-plate.dxf',folder/'synthetic-shaft.dxf',folder/'synthetic-1.0米无动力滚筒.dxf'
    make(plate,[(0,0),(100,0),(100,80),(0,80)])
    make(shaft,[(0,8),(120,8),(120,-8),(0,-8)],axis=True)
    make(roller,[(0,25),(1000,25),(1000,-25),(0,-25)])
    jobs = [
        {'name':'synthetic sheet analysis','kind':'sheet','action':'analyze','source':str(plate)},
        {'name':'synthetic sheet plan','kind':'sheet','action':'plan','source':str(plate),
         'profile':1,'thickness':2.5,'radius':1,'angle':90,'k_factor':.4},
        {'name':'synthetic roller missing dimensions','kind':'roller','action':'plan','source':str(roller)},
        {'name':'synthetic turned plan','kind':'turned','action':'plan','source':str(shaft),'variant':0},
        {'name':'GT-ZX legacy pending mappings (not QL)','kind':'parametric','machine':'GT-ZX','length':1800,'width':900,'height':1500}]
    (folder/'jobs.json').write_text(json.dumps({'schema_version':1,'sample':'synthetic_only','jobs':jobs},ensure_ascii=False,indent=2),encoding='utf-8')
    report = run_batch(jobs)
    path = write_report(report,folder)
    print(json.dumps({'sample':'synthetic_only','counts':report['counts'],'report':str(path)},ensure_ascii=False,indent=2))
    return 1 if report['counts'].get('failed') else 0


if __name__ == '__main__':
    raise SystemExit(main())

