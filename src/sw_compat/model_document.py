"""Cast a late-bound SolidWorks document after NewDocument.

A drawing is wrapped as both ``IDrawingDoc`` and ``IModelDoc2`` on the same
COM pointer. ``GetTitle`` and the other model members are read from
``IModelDoc2``. An ``IDrawingDoc``-only cast makes ``GetTitle`` hang on a
live session. Sheet and view members stay on ``IDrawingDoc``. Other
documents are ``IModelDoc2`` only. Objects without ``_oleobj_`` pass
through. No session connect, CloseDoc, or ExitApp.
"""

from .com_access import declared, read_document_kind

# Model identity members. Always use IModelDoc2. GetTitle on an IDrawingDoc-only
# wrapper hangs a live session even when the drawing class also lists it.
_MODEL_FACE = frozenset({
    'ClearSelection2',
    'EditRebuild3',
    'Extension',
    'FeatureByName',
    'FirstFeature',
    'GetPathName',
    'GetTitle',
    'GetType',
    'InsertNote',
    'Parameter',
    'Save3',
    'SaveAs3',
    'SetUnits',
})
# These exist on IDrawingDoc. Prefer that face even if a generated IModelDoc2
# wrapper also lists them.
_DRAWING_FACE = frozenset({
    'ActivateSheet',
    'CreateDrawViewFromModelView3',
    'CreateFlatPatternViewFromModelView3',
    'CreateUnfoldedViewAt3',
    'GetCurrentSheet',
    'GetFirstView',
    'GetSheetNames',
    'GetViewCount',
    'InsertTableAnnotation2',
    'NewSheet',
    'SetupSheet5',
})


class DualDocument:
    """One drawing pointer with both typed faces.

    Attribute lookup uses the generated class (or the instance dict). It does
    not probe the other face with ``getattr``, which is what hung ``GetTitle``.
    """

    def __init__(self, raw, drawing, model):
        object.__setattr__(self, '_raw', raw)
        object.__setattr__(self, '_drawing', drawing)
        object.__setattr__(self, '_model', model)

    def _face(self, name):
        if name in _MODEL_FACE:
            return self._model
        drawing_has = declared(self._drawing, name)
        model_has = declared(self._model, name)
        if name in _DRAWING_FACE and drawing_has:
            return self._drawing
        if model_has:
            return self._model
        if drawing_has:
            return self._drawing
        return self._raw

    def __getattr__(self, name):
        return getattr(self._face(name), name)

    def __setattr__(self, name, value):
        if name.startswith('_'):
            object.__setattr__(self, name, value)
            return
        setattr(self._face(name), name, value)


def model_document(raw):
    if raw is None:
        raise RuntimeError('model document is missing')
    # MagicMock fabricates attributes but does not store _oleobj_ in __dict__.
    if '_oleobj_' not in getattr(raw, '__dict__', {}):
        return raw
    from solidworks_generator import _as_interface, ensure_solidworks_typelib
    module = ensure_solidworks_typelib()
    model = _as_interface(module, raw, 'IModelDoc2')
    kind = read_document_kind(model)
    if kind is None:
        kind = read_document_kind(raw)
    if kind != 3:
        return model
    drawing = _as_interface(module, raw, 'IDrawingDoc')
    return DualDocument(raw, drawing, model)
