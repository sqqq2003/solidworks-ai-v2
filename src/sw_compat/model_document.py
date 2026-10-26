"""Cast a late-bound SolidWorks document after NewDocument.

``ManufacturingDriver.export_manufacturing`` imports ``model_document`` and
replaces the raw ``NewDocument`` result with it. The pr53 patch pack and this
branch's history did not include the helper. This module is that cast only:
drawings become ``IDrawingDoc`` (sheet and view calls), other documents
become ``IModelDoc2``, using ``solidworks_generator``'s existing typelib
helper. Objects without a real ``_oleobj_`` pass through so offline fakes
stay fakes. No session connect, CloseDoc, or ExitApp.
"""


def _document_kind(raw):
    getter = getattr(raw, 'GetType', None)
    if getter is None:
        return None
    try:
        value = getter() if callable(getter) else getter
        return int(value)
    except (TypeError, ValueError):
        return None


def model_document(raw):
    if raw is None:
        raise RuntimeError('model document is missing')
    # Same probe the drawing verifier uses. MagicMock fabricates attributes
    # but does not put _oleobj_ in the instance dict.
    if '_oleobj_' not in getattr(raw, '__dict__', {}):
        return raw
    kind = _document_kind(raw)
    if kind is None:
        raise RuntimeError('cannot read document type before model cast')
    # swDocumentTypes_e: swDocDRAWING = 3. Drawing methods are on IDrawingDoc.
    interface = 'IDrawingDoc' if kind == 3 else 'IModelDoc2'
    from solidworks_generator import _as_interface, ensure_solidworks_typelib
    return _as_interface(ensure_solidworks_typelib(), raw, interface)
