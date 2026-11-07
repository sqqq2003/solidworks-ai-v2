"""Place a drawing note or table after InsertNote / InsertBomTable.

Live A2 1:10 and A2 1:20 on ``9dd6908`` raised ``AttributeError: GetAnnotation``
before any COM call: ``InsertNote`` returns a note whose Python class does
not declare ``GetAnnotation``. That name is now invoked as a property and as
a method. ``SetPosition2`` still recasts to ``IAnnotation`` when the pointer
has ``_oleobj_``. No session rebind.
"""

from part_verification import is_member_not_found

from .com_access import read_com_member


def _cast_annotation(raw):
    if raw is None or '_oleobj_' not in getattr(raw, '__dict__', {}):
        return None
    from solidworks_generator import _as_interface, ensure_solidworks_typelib
    try:
        return _as_interface(ensure_solidworks_typelib(), raw, 'IAnnotation')
    except Exception as exc:
        if is_member_not_found(exc):
            return None
        raise


def resolve_annotation(owner):
    try:
        found = read_com_member(owner, 'GetAnnotation')
    except Exception as exc:
        if is_member_not_found(exc):
            raise RuntimeError('drawing annotation missing: DISP_E_MEMBERNOTFOUND') from exc
        raise
    if found is None:
        raise RuntimeError('drawing annotation missing')
    return found


def _targets(annotation):
    typed = _cast_annotation(annotation)
    ordered = []
    if typed is not None:
        ordered.append(typed)
    if annotation not in ordered:
        ordered.append(annotation)
    return ordered


def set_annotation_position(owner, x, y, z=0):
    """Move ``owner``'s annotation to sheet meters. False is still a failure."""
    annotation = resolve_annotation(owner)
    last = None
    for target in _targets(annotation):
        try:
            ok = read_com_member(target, 'SetPosition2', x, y, z)
        except Exception as exc:
            last = exc
            if is_member_not_found(exc):
                continue
            raise
        if not ok:
            raise RuntimeError('drawing annotation position failed')
        return True
    raise RuntimeError('drawing annotation position failed: DISP_E_MEMBERNOTFOUND') from last


def read_annotation_position(owner):
    """Return the annotation point array used for BOM bounds."""
    annotation = resolve_annotation(owner)
    last = None
    for target in _targets(annotation):
        try:
            return read_com_member(target, 'GetPosition')
        except Exception as exc:
            last = exc
            if is_member_not_found(exc):
                continue
            raise
    raise RuntimeError('drawing annotation position unreadable: DISP_E_MEMBERNOTFOUND') from last
