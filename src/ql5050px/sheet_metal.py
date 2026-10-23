"""Constant-width strip development and delegation to the existing SW generator."""
from dataclasses import asdict
from .parameters import numeric


def unfold_strip(legs_mm, angles_deg, *, thickness_mm, radius_mm, k_factor, width_mm,
                 relief_width_mm=None, relief_depth_mm=None):
    """Leg lengths measured to outside virtual sharps. One bend between each leg.

    Supports a serial strip, not arbitrary branching/curved sheet geometry.
    Bend direction does not affect this scalar blank length calculation.
    """
    from bend_allowance import compute_bend_allowance
    legs = [numeric(v,"leg") for v in legs_mm]
    width = numeric(width_mm,"width")
    if len(legs) < 2 or len(angles_deg) != len(legs)-1:
        raise ValueError("N legs require N-1 bends")
    angles = [numeric(a,"angle") for a in angles_deg]
    bends = [compute_bend_allowance(thickness_mm,radius_mm,a,k_factor) for a in angles]
    tangent = []
    for i,leg in enumerate(legs):
        setbacks = (bends[i-1].outside_setback_mm if i else 0) + (bends[i].outside_setback_mm if i < len(bends) else 0)
        if leg <= setbacks:
            raise ValueError(f"leg {i}: adjacent bend zones consume straight length")
        tangent.append(leg-setbacks)
    rw = numeric(thickness_mm if relief_width_mm is None else relief_width_mm,"relief width")
    rd = numeric(radius_mm+thickness_mm if relief_depth_mm is None else relief_depth_mm,"relief depth")
    if rw < thickness_mm or rd < radius_mm+thickness_mm or 2*rd >= width:
        raise ValueError("relief must clear bend and leave positive strip width")
    cursor = 0.0
    lines,slots = [],[]
    for i,bend in enumerate(bends):
        cursor += tangent[i]
        center = cursor+bend.bend_allowance_mm/2
        lines.append({"x_mm": center, "angle_deg": angles[i]})
        for y in (0,width-rd):
            slots.append({"x_mm": center-rw/2, "y_mm": y, "width_mm": rw, "depth_mm": rd})
        cursor += bend.bend_allowance_mm
    length = sum(tangent)+sum(b.bend_allowance_mm for b in bends)
    return {"units": "mm", "profile_kind": "serial_constant_width_strip",
            "flat_length_mm": length, "width_mm": width, "thickness_mm": thickness_mm,
            "radius_mm": radius_mm, "k_factor": k_factor, "bend_lines": lines,
            "relief_slots": slots, "bends": [asdict(b) for b in bends],
            "native_status": "unverified"}


def generate_native(analysis, output_path, *, generator_options):
    """Use an existing DrawingAnalysis; native generator owns session safeguards.

    generator_options is passed verbatim to the established generate_sheet_metal
    API, preserving that API's profile, bend and relief controls.
    """
    import sys
    from pathlib import Path
    if sys.platform != "win32":
        raise RuntimeError("native sheet generation requires Windows")
    output = Path(output_path).resolve()
    if output.exists() or output.suffix.lower() != ".sldprt":
        raise ValueError("new SLDPRT work output required")
    from solidworks_generator import generate_sheet_metal
    if "output_path" in generator_options:
        raise ValueError("output_path must be supplied only as output_path argument")
    return generate_sheet_metal(analysis=analysis, output_path=output, **generator_options)


def export_blank_dxf(blank, output_path):
    """Write developed contour with open-edge rectangular relief notches."""
    from .drawing_bom import write_dxf
    length,width = blank["flat_length_mm"],blank["width_mm"]
    slots = sorted(blank["relief_slots"], key=lambda s:s["x_mm"])
    points = [(0,0)]
    for s in (s for s in slots if s["y_mm"] == 0):
        x,w,d = s["x_mm"],s["width_mm"],s["depth_mm"]
        points.extend([(x,0),(x,d),(x+w,d),(x+w,0)])
    points.extend([(length,0),(length,width)])
    for s in sorted((s for s in slots if s["y_mm"] != 0),key=lambda s:-s["x_mm"]):
        x,w,y = s["x_mm"],s["width_mm"],s["y_mm"]
        points.extend([(x+w,width),(x+w,y),(x,y),(x,width)])
    points.extend([(0,width),(0,0)])
    segments = [(a,b,"CUT") for a,b in zip(points,points[1:])]
    segments += [((b["x_mm"],0),(b["x_mm"],width),"BEND") for b in blank["bend_lines"]]
    return write_dxf(segments,output_path)
