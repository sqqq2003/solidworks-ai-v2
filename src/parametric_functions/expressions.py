"""Bounded arithmetic expressions with physical dimensions; never eval/exec."""
import ast
from dataclasses import dataclass
from fractions import Fraction
import math
import re

NAME = re.compile(r'[A-Za-z][A-Za-z0-9_]{0,63}\Z')
MAX_NODES = 128
MAX_VALUE = 1e12
# Canonical lengths are mm; canonical angles are radians.
UNITS = {'mm': (1., (1, 0)), 'm': (1000., (1, 0)),
         'mm2': (1., (2, 0)), 'mm3': (1., (3, 0)),
         'deg': (math.pi/180, (0, 1)), 'rad': (1., (0, 1)),
         'count': (1., (0, 0)), 'ratio': (1., (0, 0))}
FUNCTIONS = frozenset({'min', 'max', 'abs', 'sqrt', 'ceil', 'floor', 'round', 'sin', 'cos', 'tan'})
CONSTANTS = {'pi': math.pi}


@dataclass(frozen=True)
class Quantity:
    value: float
    dimension: tuple = (0, 0)

    def __post_init__(self):
        finite(self.value)


def finite(value):
    if type(value) not in (int, float) or not math.isfinite(value) or abs(value) > MAX_VALUE:
        raise ValueError('finite bounded numeric value required (absolute value <= 1e12)')
    return float(value)


def quantity(value, unit):
    if unit not in UNITS:raise ValueError('unsupported explicit unit: ' + str(unit))
    factor, dimension = UNITS[unit]
    return Quantity(finite(value) * factor, dimension)


def converted(value, unit):
    if unit not in UNITS or value.dimension != UNITS[unit][1]:
        raise ValueError('expression units do not match declared output unit: ' + str(unit))
    number = finite(value.value / UNITS[unit][0])
    if unit == 'count':
        if not number.is_integer():raise ValueError('count must be an integer; use ceil/floor/round explicitly')
        return int(number)
    return number


def compile_expression(text):
    if not isinstance(text, str) or not text.strip() or len(text) > 1024:
        raise ValueError('expression must contain 1..1024 characters')
    try:tree = ast.parse(text, mode='eval')
    except (SyntaxError, RecursionError) as error:raise ValueError('invalid expression syntax') from error
    nodes = list(ast.walk(tree))
    if len(nodes) > MAX_NODES:raise ValueError('expression operation limit exceeded')
    allowed = (ast.Expression, ast.Constant, ast.Name, ast.Load, ast.BinOp, ast.UnaryOp,
               ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.UAdd, ast.USub, ast.Call,
               ast.Compare, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.Eq, ast.NotEq)
    for node in nodes:
        if not isinstance(node, allowed):raise ValueError('operation outside arithmetic whitelist')
        if isinstance(node, ast.Constant):finite(node.value)
        if isinstance(node, ast.Name) and not NAME.fullmatch(node.id):raise ValueError('invalid parameter name')
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in FUNCTIONS or node.keywords:
                raise ValueError('function outside numeric whitelist')
            if not 1 <= len(node.args) <= 16:raise ValueError('function argument limit exceeded')
        if isinstance(node, ast.Compare) and len(node.ops) != 1:
            raise ValueError('use separate constraints instead of chained comparisons')
    called = {id(n.func) for n in nodes if isinstance(n, ast.Call)}
    deps = {n.id for n in nodes if isinstance(n, ast.Name) and id(n) not in called and n.id not in CONSTANTS}
    return tree.body, deps


def evaluate(node, values):
    if isinstance(node, ast.Constant):return Quantity(finite(node.value))
    if isinstance(node, ast.Name):
        if node.id in values:return values[node.id]
        if node.id in CONSTANTS:return Quantity(CONSTANTS[node.id])
        raise ValueError('unknown parameter: ' + node.id)
    if isinstance(node, ast.UnaryOp):
        q = evaluate(node.operand, values)
        if not isinstance(q, Quantity):raise ValueError('comparison cannot be an arithmetic operand')
        return Quantity(q.value * (-1 if isinstance(node.op, ast.USub) else 1), q.dimension)
    if isinstance(node, (ast.BinOp, ast.Compare)):
        a = evaluate(node.left, values)
        b = evaluate(node.right if isinstance(node, ast.BinOp) else node.comparators[0], values)
        if not isinstance(a, Quantity) or not isinstance(b, Quantity):raise ValueError('comparison cannot be an arithmetic operand')
        op = node.op if isinstance(node, ast.BinOp) else node.ops[0]
        if isinstance(op, (ast.Add, ast.Sub, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.Eq, ast.NotEq)):
            if a.dimension != b.dimension:raise ValueError('incompatible units in addition/comparison')
            if isinstance(op, ast.Add):return Quantity(a.value + b.value, a.dimension)
            if isinstance(op, ast.Sub):return Quantity(a.value - b.value, a.dimension)
            if isinstance(op, ast.Lt):return a.value < b.value
            if isinstance(op, ast.LtE):return a.value <= b.value
            if isinstance(op, ast.Gt):return a.value > b.value
            if isinstance(op, ast.GtE):return a.value >= b.value
            if isinstance(op, ast.Eq):return a.value == b.value
            return a.value != b.value
        if isinstance(op, ast.Mult):return Quantity(a.value*b.value, tuple(x+y for x,y in zip(a.dimension,b.dimension)))
        if isinstance(op, ast.Div):
            if b.value == 0:raise ValueError('division by zero')
            return Quantity(a.value/b.value, tuple(x-y for x,y in zip(a.dimension,b.dimension)))
        if b.dimension != (0, 0) or not b.value.is_integer() or abs(b.value) > 8:
            raise ValueError('power must be a dimensionless integer in [-8,8]')
        if a.value == 0 and b.value < 0:raise ValueError('division by zero')
        return Quantity(a.value ** int(b.value), tuple(x*int(b.value) for x in a.dimension))
    if isinstance(node, ast.Call):
        args = [evaluate(x, values) for x in node.args]
        if any(not isinstance(q, Quantity) for q in args):raise ValueError('numeric function arguments required')
        fn = node.func.id
        if fn in {'min','max'}:
            if any(q.dimension != args[0].dimension for q in args):raise ValueError('min/max units differ')
            return Quantity((min if fn == 'min' else max)(q.value for q in args), args[0].dimension)
        if len(args) != 1:raise ValueError(fn + ' takes exactly one argument')
        q = args[0]
        if fn == 'sqrt':return Quantity(math.sqrt(q.value), tuple(Fraction(x,2) for x in q.dimension))
        if fn in {'sin','cos','tan'}:
            if q.dimension != (0,1):raise ValueError('trigonometric function requires an angle (deg/rad)')
            return Quantity(getattr(math,fn)(q.value))
        number = {'abs': abs, 'ceil': math.ceil, 'floor': math.floor, 'round': round}[fn](q.value)
        return Quantity(float(number), q.dimension)
    raise ValueError('invalid numeric expression')
