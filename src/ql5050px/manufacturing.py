"""Material takeoff and manufacturing package handlers; no CAD imports required."""
from math import hypot
from .parameters import numeric


def panel_takeoff(panel, *, quantity=1, density_kg_m3=None, price_per_kg=None, scrap_fraction=0):
    """Use caller-sourced density/price; never assume an OEM material grade.

    Net area excludes holes. Purchased area uses bounding rectangle and caller
    scrap fraction; nesting, kerf, tool forces and bend sequencing are pending.
    """
    if isinstance(quantity,bool) or not isinstance(quantity,int) or quantity<=0:
        raise ValueError("positive integer quantity required")
    if isinstance(scrap_fraction,bool) or not isinstance(scrap_fraction,(int,float)) or not 0<=scrap_fraction<1:
        raise ValueError("scrap fraction must be in [0,1)")
    from .panel import edges
    outer = panel["outer_xy_mm"]
    width = max(p[0] for p in outer)-min(p[0] for p in outer)
    height = max(p[1] for p in outer)-min(p[1] for p in outer)
    cut = sum(hypot(b[0]-a[0],b[1]-a[1]) for contour in [outer,*panel["holes_xy_mm"]] for a,b in edges(contour))
    density = None if density_kg_m3 is None else numeric(density_kg_m3,"density")
    mass = None if density is None else panel["volume_mm3"]*1e-9*density*quantity
    stock_mass = None if density is None else width*height*panel["thickness_mm"]*1e-9*density*quantity/(1-scrap_fraction)
    price = None if price_per_kg is None else numeric(price_per_kg,"price per kg")
    return {"quantity":quantity,"net_area_m2":panel["net_area_mm2"]*1e-6*quantity,
            "stock_area_m2":width*height*1e-6*quantity/(1-scrap_fraction),
            "cut_length_mm":cut*quantity,"bend_count":len(panel["bends"])*quantity,
            "net_mass_kg":mass,"stock_mass_kg":stock_mass,
            "material_cost":None if stock_mass is None or price is None else stock_mass*price,
            "currency":"caller_defined","manufacturing_status":"estimate_only"}


def offline_runner(*, driver=None, native_port=None):
    """Compose real module calls into the resumable BatchRunner.

    Native operations remain disabled unless run(..., allow_native=True), and
    still require the host-owned transaction driver or WindowsExecutionPort.
    """
    from .batch import BatchRunner
    from .parameters import build_plan
    from .panel import develop_panel, panel_dxf
    from .bom_tree import explode_bom, compare_boms
    from .assembly import inspect_assembly
    from .drawing_bom import export_bom_csv
    from .drawing_layout import render_sheet_svg
    def panel(payload,folder):
        value = develop_panel(**payload)
        panel_dxf(value,folder/"blank.dxf")
        return value
    def bom(payload,folder):
        value = explode_bom(**payload)
        export_bom_csv(value["bom"],folder/"bom.csv")
        return value
    def drawing(payload,folder):
        render_sheet_svg(payload,folder/"sheet.svg")
        return {"file":"sheet.svg","native_status":"unverified"}
    handlers = {"parameters":lambda p,f:build_plan(**p),
                "panel":panel,"bom_tree":bom,
                "bom_diff":lambda p,f:compare_boms(**p),
                "assembly":lambda p,f:inspect_assembly(**p),
                "takeoff":lambda p,f:panel_takeoff(**p),"drawing_svg":drawing}
    from .assembly_builder import plan_assembly
    from .drive_variant import plan_drive
    from .manufacturing_drawings import plan_drawings
    from .machine_package import write_machine_package
    handlers.update(auto_assembly=lambda p,f:plan_assembly(**p),drive_variant=lambda p,f:plan_drive(**p),
                    manufacturing_drawings=lambda p,f:plan_drawings(**p),
                    machine_package=lambda p,f:write_machine_package(p,f/'execution-package'))
    if driver is not None:
        def variant(payload,folder):
            from .control import execute_variant
            result = execute_variant(payload["plan"],payload["mapping_payload"],folder/"variant.sldasm",driver=driver)
            if result.get("execution_status") not in {"readback_verified","no_changes"}:
                raise RuntimeError("native variant did not complete: " + str(result))
            return result
        handlers["native_variant"] = variant
    if native_port is not None:
        def drawing_native(payload,folder):
            from .control import export_native
            return export_native(native_port,payload,folder/"drawing.slddrw","drawing")
        def flat_native(payload,folder):
            from .control import export_native
            return export_native(native_port,payload,folder/"flat.dxf","flat_dxf")
        handlers.update(native_drawing=drawing_native,native_flat_dxf=flat_native)
    return BatchRunner(handlers,native_kinds={"native_variant","native_drawing","native_flat_dxf"})
