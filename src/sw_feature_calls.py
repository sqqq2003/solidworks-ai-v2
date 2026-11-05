"""Typed FeatureExtrusion2 / FeatureCut3 arguments.

SolidWorks late-binds these calls. A Python int where the typelib wants a
double is DISP_E_TYPEMISMATCH (-2147352571). Sheet-metal cuts set NormalCut
True; solid plate and bracket cuts set it False. There is no default.
"""
import math


def _bool(value, name):
    if type(value) is not bool:
        raise TypeError(name + ' must be an explicit bool')
    return value


def _int(value, name):
    if type(value) is not int:
        raise TypeError(name + ' must be an int end/start code')
    return value


def _float(value, name):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise TypeError(name + ' must be a finite float')
    return float(value)


def solid_blind_extrude(manager, depth_m, *, merge):
    """Blind solid boss. FeatureExtrusion2 has no NormalCut argument.

    ``merge`` is explicit: the first body on an empty part must be False on
    several SolidWorks versions; a joining boss passes True.
    """
    depth_m = _float(depth_m, 'depth_m')
    merge = _bool(merge, 'merge')
    return manager.FeatureExtrusion2(
        True, False, False,
        0, 0,
        depth_m, 0.0,
        False, False, False, False,
        0.0, 0.0,
        False, False, False, False,
        merge, True, True,
        0, 0.0, False,
    )


def solid_blind_cut(manager, depth_m, *, reverse):
    """Blind solid cut. NormalCut is False and is not copied from sheet metal."""
    depth_m = _float(depth_m, 'depth_m')
    reverse = _bool(reverse, 'reverse')
    return manager.FeatureCut3(
        True, False, reverse,
        0, 0,
        depth_m, 0.0,
        False, False, False, False,
        0.0, 0.0,
        False, False, False, False,
        False,
        True, True, True, True, False,
        0, 0.0, False,
    )


def sheet_metal_through_cut(manager):
    """Through-all sheet-metal hole. NormalCut stays True for the sheet body."""
    return manager.FeatureCut3(
        False, False, False,
        1, 0,
        0.005, 0.005,
        False, False, False, False,
        0.0, 0.0,
        False, False, False, False,
        True,
        False, True, False, False, False,
        0, 0.0, False,
    )


def solid_revolve(manager, angle_radians, *, merge):
    """Single-direction blind solid revolve, explicit axis selected by caller.

    FeatureRevolve2 uses twenty typed arguments. No thin/cut or guessed axis.
    """
    angle = _float(angle_radians, 'angle_radians')
    if not 0 < angle <= 2 * math.pi:
        raise ValueError('revolve angle must be in (0, 2*pi]')
    return manager.FeatureRevolve2(
        True, True, False, False, False, False, 0, 0,
        angle, 0.0, False, False, 0.0, 0.0, 0, 0.0, 0.0,
        _bool(merge, 'merge'), True, True,
    )


# Positions that the typelib types as double. Ints here are the r2 mismatch class.
DOUBLE_ARG_INDEXES = (5, 6, 11, 12, 24)
NORMAL_CUT_INDEX = 17
