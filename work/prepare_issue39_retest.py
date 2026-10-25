"""Create a synthetic S1/S2 repro and exact argument vectors; never starts COM."""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out',type=Path,required=True);p.add_argument('--sw-exe',type=Path,required=True)
    for name in ('length','width','bend-x','thickness','radius','angle','k-factor'):p.add_argument('--'+name,type=float,required=True)
    p.add_argument('--direction',choices=('normal','reverse'),required=True);a=p.parse_args()
    if min(a.length,a.width)<=0 or not 0<a.bend_x<a.length:raise ValueError('explicit rectangle/bend geometry invalid')
    root=a.out.resolve();root.mkdir(parents=True,exist_ok=False)
    import ezdxf
    from cad_analyzer import analyze_dxf
    from sheet_metal_pipeline import build_plan
    doc=ezdxf.new('R2010');doc.units=4;space=doc.modelspace()
    space.add_lwpolyline([(0,0),(a.length,0),(a.length,a.width),(0,a.width)],close=True)
    doc.layers.new('BEND',dxfattribs={'color':1});space.add_line((a.bend_x,0),(a.bend_x,a.width),dxfattribs={'layer':'BEND','color':1})
    source=root/'synthetic-issue39.dxf';doc.saveas(source);analysis=analyze_dxf(source)
    candidates=[i for i,r in enumerate(analysis.profiles) if r.kind!='CIRCLE' and len(r.points)>=4]
    if len(candidates)!=1:raise RuntimeError('synthetic rectangle did not resolve uniquely')
    profile=candidates[0];plan=build_plan(analysis,profile_index=profile,thickness_mm=a.thickness,radius_mm=a.radius,
        angle_degrees=a.angle,k_factor=a.k_factor,flip_direction=a.direction=='reverse',units_confirmed=True,bends_confirmed=True)
    if len(plan['bend_indices'])!=1 or plan['pending']:raise RuntimeError('synthetic one-bend fixture unresolved')
    params=['--profile',str(profile),'--thickness',str(a.thickness),'--radius',str(a.radius),'--angle',str(a.angle),
        '--k-factor',str(a.k_factor),'--direction',a.direction,'--confirm-bends','--confirm-unitless-mm','--no-relief-retries']
    commands=[{'id':'minimal-exit','command':[sys.executable,'-X','utf8',str(ROOT/'src/run_recovery.py'),'--sw-exe',str(a.sw_exe),'--repeat','3','--output-dir',str(root/'minimal-exit')]},
        {'id':'offline-fixture','command':[sys.executable,'-X','utf8',str(ROOT/'work/run_sheet_metal.py'),str(source),*params,'--dry-run','--out',str(root/'offline')]},
        {'id':'native-S1-S2','command':[sys.executable,'-X','utf8',str(ROOT/'work/run_sheet_metal.py'),str(source),*params,'--live','--sw-exe',str(a.sw_exe),'--out',str(root/'native'),'--diagnostic-log',str(root/'native-diagnostic.log')]}]
    (root/'plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding='utf-8')
    (root/'commands.json').write_text(json.dumps(commands,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'status':'prepared_only','fixture':'synthetic matching reported sizes, not original evidence bytes','directory':str(root),'commands':commands,'native_acceptance':'pending_windows_validation'},ensure_ascii=False,indent=2))
    return 0

if __name__=='__main__':raise SystemExit(main())
