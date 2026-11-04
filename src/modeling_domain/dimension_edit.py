"""Single reviewed length edit on an owned copy with a sealed checkpoint.

The caller owns receipt completion, save/reopen verification and rollback.
Enum values follow SW API swDimensionParamType_e, swDimensionDrivenState_e
and swSetValueInConfiguration_e; angles are never converted as millimetres.
"""
import math
from pathlib import Path

from cad_checkpoint import digest_file, inspect_checkpoint
from ql5050px.native_machine import read_member


def _number(value):
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise ValueError('positive finite millimetres required')
    return float(value)


def edit_reviewed_length(port, checkpoint, *, configuration, dimension_name,
                         before_mm, after_mm, allowed_range, source):
    before_mm, after_mm = _number(before_mm), _number(after_mm)
    if (not isinstance(configuration, str) or not configuration.strip()
            or not isinstance(dimension_name, str) or '@' not in dimension_name
            or not isinstance(source, str) or not source.strip()):
        raise ValueError('explicit configuration, native dimension and mapping source required')
    if not isinstance(allowed_range, (list, tuple)) or len(allowed_range) != 2:
        raise ValueError('reviewed test range required')
    lo, hi = map(_number, allowed_range)
    if not lo <= before_mm <= hi or not lo <= after_mm <= hi:
        raise ValueError('length outside reviewed range')
    port.guard()
    manifest = inspect_checkpoint(checkpoint)
    target = Path(port.path).resolve(strict=True)
    row = next((r for r in manifest['files'] if Path(r['target']).resolve() == target), None)
    if row is None or digest_file(target) != row['source_sha256']:
        raise ValueError('owned model is not at the sealed file baseline')
    for name, expected in manifest['original_sha256'].items():
        if digest_file(name) != expected:raise ValueError('original changed before dimension edit')
    model = port.host.model
    active = str(read_member(read_member(model, 'ConfigurationManager'), 'ActiveConfiguration').Name)
    if active != configuration:raise ValueError('active configuration differs from reviewed mapping')
    dimension = model.Parameter(dimension_name)
    if dimension is None:raise ValueError('reviewed native dimension not found')
    if hasattr(dimension, '_oleobj_'):
        import solidworks_generator as sw
        dimension = sw._as_interface(sw.ensure_solidworks_typelib(), dimension, 'IDimension')
    if (int(dimension.GetType()) != 0 or bool(dimension.ReadOnly)
            or int(dimension.DrivenState) != 2):
        raise ValueError('editable driving linear dimension required')
    current = float(dimension.SystemValue) * 1000
    if not math.isclose(current, before_mm, rel_tol=0, abs_tol=1e-6):
        raise ValueError('stale dimension mapping')
    # One write only. Any failure is returned to the caller for checkpoint rollback.
    port.guard()
    status = int(dimension.SetSystemValue3(after_mm / 1000, 3, [configuration]))
    if status != 0:raise RuntimeError('native dimension edit rejected: ' + str(status))
    if read_member(model, 'EditRebuild3') is not True:raise RuntimeError('dimension rebuild failed')
    actual = float(dimension.SystemValue) * 1000
    if not math.isclose(actual, after_mm, rel_tol=0, abs_tol=1e-6):
        raise RuntimeError('changed dimension readback mismatch')
    return {'dimension': dimension_name, 'configuration': configuration, 'unit': 'mm',
            'before_mm': current, 'after_mm': actual, 'source': source,
            'status': 'rebuilt_pending_save_reopen', 'manufacturing_approved': False}
