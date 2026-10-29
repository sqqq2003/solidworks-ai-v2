"""Shared finite quantities and four-state reporting; reuse platform digests."""
import math
from design_review.impact import review_digest


def number(value, *, minimum=None):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError('finite numeric value required')
    if minimum is not None and value < minimum:
        raise ValueError('value below allowed minimum')
    return float(value)


def quantity(row, unit, *, minimum=None):
    if not isinstance(row, dict) or row.get('unit') != unit or not row.get('source'):
        raise ValueError('explicit unit and source required: '+unit)
    return number(row['value'], minimum=minimum)


def index(rows):
    out = {}
    for row in rows:
        key = row.get('id')
        if not isinstance(key, str) or not key or key in out:
            raise ValueError('nonempty unique id required')
        out[key] = row
    return out


def result(data, *, issues=(), failed=()):
    return dict(data, status='failed' if failed else 'review_required' if issues else 'passed',
                issues=list(issues), failures=list(failed), engineering_approved=False,
                native_status='pending_windows_validation')
