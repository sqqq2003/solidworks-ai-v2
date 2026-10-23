"""Explicit solve and geometric readback on an owned, isolated Windows work copy.

Does not save, attach, close, kill, or create a SolidWorks session. Caller must
supply a model on its owning task STA. Gork runs this only on Windows.
"""
from __future__ import annotations
import ntpath
import os
import sys
from .equation_health import analyze_equations


def _inside(path, root):
    if os.name == 'nt':
        path, root = os.path.realpath(path), os.path.realpath(root)
    path, root = ntpath.normcase(ntpath.normpath(path)), ntpath.normcase(ntpath.normpath(root))
    try:
        return ntpath.isabs(path) and ntpath.commonpath([path, root]) == root
    except ValueError:
        return False


def assert_isolated(model, root):
    """Reject source/shared references before any write or rebuild."""
    if not ntpath.isabs(root):
        raise ValueError('isolation root must be absolute')
    if not _inside(str(model.GetPathName()), root):
        raise ValueError('model is outside isolated work directory')
    deps = model.GetDependencies2(True, True, False)
    if deps is None:
        raise RuntimeError('dependency inventory unavailable; isolation unverified')
    deps = list(deps)
    if not deps or len(deps) % 2:
        raise RuntimeError('invalid dependency name/path pairs')
    for path in deps[1::2]:
        if not _inside(str(path), root):
            raise ValueError('shared or unresolved reference; Pack and Go required: ' + str(path))


def snapshot(model):
    manager = model.GetEquationMgr()
    rows, dimensions = [], {}
    for index in range(int(manager.GetCount())):
        text = str(manager.Equation(index))
        rows.append({'index': index, 'equation': text, 'value': float(manager.Value(index))})
        from .equation_health import ROW
        match = ROW.match(text)
        if match and '@' in match[1]:
            dimension = model.Parameter(match[1])
            if dimension is not None:
                dimensions[match[1]] = float(dimension.SystemValue) * 1000
    return {'equations': rows, 'dimensions_mm': dimensions,
            'analysis': analyze_equations(rows, dimensions)}


def solve_owned_work_copy(model, isolated_root, *, updates=None):
    """Run on task STA; fail closed before saving if geometry has not followed.

    Caller must checkpoint the complete isolated document set and restore or
    discard unsaved documents on any exception. This function never saves.
    """
    if sys.platform != 'win32':
        raise RuntimeError('sw_live=not_applicable_on_linux')
    from .win32com_backend import _import_sw_session, _assign_existing_equations
    session = _import_sw_session()
    lease = session.require_model_write()
    assert_isolated(model, isolated_root)
    before = snapshot(model)
    session.require_model_write(lease)
    manager = model.GetEquationMgr()
    manager.AutomaticSolveOrder = True
    if not bool(manager.AutomaticSolveOrder):
        raise RuntimeError('AutomaticSolveOrder did not enable')
    if updates:
        _assign_existing_equations(model, updates)
    session.require_model_write(lease)
    evaluation = manager.EvaluateAll()
    session.require_model_write(lease)
    rebuilt = model.ForceRebuild3(False)
    after = snapshot(model)
    report = {'before': before, 'after': after, 'evaluate_all_result': evaluation,
              'force_rebuild_result': rebuilt, 'saved': False, 'mechanical_checks': 'unverified'}
    if evaluation != -1 or not rebuilt or after['analysis']['status'] != 'equations_and_linked_dimensions_verified':
        report['status'] = 'geometry_verification_failed'
    else:
        report['status'] = 'linked_dimensions_verified_unsaved'
    return report
