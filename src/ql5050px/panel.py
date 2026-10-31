"""Polygon tangent-base panels with independent straight edge flanges.

Input base lies on bend tangent lines, not outside virtual sharps. This is a
development construction, not a general folded-solid unfolding algorithm.
"""
from math import hypot, isfinite
from .parameters import numeric

EPS = 1e-8


def cross(a, b, c):
    return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])


def on_segment(p, a, b):
    return abs(cross(a,b,p)) < EPS and all(min(a[i],b[i])-EPS <= p[i] <= max(a[i],b[i])+EPS for i in (0,1))


def intersects(a,b,c,d):
    values = cross(a,b,c),cross(a,b,d),cross(c,d,a),cross(c,d,b)
    return (values[0]*values[1] < -EPS and values[2]*values[3] < -EPS) or any(
        on_segment(p,x,y) for p,x,y in ((c,a,b),(d,a,b),(a,c,d),(b,c,d)))


def edges(points):
    return list(zip(points,points[1:]+points[:1]))


def area(points):
    return sum(a[0]*b[1]-b[0]*a[1] for a,b in edges(points))/2


def polygon(points):
    result = []
    for p in points:
        if len(p) != 2 or not all(isinstance(v,(int,float)) and not isinstance(v,bool) and isfinite(v) for v in p):
            raise ValueError("polygon requires finite xy coordinates")
        result.append(tuple(map(float,p)))
    if len(result)>1 and result[0] == result[-1]:
        result.pop()
    if len(result)<3 or abs(area(result))<EPS:
        raise ValueError("nondegenerate polygon required")
    lines = edges(result)
    for i,(a,b) in enumerate(lines):
        if hypot(b[0]-a[0],b[1]-a[1])<EPS:
            raise ValueError("zero-length polygon edge")
        for j,(c,d) in enumerate(lines[i+1:],i+1):
            if j == i+1 or (i==0 and j==len(lines)-1):
                continue
            if intersects(a,b,c,d):
                raise ValueError("self-intersecting polygon")
    return result


def inside(p, points):
    if any(on_segment(p,a,b) for a,b in edges(points)):
        return False
    hit = False
    for a,b in edges(points):
        if (a[1]>p[1]) != (b[1]>p[1]):
            if p[0] < (b[0]-a[0])*(p[1]-a[1])/(b[1]-a[1])+a[0]:
                hit = not hit
    return hit


def develop_panel(base_xy_mm, flanges, *, thickness_mm, holes_xy_mm=()):
    """Flange: edge index, straight_mm, radius_mm, angle_deg, k_factor,
    start_gap_mm/end_gap_mm >= thickness. Indices refer to supplied CCW base.
    Gap leaves an open corner relief. Nested flanges and hems are unsupported.
    """
    from bend_allowance import compute_bend_allowance
    t = numeric(thickness_mm,"thickness")
    base = polygon(base_xy_mm)
    if area(base)<0:
        raise ValueError("base must be counterclockwise; preserve edge numbering")
    by_edge = {}
    for f in flanges:
        index = f["edge"]
        if isinstance(index,bool) or not isinstance(index,int) or not 0<=index<len(base) or index in by_edge:
            raise ValueError("one flange per existing base edge required")
        by_edge[index] = f
    outline, bends = [],[]
    for index,(a,b) in enumerate(edges(base)):
        outline.append(a)
        if index not in by_edge:
            continue
        f = by_edge[index]
        length = hypot(b[0]-a[0],b[1]-a[1])
        u = ((b[0]-a[0])/length,(b[1]-a[1])/length)
        outward = (u[1],-u[0])
        start = numeric(f.get("start_gap_mm",t),"start relief")
        end = numeric(f.get("end_gap_mm",t),"end relief")
        if min(start,end)<t or start+end>=length:
            raise ValueError("corner relief must be >= thickness and leave flange width")
        result = compute_bend_allowance(t,f["radius_mm"],f["angle_deg"],f["k_factor"])
        depth = numeric(f["straight_mm"],"straight flange")+result.bend_allowance_mm
        def point(along,out):
            return (a[0]+u[0]*along+outward[0]*out,a[1]+u[1]*along+outward[1]*out)
        outline.extend([point(start,0),point(start,depth),point(length-end,depth),point(length-end,0)])
        bends.append({"edge":index,"start_xy_mm":point(start,result.bend_allowance_mm/2),
                      "end_xy_mm":point(length-end,result.bend_allowance_mm/2),
                      "angle_deg":f["angle_deg"],"bend_allowance_mm":result.bend_allowance_mm,
                      "k_factor":f["k_factor"],"radius_mm":f["radius_mm"]})
    outline = polygon(outline)  # Reject overlapping flange developments.
    holes = [polygon(h) for h in holes_xy_mm]
    for i,hole in enumerate(holes):
        # Holes may only belong to tangent base in v1; reject crossing bend zones.
        if not all(inside(p,base) for p in hole) or any(intersects(a,b,c,d) for a,b in edges(hole) for c,d in edges(base)):
            raise ValueError("hole must lie strictly inside tangent base")
        for other in holes[:i]:
            if any(intersects(a,b,c,d) for a,b in edges(hole) for c,d in edges(other)) or inside(hole[0],other) or inside(other[0],hole):
                raise ValueError("overlapping or nested holes unsupported")
    net_area = abs(area(outline))-sum(abs(area(h)) for h in holes)
    return {"schema_version":1,"units":"mm","construction":"tangent_base_edge_flanges",
            "outer_xy_mm":outline,"holes_xy_mm":holes,"bends":bends,"thickness_mm":t,
            "net_area_mm2":net_area,"volume_mm3":net_area*t,"native_status":"unverified",
            "manufacturing_status":"review_required"}


def panel_dxf(panel, destination):
    from .drawing_bom import write_dxf
    segments = [(a,b,"CUT") for contour in [panel["outer_xy_mm"],*panel["holes_xy_mm"]] for a,b in edges(contour)]
    segments.extend((b["start_xy_mm"],b["end_xy_mm"],"BEND") for b in panel["bends"])
    return write_dxf(segments,destination)
