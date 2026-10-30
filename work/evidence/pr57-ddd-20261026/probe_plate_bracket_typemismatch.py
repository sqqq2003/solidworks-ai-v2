# -*- coding: utf-8 -*-
from __future__ import annotations
import json, sys, traceback
from pathlib import Path
OUT = Path(__file__).resolve().parent
ROOT = Path(r"C:\Users\yue\Desktop\solidworks-ai-v2")
sys.path.insert(0, str(ROOT / "src"))
SW_EXE = r"D:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\SLDWORKS.exe"
PART = OUT / "plate_bracket_probe.SLDPRT"
REPORT = OUT / "plate_bracket_live.json"

def main() -> int:
    from sw_owned_launch import owned_solidworks
    from sw_session import run_on_task_sta, current_lease
    from sw_feature_calls import solid_blind_cut, solid_blind_extrude
    import solidworks_generator as sw
    result = {"probe": "plate_bracket_typemismatch", "part": str(PART), "events": []}
    def job():
        body_err = None
        with owned_solidworks(SW_EXE) as binding:
            result["session"] = binding.evidence()
            try:
                app = binding.app
                module = sw.ensure_solidworks_typelib()
                typed = sw._as_interface(module, app, "ISldWorks")
                lease = current_lease()
                if lease is not None:
                    lease.note_bound_application(typed)
                sw._set_sw_automation_mode(typed, True)
                template_path = typed.GetUserPreferenceStringValue(sw.SW_DEFAULT_TEMPLATE_PART)
                raw_model = typed.NewDocument(str(template_path), 0, 0.0, 0.0)
                model = sw._as_interface(module, raw_model, "IModelDoc2")
                title = model.GetTitle
                if callable(title): title = title()
                if lease is not None:
                    lease.note_owned_document(str(title), handle_id=id(raw_model))
                fm = sw._as_interface(module, model.FeatureManager, "IFeatureManager")
                sm = sw._as_interface(module, model.SketchManager, "ISketchManager")
                planes = [f for f in sw._features(model, module) if f.GetTypeName2() == "RefPlane"]
                plane = planes[0]
                for p in planes:
                    name = p.Name; name = name() if callable(name) else name
                    if "Front" in str(name) or "前" in str(name):
                        plane = p; break
                model.ClearSelection2(True)
                if not sw._as_interface(module, plane, "IEntity").Select4(False, None):
                    raise RuntimeError("plane Select4 failed")
                sm.InsertSketch(True)
                sm.CreateCornerRectangle(-0.02, -0.015, 0.0, 0.02, 0.015, 0.0)
                sm.InsertSketch(True)
                boss = None
                for merge in (False, True):
                    try: boss = solid_blind_extrude(fm, 0.003, merge=merge)
                    except Exception as e:
                        result["events"].append({"extrude_err": f"{type(e).__name__}:{e}", "merge": merge}); boss=None
                    if boss is not None:
                        result["events"].append({"extrude_ok": True, "merge": merge}); break
                if boss is None: raise RuntimeError("extrude failed")
                model.ClearSelection2(True)
                if not sw._as_interface(module, plane, "IEntity").Select4(False, None):
                    raise RuntimeError("plane reselect failed")
                sm.InsertSketch(True)
                sm.CreateCircleByRadius(0.0, 0.0, 0.0, 0.004)
                sm.InsertSketch(True)
                raw_latest = model.FeatureByPositionReverse(0)
                latest = sw._as_interface(module, raw_latest, "IFeature")
                sketch_name = latest.Name
                if callable(sketch_name): sketch_name = sketch_name()
                result["events"].append({"cut_sketch": str(sketch_name), "type": latest.GetTypeName2()})
                model.ClearSelection2(True)
                if not sw._as_interface(module, latest, "IEntity").Select4(False, None):
                    raise RuntimeError("sketch Select4 failed")
                typemismatch = {}
                try:
                    solid_blind_cut(fm, "0.01", reverse=False)
                    typemismatch["helper_rejects_str"] = "DID_NOT_RAISE"
                except TypeError as e:
                    typemismatch["helper_rejects_str"] = f"TypeError:{e}"
                except Exception as e:
                    typemismatch["helper_rejects_str"] = f"{type(e).__name__}:{e}"
                # re-select sketch after helper reject attempt
                model.ClearSelection2(True)
                sw._as_interface(module, latest, "IEntity").Select4(False, None)
                try:
                    cut = solid_blind_cut(fm, 0.01, reverse=False)
                    typemismatch["solid_blind_cut"] = {"ok": cut is not None, "name": getattr(cut, "Name", None)}
                except Exception as e:
                    hresult = e.args[0] if getattr(e, "args", None) else None
                    typemismatch["solid_blind_cut"] = {
                        "ok": False, "error": f"{type(e).__name__}: {e}", "hresult": hresult,
                        "is_typemismatch": hresult == -2147352571 or "TYPEMISMATCH" in str(e).upper() or "类型不匹配" in str(e),
                    }
                result["typemismatch"] = typemismatch
                if PART.exists(): PART.unlink()
                err = model.SaveAs3(str(PART), 0, 2)
                result["save_error_code"] = int(err) if err is not None else None
                result["part_exists"] = PART.exists()
                result["part_bytes"] = PART.stat().st_size if PART.exists() else 0
                cut_ok = bool((typemismatch.get("solid_blind_cut") or {}).get("ok"))
                helper_ok = str(typemismatch.get("helper_rejects_str","")).startswith("TypeError")
                result["TYPEMISMATCH_repros"] = bool((typemismatch.get("solid_blind_cut") or {}).get("is_typemismatch"))
                result["status"] = "pass" if (cut_ok and helper_ok and result["part_exists"]) else ("partial" if result.get("part_exists") else "fail")
                result["sw_live_verified"] = bool(cut_ok and result.get("part_exists"))
            except Exception as e:
                body_err = e
                result["body_error"] = f"{type(e).__name__}: {e}"
                result["body_trace"] = traceback.format_exc()[-2000:]
                result["status"] = result.get("status") or "fail"
        if body_err is not None and result.get("status") not in {"pass","partial"}:
            raise body_err
        return 0 if result.get("status") in {"pass","partial"} else 1
    try:
        rc = run_on_task_sta(job, timeout=240, task_name="probe-plate-bracket")
        result["exit_code"] = rc
    except Exception as e:
        result.setdefault("status","fail")
        result["error"] = f"{type(e).__name__}: {e}"
        result["trace"] = traceback.format_exc()[-2500:]
        result["exit_code"] = 1
        if result.get("part_exists") and (result.get("typemismatch") or {}).get("solid_blind_cut",{}).get("ok"):
            result["status"]="partial"; result["sw_live_verified"]=True; result["note"]="feature ok; cleanup raised"
    REPORT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: result.get(k) for k in ("status","sw_live_verified","TYPEMISMATCH_repros","exit_code","typemismatch","part_bytes","error","body_error","note","events")}, ensure_ascii=False))
    return 0 if result.get("sw_live_verified") else 1
if __name__ == "__main__":
    raise SystemExit(main())
