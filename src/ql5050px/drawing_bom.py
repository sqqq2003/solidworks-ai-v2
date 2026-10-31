"""Deterministic BOM, drawing data, ASCII DXF and controlled native export."""
import csv
import json
from math import isfinite
from pathlib import Path


def build_bom(components):
    """Rows require part_number, material and positive integer quantity.

    A part/configuration/material/purchase identity groups repeated instances.
    Missing OEM fields are retained explicitly as pending, never invented.
    """
    grouped = {}
    for c in components:
        qty = c.get("quantity",1)
        if isinstance(qty,bool) or not isinstance(qty,int) or qty <= 0:
            raise ValueError("BOM quantity must be positive integer")
        number = c.get("part_number")
        if not isinstance(number,str) or not number.strip():
            raise ValueError("stable part_number required; use explicit provisional identifier")
        key = (number,c.get("configuration",""),c.get("material") or "pending_mapping",bool(c.get("purchased")))
        if key not in grouped:
            grouped[key] = {"part_number": key[0], "configuration": key[1], "material": key[2],
                            "purchased": key[3], "quantity": 0, "instances": [],
                            "status": "pending_mapping" if key[2] == "pending_mapping" else "declared_input"}
        grouped[key]["quantity"] += qty
        grouped[key]["instances"].append(c.get("id",number))
    return [dict(item=i,**grouped[k]) for i,k in enumerate(sorted(grouped),1)]


def export_bom_csv(bom, path):
    fields = ["item","part_number","configuration","material","purchased","quantity","status"]
    with Path(path).open("x",encoding="utf-8-sig",newline="") as stream:
        writer = csv.DictWriter(stream,fieldnames=fields,extrasaction="ignore")
        writer.writeheader()
        writer.writerows(bom)
    return str(path)


def drawing_model(part_number, *, material=None, dimensions_mm=None, views=(), notes=(), bom=()):
    dimensions = dict(dimensions_mm or {})
    for name,value in dimensions.items():
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not isfinite(value):
            raise ValueError(f"invalid drawing dimension {name}")
    return {"schema_version": 1, "units": "mm", "part_number": part_number,
            "material": material, "dimensions_mm": dimensions, "views": list(views),
            "notes": list(notes), "bom": list(bom), "native_status": "unverified"}


def export_drawing_json(model,path):
    with Path(path).open("x",encoding="utf-8") as stream:
        json.dump(model,stream,ensure_ascii=False,indent=2,allow_nan=False)
    return str(path)


def write_dxf(segments,path):
    """Minimal AC1015 DXF in mm with LINE entities and explicit layer table."""
    rows = list(segments)
    layers = set()
    for a,b,layer in rows:
        if len(a) != 2 or len(b) != 2 or not all(isinstance(v,(int,float)) and not isinstance(v,bool) and isfinite(v) for v in (*a,*b)):
            raise ValueError("finite 2D line coordinates required")
        if not layer or not layer.isascii() or any(ch in layer for ch in '\r\n<>/\\":;?*|=,'):
            raise ValueError("invalid DXF layer")
        layers.add(layer)
    data = ["0","SECTION","2","HEADER","9","$ACADVER","1","AC1015","9","$INSUNITS","70","4","0","ENDSEC",
            "0","SECTION","2","TABLES","0","TABLE","2","LAYER","70",str(len(layers))]
    for layer in sorted(layers):
        data += ["0","LAYER","2",layer,"70","0","62","7","6","CONTINUOUS"]
    data += ["0","ENDTAB","0","ENDSEC","0","SECTION","2","ENTITIES"]
    for a,b,layer in rows:
        data += ["0","LINE","8",layer,"10",str(a[0]),"20",str(a[1]),"30","0",
                 "11",str(b[0]),"21",str(b[1]),"31","0"]
    data += ["0","ENDSEC","0","EOF"]
    with Path(path).open("x",encoding="ascii") as stream:
        stream.write("\n".join(data)+"\n")
    return str(path)


def export_native_drawing(port, drawing_request, destination):
    from .control import export_native
    return export_native(port,drawing_request,destination,"drawing")
