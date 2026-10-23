"""Callable development fixture; invented example geometry is not OEM mapping.

From repo root: python examples/ql5050px_batch.py --output NEW_DIRECTORY
All outputs are offline simulation fixtures; tests/test_ql5050px_cli.py runs it.
"""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from ql5050px import build_plan, inspect_assembly, sample_motion, unfold_strip, build_bom
from ql5050px.control import execute_variant
from ql5050px.drawing_bom import drawing_model, export_drawing_json, export_bom_csv
from ql5050px.sheet_metal import export_blank_dxf


def main(output):
    output.mkdir(parents=True,exist_ok=False)
    plan = build_plan()
    # Empty mapping deliberately exercises refusal, not an SW transaction pass.
    control = execute_variant(plan,{"schema_version":1,"parameters":[]},output/"variant.sldasm")
    components = [
        {"id":"fixture_base","part_number":"SIM-BASE","material":"simulation", "fixed":True,"bbox_mm":[0,0,0,100,100,10]},
        {"id":"fixture_slide","part_number":"SIM-SLIDE","material":"simulation","expected_dof":1,"bbox_mm":[10,10,20,30,30,30]},
    ]
    mates = [{"a":"fixture_base","b":"fixture_slide","type":"concentric"},
             {"a":"fixture_base","b":"fixture_slide","type":"distance"}]
    assembly = inspect_assembly(components,mates)
    motion = sample_motion(components,{"fixture_slide":lambda t:(0,0,-20*t)},[0,0.5,1])
    blank = unfold_strip([100,50,100],[90,90],thickness_mm=2,radius_mm=2,k_factor=0.44,width_mm=80)
    export_blank_dxf(blank,output/"simulation_blank.dxf")
    bom = build_bom(components)
    export_bom_csv(bom,output/"simulation_bom.csv")
    drawing = drawing_model("SIM-STRIP",material="simulation",dimensions_mm={"length":blank["flat_length_mm"],"width":80},
                            notes=["Development fixture; not an OEM release"],bom=bom)
    export_drawing_json(drawing,output/"drawing.json")
    export_drawing_json({"plan":plan,"control":control,"assembly":assembly,"motion":motion,"blank":blank,
                         "test_status":"offline_simulation_only"},output/"batch.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",required=True,type=Path)
    main(parser.parse_args().output)
