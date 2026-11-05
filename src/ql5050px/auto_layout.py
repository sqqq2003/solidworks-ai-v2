"""Place three first-angle views at the requested scale; never shrink geometry.

Returned coordinates are GetOutline centers on the sheet. SolidWorks
``View.Position`` is the model geometric center and can sit away from that
outline; ``position_for_outline_center`` turns a center into the Position
to write. This module does not change scale.
"""
import math


class LayoutDoesNotFit(ValueError):
    def __init__(self,message,*,diagnostic=None,alternatives=None):
        super().__init__(message)
        self.diagnostic=diagnostic or {}
        self.alternatives=alternatives or []


def position_for_outline_center(center_mm, anchor_mm):
    """``anchor`` is ``Position - outline center``, both in mm. Translation keeps it."""
    if len(center_mm)!=2 or len(anchor_mm)!=2 or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in (*center_mm,*anchor_mm)):
        raise ValueError('drawing anchor must be two finite coordinates')
    return [center_mm[0]+anchor_mm[0], center_mm[1]+anchor_mm[1]]


def rectangles_overlap(a, b):
    """Same 0.1 mm test the drawing verifier uses for views and the title block."""
    return min(a[2],b[2])-max(a[0],b[0])>.1 and min(a[3],b[3])-max(a[1],b[1])>.1


def _refuse(sizes):
    text=','.join(f'{name}:[{sizes[name][0]:.2f},{sizes[name][1]:.2f}]' for name in ('front','top','right'))
    raise LayoutDoesNotFit('layout_does_not_fit_requested_scale; choose a larger sheet or explicitly change scale; sizes_mm={'+text+'}',diagnostic={'sizes_mm':sizes})


def explicit_fit_alternatives(sizes,current_scale,current_sheet):
    """Paper-space estimates for user choices; never change the live drawing."""
    ratio=float(current_scale[0])/float(current_scale[1])
    if not math.isfinite(ratio) or ratio<=0:raise ValueError('positive current scale required')
    choices=[]
    for sheet,width,height in [('A2',594,420),('A3',420,297)]:
        for denominator in (5,10,20):
            if [width,height]==list(current_sheet) and list(current_scale)==[1,denominator]:continue
            target=1/denominator
            scaled={name:[v*target/ratio for v in size] for name,size in sizes.items()}
            try:centers=first_angle_layout(width,height,scaled)
            except LayoutDoesNotFit:continue
            choices.append({'sheet':sheet,'sheet_mm':[width,height],'scale':[1,denominator],
                'estimated_view_sizes_mm':scaled,'estimated_centers_mm':centers,
                'explicit_user_choice_required':True,'native_and_visual_review_required':True})
    return choices


def _arranged(sizes, gap, left, bottom):
    fw,fh=sizes['front']; tw,th=sizes['top']; rw,rh=sizes['right']
    col=max(fw,tw); row=max(fh,rh)
    x=left+rw+gap+col/2
    y=bottom+th+gap+row/2
    centers={'front':[x,y],'right':[left+rw/2,y],'top':[x,bottom+th/2]}
    return centers, rw+gap+col, th+gap+row


def _boxes(centers, sizes):
    return {name:[centers[name][0]-sizes[name][0]/2, centers[name][1]-sizes[name][1]/2,
                  centers[name][0]+sizes[name][0]/2, centers[name][1]+sizes[name][1]/2]
            for name in centers}


def _outside_frame(box, width, height):
    # Same edges as view_exceeds_frame(default_frame_mm(width, height)).
    frame=(25, 10, width-10, height-10)
    return box[0]<frame[0]-.1 or box[1]<frame[1]-.1 or box[2]>frame[2]+.1 or box[3]>frame[3]+.1


def _clean(boxes, width, height):
    title=[width-180, 0, width, 60]
    names=list(boxes)
    if any(_outside_frame(box, width, height) or rectangles_overlap(box, title) for box in boxes.values()):
        return False
    return not any(rectangles_overlap(boxes[a], boxes[b]) for i,a in enumerate(names) for b in names[i+1:])


def first_angle_layout(width, height, sizes, gap=10, *, centered=False):
    if set(sizes)!={'front','top','right'}:raise ValueError('three standard views required')
    if any(len(v)!=2 or any(not math.isfinite(n) or n<=0 for n in v) for v in sizes.values()):
        raise ValueError('positive finite view sizes required')
    _,group_w,group_h=_arranged(sizes, gap, 0, 0)
    # (30, 15) is the historical bottom-left slot. The later slots clear the
    # GB title block or sit in the rest of the frame. The first clean slot wins.
    origins=[]
    if centered:
        # Center the complete aligned group in the usable drawing body,
        # keeping the requested scale and first-angle relationships intact.
        origins.extend([((25+width-10-group_w)/2,(60+gap+height-10-group_h)/2),
                        ((25+width-10-group_w)/2,(10+height-10-group_h)/2)])
    origins.extend([(30, 15), (30, 60+gap), (25, 10), (25, 60+gap)])
    title_left=width-180
    if group_w+gap<=title_left-25:
        origins.append((25, 10))
    else:
        origins.append((max(25.0, title_left-gap-group_w), 60+gap))
    seen=set()
    for left,bottom in origins:
        key=(round(left,3), round(bottom,3))
        if key in seen:continue
        seen.add(key)
        if left<25-.1 or bottom<10-.1:continue
        if left+group_w>width-10+.1 or bottom+group_h>height-10+.1:continue
        centers,_,_=_arranged(sizes, gap, left, bottom)
        if _clean(_boxes(centers, sizes), width, height):return centers
    _refuse(sizes)
