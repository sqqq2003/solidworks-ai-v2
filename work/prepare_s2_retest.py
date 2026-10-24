"""Prepare an explicitly parameterized synthetic S1/S2 test; never launch CAD."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'src')]


def prepare(folder,*,thickness,radius,angle,k_factor,sw_exe):
    import math
    import ezdxf
    from cad_analyzer import analyze_dxf,primitive_bounds
    from sheet_metal_pipeline import code_hash
    parameters=dict(thickness_mm=thickness,radius_mm=radius,angle_degrees=angle,k_factor=k_factor)
    if not all(type(v) in (int,float) and math.isfinite(v) for v in parameters.values()):
        raise ValueError('explicit finite fixture parameters required')
    if thickness<=0 or radius<=0 or not 0<angle<180 or not 0<=k_factor<=1:
        raise ValueError('fixture parameters out of range')
    folder=Path(folder).resolve()
    if any(part.casefold()=='desktop' for part in folder.parts):
        raise ValueError('desktop output is forbidden')
    folder.mkdir(parents=True,exist_ok=False)
    source=folder/'synthetic-s2-100x80.dxf'
    doc=ezdxf.new('R2010');doc.units=ezdxf.units.MM
    m=doc.modelspace()
    m.add_lwpolyline([(0,0),(100,0),(100,80),(0,80)],close=True)
    m.add_circle((20,20),4)
    doc.layers.new('BEND',dxfattribs={'color':1})
    m.add_line((50,0),(50,80),dxfattribs={'layer':'BEND','color':1})
    doc.saveas(source)
    analysis=analyze_dxf(source)
    def area(profile):
        x0,y0,x1,y1=primitive_bounds(profile)
        return (x1-x0)*(y1-y0)
    index=max(range(len(analysis.profiles)),key=lambda i:area(analysis.profiles[i]))
    argv=[sys.executable,'-X','utf8',str(ROOT/'work/run_sheet_metal.py'),str(source),
          '--profile',str(index),'--thickness',str(thickness),'--radius',str(radius),
          '--angle',str(angle),'--k-factor',str(k_factor),'--direction','normal',
          '--confirm-bends','--no-relief-retries','--live','--sw-exe',str(sw_exe),
          '--out',str(folder/'native'),'--diagnostic-log',str(folder/'session.log')]
    modules=['src/solidworks_generator.py','src/sw_session.py','src/sw_owned_launch.py','src/sheet_metal_windows.py']
    report=dict(scope='synthetic_fixture_only_not_production',cad_executed=False,
                parameters=parameters,profile_index=index,index_base=0,
                source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                code_sha256=code_hash(),
                loaded_code_sha256={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in modules},
                command_argv=argv,command_windows=subprocess.list2cmdline(argv),
                expected='S1/S2/S3 published native feature evidence; clean exit separately verified')
    (folder/'retest-plan.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--sw-exe',type=Path,required=True)
    for name in ('thickness','radius','angle','k-factor'):
        p.add_argument('--'+name,type=float,required=True)
    a=p.parse_args()
    result=prepare(a.out,thickness=a.thickness,radius=a.radius,angle=a.angle,k_factor=a.k_factor,sw_exe=a.sw_exe)
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':
    main()
