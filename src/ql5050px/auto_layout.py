"""Place three first-angle views at the requested scale; never shrink geometry.

Returned coordinates are GetOutline centers on the sheet. SolidWorks
``View.Position`` is the model geometric center and can sit away from that
outline; ``position_for_outline_center`` turns a center into the Position
to write. This module does not change scale.
"""
import math


def position_for_outline_center(center_mm, anchor_mm):
    """``anchor`` is ``Position - outline center``, both in mm. Translation keeps it."""
    if len(center_mm)!=2 or len(anchor_mm)!=2 or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in (*center_mm,*anchor_mm)):
        raise ValueError('drawing anchor must be two finite coordinates')
    return [center_mm[0]+anchor_mm[0], center_mm[1]+anchor_mm[1]]


def first_angle_layout(width,height,sizes,gap=10):
    if set(sizes)!={'front','top','right'}:raise ValueError('three standard views required')
    if any(len(v)!=2 or any(not math.isfinite(n) or n<=0 for n in v) for v in sizes.values()):
        raise ValueError('positive finite view sizes required')
    fw,fh=sizes['front'];tw,th=sizes['top'];rw,rh=sizes['right']
    # Match actual outlines, including unequal top/front widths and right heights.
    col=max(fw,tw);row=max(fh,rh)
    group_width=rw+gap+col;group_height=row+gap+th
    left,bottom=30,15
    if left+group_width>width-10 or bottom+group_height>height-30:
        raise ValueError('layout_does_not_fit_requested_scale; choose a larger sheet or explicitly change scale')
    x=left+rw+gap+col/2;y=bottom+th+gap+row/2
    result={'front':[x,y],'right':[left+rw/2,y],'top':[x,bottom+th/2]}
    # Keep the bottom view away from the lower-right title block.
    if x+tw/2>width-180 and bottom<60:
        shift=60-bottom+gap
        if bottom+group_height+shift>height-30:raise ValueError('layout_title_block_conflict')
        for pos in result.values():pos[1]+=shift
    return result
