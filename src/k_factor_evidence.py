"""Separate native K persistence from flat-length dimensional assumptions."""
import math
from sheet_metal_pipeline import diagnose_k_change


def audit_variants(payload, *, geometry_basis=None, thickness_mm=2.5, radius_mm=1, angle_degrees=90):
    variants = payload.get('variants', [])
    if len(variants) != 2:
        raise ValueError('two K variants required')
    matches = []
    lengths = []
    for row in variants:
        target, read = row.get('k_target'), row.get('k_read')
        valid = all(type(v) in (int, float) and math.isfinite(v) for v in (target, read))
        matches.append(valid and 0 <= target <= 1 and math.isclose(target, read, abs_tol=1e-8))
        extents = row.get('dxf_extents', {})
        lengths.append(extents.get('max_extent_mm') if extents.get('ok') else None)
    result = {'status': 'review_required', 'sw_live_verified': False,
              'native_k_persistence': 'matched_in_supplied_evidence' if all(matches) else 'mismatch_or_missing',
              'geometry_basis': geometry_basis or 'pending_confirmation',
              'flat_comparison': None,
              'required_next_evidence': ['folded_body_dimensions_for_each_K',
                    'unsuppressed_flat_body_dimensions_for_each_K',
                    'native_bend_allowance_readback_after_reopen',
                    'source_parameter_and_code_hashes'],
              'note': 'Equal DXF bounding boxes alone do not establish that SolidWorks ignored K.'}
    if not all(matches):
        return result
    if geometry_basis is None:
        result['status'] = 'pending_dimension_basis'
        return result
    comparison = diagnose_k_change(thickness_mm=thickness_mm, radius_mm=radius_mm,
        angle_degrees=angle_degrees, old_k=variants[0]['k_target'], new_k=variants[1]['k_target'],
        geometry_basis=geometry_basis, old_flat_mm=lengths[0], new_flat_mm=lengths[1])
    result['flat_comparison'] = comparison
    # Formula consistency is not acceptance of native geometry or exported parts.
    result['status'] = 'consistent_fixed_blank_pending_folded_measurements' if (
        geometry_basis == 'fixed_blank' and comparison['status'] == 'consistent_with_formula') else 'review_required'
    return result
