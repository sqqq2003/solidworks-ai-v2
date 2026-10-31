"""Audit SW equation dumps without COM or treating globals as geometry proof."""
from __future__ import annotations
import ast
import math
import operator
import re

ROW = re.compile(r'^\s*"([^"]+)"\s*=\s*(.+?)\s*$')
REF = re.compile(r'"([^"]+)"')
MM = re.compile(r'(?<=\d)\s*mm\b', re.I)
OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}


def numeric(node):
    if isinstance(node, ast.Expression):
        return numeric(node.body)
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        return float(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        return (-1 if isinstance(node.op, ast.USub) else 1) * numeric(node.operand)
    if isinstance(node, ast.BinOp) and type(node.op) in OPS:
        return OPS[type(node.op)](numeric(node.left), numeric(node.right))
    raise ValueError("unsupported formula; needs native verification")


def analyze_equations(rows: list[dict], dimensions_mm: dict | None = None) -> dict:
    """Only arithmetic/mm formulas are interpreted. No Python eval is used."""
    equations, positions = {}, {}
    for row in rows:
        match = ROW.match(row['equation'])
        if not match:
            raise ValueError("invalid equation text")
        name, rhs = match.groups()
        if name in equations:
            raise ValueError("duplicate equation target")
        equations[name] = (rhs, row)
        positions[name] = row['index']
    expected, pending, active = {}, {}, set()

    def solve(name):
        if name in expected:
            return expected[name]
        if name in active:
            raise ValueError("cyclic equation dependency")
        if name not in equations:
            raise ValueError("unresolved equation reference: " + name)
        active.add(name)
        try:
            rhs = REF.sub(lambda m: '(' + repr(solve(m[1])) + ')', equations[name][0])
            value = numeric(ast.parse(MM.sub('', rhs), mode='eval'))
            if not math.isfinite(value):
                raise ValueError("nonfinite equation value")
            expected[name] = value
            return value
        finally:
            active.remove(name)

    mismatches, geometry, forward = [], [], []
    for name, (rhs, row) in equations.items():
        for dep in REF.findall(rhs):
            if dep in positions and positions[dep] > positions[name]:
                forward.append({'target': name, 'depends_on': dep})
        try:
            want = solve(name)
        except (ValueError, SyntaxError, ZeroDivisionError, OverflowError, RecursionError) as exc:
            pending[name] = str(exc)
            continue
        actual = row.get('value')
        if type(actual) not in (int, float) or not math.isfinite(actual) or not math.isclose(actual, want, abs_tol=1e-5, rel_tol=1e-8):
            mismatches.append({'target': name, 'expected_mm': want, 'equation_value': actual})
        if '@' in name:
            actual_dimension = (dimensions_mm or {}).get(name)
            valid = type(actual_dimension) in (float, int) and math.isfinite(actual_dimension) and math.isclose(actual_dimension, want, abs_tol=1e-5, rel_tol=1e-8)
            geometry.append({'target': name, 'expected_mm': want, 'dimension_mm': actual_dimension,
                             'status': 'verified' if valid else ('unverified' if actual_dimension is None else 'mismatch')})
    good = not pending and not mismatches and bool(geometry) and all(r['status'] == 'verified' for r in geometry)
    return {'status': 'equations_and_linked_dimensions_verified' if good else 'review_required',
            'expected_mm': expected, 'equation_mismatches': mismatches, 'pending_formulas': pending,
            'forward_references': forward, 'linked_dimensions': geometry,
            'mechanical_checks': 'unverified', 'cad_release_approved': False}
