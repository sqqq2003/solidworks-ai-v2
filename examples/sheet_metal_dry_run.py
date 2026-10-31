"""Synthetic plate smoke example; generates JSON traces, never SLDPRT/DWG."""
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'src')]
import ezdxf
from cad_analyzer import analyze_dxf
from sheet_metal_pipeline import build_plan, run_plan, MockSheetMetalPort


def main():
    folder = ROOT/'runtime/p0-synthetic-example'
    folder.mkdir(parents=True, exist_ok=True)
    source = folder/'synthetic-plate.dxf'
    if not source.exists():
        doc = ezdxf.new('R2010')
        doc.units = ezdxf.units.MM
        model = doc.modelspace()
        model.add_lwpolyline([(0,0),(100,0),(100,80),(0,80)], close=True)
        model.add_circle((20,20), 4)
        doc.layers.new('BEND', dxfattribs={'color':1})
        model.add_line((50,0),(50,80), dxfattribs={'layer':'BEND','color':1})
        doc.saveas(source)
    analysis = analyze_dxf(source)
    outer = next(i for i, p in enumerate(analysis.profiles) if p.kind != 'CIRCLE')
    plan = build_plan(analysis, profile_index=outer, thickness_mm=2.5, radius_mm=1,
                      angle_degrees=90, k_factor=.4, flip_direction=False,
                      relief_bend_indices=(0,), bends_confirmed=True)
    result = run_plan(analysis, plan, folder/'output', MockSheetMetalPort())
    print(json.dumps({'sample': 'synthetic_not_customer_cad', 'plan': plan, 'result': result},
                     ensure_ascii=False, indent=2))
    return 0 if result['status'] == 'simulated_pass' else 1


if __name__ == '__main__':
    raise SystemExit(main())
