# -*- coding: utf-8 -*-
"""本机验收：夹具 DXF → 车件 SLDPRT → 量外包，并与成品对比。"""
from __future__ import annotations

import json
import math
import sys
import traceback
from pathlib import Path

ROOT = Path(r"C:\Users\yue\Downloads\cad2sw-dl\ext\CAD转SolidWorks")
sys.path.insert(0, str(ROOT))

OUT_DIR = Path(r"D:\工程\钣金导入\wb_pr57_full_20261026_134308\chejian")
DXF_DIR = Path(r"C:\Users\yue\Desktop\chejian_cmp\dxf_fixtures")
REPORT = Path(r"D:\工程\钣金导入\wb_pr57_full_20261026_134308\accept_chejian.json")
FIN_DIR = Path(r"C:\Users\yue\Desktop\QL-5050PX左右驱动一体封箱机\车件图")

CASES = [
    {"id": "f09", "file": "f09.dxf", "name": "主动轴", "expect": (166.0, 28.0, 28.0), "stock": "revolve"},
    {"id": "f11", "file": "f11.dxf", "name": "锁定柱", "expect": (75.0, 19.63, 17.0), "stock": "hex"},
    {"id": "f15", "file": "f15.dxf", "name": "导轮轴", "expect": (54.97, 10.0, 10.0), "stock": "revolve"},
    {"id": "f19", "file": "f19.dxf", "name": "延长轴", "expect": (385.0, 15.0, 15.0), "stock": "revolve"},
]


def sorted_dims_mm(box) -> tuple[float, float, float] | None:
    if not box or len(box) < 6:
        return None
    xs = [float(box[0]), float(box[3])]
    ys = [float(box[1]), float(box[4])]
    zs = [float(box[2]), float(box[5])]
    dx, dy, dz = abs(xs[1] - xs[0]), abs(ys[1] - ys[0]), abs(zs[1] - zs[0])
    # SW GetBodyBox is meters
    vals = sorted([dx, dy, dz], reverse=True)
    if max(vals) < 2.0:  # likely meters
        vals = [v * 1000.0 for v in vals]
    return (vals[0], vals[1], vals[2])


def measure_sldprt(path: Path) -> dict:
    import win32com.client

    result = {"path": str(path), "exists": path.exists()}
    if not path.exists():
        return result
    try:
        try:
            sw = win32com.client.GetActiveObject("SldWorks.Application")
        except Exception:
            sw = win32com.client.Dispatch("SldWorks.Application")
        sw.Visible = True
        doc = sw.OpenDoc(str(path), 1)  # swDocPART
        if doc is None:
            result["error"] = "OpenDoc returned None"
            return result
        try:
            bodies = doc.GetBodies2(0, False)  # solid
            body_dims = []
            if bodies:
                for b in bodies:
                    try:
                        box = b.GetBodyBox()
                        dims = sorted_dims_mm(box)
                        if dims:
                            body_dims.append(dims)
                    except Exception as e:
                        body_dims.append({"error": str(e)})
            result["bodies"] = body_dims
            if body_dims and isinstance(body_dims[0], tuple):
                result["LWH_mm"] = body_dims[0]
            try:
                result["title"] = doc.GetTitle
            except Exception:
                pass
        finally:
            sw.CloseDoc(doc.GetTitle)
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"
        result["trace"] = traceback.format_exc()[-1500:]
    return result


def within_tol(got, expect, rel=0.02, abs_mm=1.0) -> bool:
    if not got or not expect:
        return False
    for g, e in zip(got, expect):
        if abs(g - e) > max(abs_mm, abs(e) * rel):
            return False
    return True


def find_fin(keyword: str) -> Path | None:
    if not FIN_DIR.exists():
        return None
    hits = [p for p in FIN_DIR.glob("*.SLDPRT") if keyword in p.name and not p.name.startswith("~$")]
    return hits[0] if hits else None


def main() -> int:
    from cad_analyzer import analyze_cad_file
    from turned_part import generate_turned_part, plan_turned_part

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    report = {"cases": [], "ok": True}
    for case in CASES:
        row = dict(case)
        dxf = DXF_DIR / case["file"]
        out = OUT_DIR / f"{case['id']}_{case['name']}.SLDPRT"
        row["dxf"] = str(dxf)
        row["out"] = str(out)
        if out.exists():
            try:
                out.unlink()
            except Exception as e:
                row["unlink_error"] = str(e)
        try:
            analysis = analyze_cad_file(str(dxf))
            plan = plan_turned_part(analysis)
            row["plan"] = {
                "length_mm": getattr(plan, "length_mm", None),
                "max_radius_mm": getattr(plan, "max_radius_mm", None),
                "stock": getattr(plan, "stock", None),
                "stock_size_mm": getattr(plan, "stock_size_mm", None),
                "profile_n": len(getattr(plan, "profile", ()) or ()),
            }
            path = generate_turned_part(plan, str(out))
            row["generated"] = path
            row["measure"] = measure_sldprt(Path(path))
            got = row["measure"].get("LWH_mm")
            row["pass_expect"] = within_tol(got, case["expect"])
            if not row["pass_expect"]:
                report["ok"] = False
        except Exception as e:
            report["ok"] = False
            row["error"] = f"{type(e).__name__}: {e}"
            row["trace"] = traceback.format_exc()[-2000:]

        fin = find_fin(case["name"])
        if fin:
            row["fin_path"] = str(fin)
            row["fin_measure"] = measure_sldprt(fin)
            row["fin_size"] = fin.stat().st_size
            if out.exists():
                row["prog_size"] = out.stat().st_size
                row["size_ratio"] = round(out.stat().st_size / max(fin.stat().st_size, 1), 3)
        report["cases"].append(row)

    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": report["ok"], "report": str(REPORT), "n": len(report["cases"])}, ensure_ascii=False))
    for c in report["cases"]:
        print(
            c["id"],
            "PASS" if c.get("pass_expect") else "FAIL",
            "plan",
            (c.get("plan") or {}).get("length_mm"),
            "got",
            (c.get("measure") or {}).get("LWH_mm"),
            "fin",
            (c.get("fin_measure") or {}).get("LWH_mm"),
            "err",
            c.get("error") or (c.get("measure") or {}).get("error"),
        )
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
