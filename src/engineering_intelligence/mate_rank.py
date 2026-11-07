"""First-order mate constraint rank from declared assembly-frame geometry.

Each mate names the entities it binds at the current pose (point, axis or
plane in assembly millimetres). Constraint rows are gradients with respect
to small relative twists, so mobility, redundant equations and the motions
each component keeps come from linear algebra rather than a per-type DOF
table. This is instantaneous analysis of caller-declared geometry; singular
poses can show extra first-order freedom, and nothing here is a SolidWorks
mate solve.
"""
import math
from .common import number, quantity

GEOMETRIC_TYPES = ('fixed', 'coincident', 'concentric', 'distance', 'parallel', 'perpendicular', 'angle')
MAX_MOVING_COMPONENTS = 60
MAX_EQUATIONS = 600
GROUND = '__ground__'
_TOL = 1e-8
_AXES = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))


def _dot(a, b): return sum(x*y for x, y in zip(a, b))
def _norm(a): return math.sqrt(_dot(a, a))
def _sub(a, b): return tuple(x-y for x, y in zip(a, b))
def _add(a, b): return tuple(x+y for x, y in zip(a, b))
def _mul(a, k): return tuple(x*k for x in a)
def _cross(a, b): return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])


def _extend(basis, row):
    """Append the normalised Gram-Schmidt residual of row if it is independent."""
    residual = list(row)
    for _ in range(2):
        for vector in basis:
            d = _dot(residual, vector)
            if d: residual = [x-d*y for x, y in zip(residual, vector)]
    size = _norm(residual)
    if size <= _TOL*max(1.0, _norm(row)): return False
    basis.append([x/size for x in residual])
    return True


def _span(rows):
    basis = []
    for row in rows: _extend(basis, row)
    return basis


def _complement(basis, size):
    full = [list(v) for v in basis]; extra = []
    for j in range(size):
        if len(full) == size: break
        if _extend(full, [1.0 if i == j else 0.0 for i in range(size)]): extra.append(full[-1])
    return extra


def _dependencies(rows):
    """Rank plus one left-null combination per row that depends on earlier rows."""
    basis, deps = [], []
    for i, row in enumerate(rows):
        residual, combo = list(row), {i: 1.0}
        for _ in range(2):
            for vector, weights in basis:
                d = _dot(residual, vector)
                if not d: continue
                residual = [x-d*y for x, y in zip(residual, vector)]
                for k, w in weights.items(): combo[k] = combo.get(k, 0.0)-d*w
        size = _norm(residual)
        if size <= _TOL*max(1.0, _norm(row)): deps.append(combo)
        else: basis.append(([x/size for x in residual], {k: w/size for k, w in combo.items()}))
    return len(basis), deps


def _solve(matrix, rhs):
    n = len(rhs); a = [list(matrix[i])+[rhs[i]] for i in range(n)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(a[r][col]))
        a[col], a[pivot] = a[pivot], a[col]
        for r in range(n):
            if r != col and a[r][col]:
                f = a[r][col]/a[col][col]
                a[r] = [x-f*y for x, y in zip(a[r], a[col])]
    return [a[i][n]/a[i][i] for i in range(n)]


def _vector(value, name, *, unit=False):
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError(name+' requires three numbers')
    v = tuple(number(x) for x in value)
    if unit:
        size = _norm(v)
        if size < 1e-12: raise ValueError(name+' must be a nonzero direction')
        v = _mul(v, 1.0/size)
    return v


def _entity(row, name):
    if not isinstance(row, dict) or row.get('kind') not in ('point', 'axis', 'plane'):
        raise ValueError(name+' kind must be point, axis or plane')
    point = _vector(row.get('point_mm'), name+'.point_mm')
    if row['kind'] == 'point': return {'kind': 'point', 'p': point}
    key = 'direction' if row['kind'] == 'axis' else 'normal'
    return {'kind': row['kind'], 'p': point, 'd': _vector(row.get(key), name+'.'+key, unit=True)}


def _perpendiculars(d):
    seed = min(_AXES, key=lambda e: abs(_dot(e, d)))
    u = _cross(d, seed); u = _mul(u, 1.0/_norm(u))
    return u, _cross(d, u)


class _Rows:
    """Rows for the moving entity side; points are scaled about the centroid."""

    def __init__(self, centre, length):
        self.centre, self.length, self.rows, self.linear, self.angular = centre, length, [], [], []

    def _point_row(self, point, e):
        arm = _mul(_sub(point, self.centre), 1.0/self.length)
        return list(e)+list(_cross(arm, e))

    def on_plane(self, point, plane, offset=0.0):
        signed = _dot(plane['d'], _sub(point, plane['p']))
        self.linear.append(abs(signed)-offset if offset else signed)
        self.rows.append(self._point_row(point, plane['d']))

    def on_line(self, point, axis):
        for u in _perpendiculars(axis['d']):
            self.linear.append(_dot(u, _sub(point, axis['p'])))
            self.rows.append(self._point_row(point, u))

    def same_point(self, point, other):
        for e in _AXES:
            self.linear.append(_dot(e, _sub(point, other)))
            self.rows.append(self._point_row(point, e))

    def separation(self, vector, point, distance, what):
        size = _norm(vector)
        if size < 1e-9: raise ValueError(what+' distance mate needs separated entities')
        self.linear.append(size-distance)
        self.rows.append(self._point_row(point, _mul(vector, 1.0/size)))

    def parallel(self, moving, fixed):
        for u in _perpendiculars(fixed):
            self.angular.append(math.asin(min(1.0, abs(_dot(u, moving)))))
            self.rows.append([0.0, 0.0, 0.0]+list(_cross(moving, u)))

    def perpendicular(self, moving, fixed):
        self.angular.append(math.asin(min(1.0, abs(_dot(moving, fixed)))))
        self.rows.append([0.0, 0.0, 0.0]+list(_cross(moving, fixed)))

    def angle(self, moving, fixed, target):
        axis = _cross(moving, fixed)
        if _norm(axis) < 1e-6:
            raise ValueError('angle mate at 0 or 180 deg is degenerate; declare it as parallel')
        actual = math.acos(max(-1.0, min(1.0, _dot(moving, fixed))))
        self.angular.append(min(abs(actual-target), abs(actual-(math.pi-target))))
        self.rows.append([0.0, 0.0, 0.0]+list(axis))


def _mate_rows(mate, rows):
    """Fill rows; return the sign that makes them gradients in b's twist relative to a."""
    kind = mate['type']
    if kind == 'fixed':
        for i in range(6): rows.rows.append([1.0 if i == j else 0.0 for j in range(6)])
        return 1
    geometry = mate['geometry']
    a, b = _entity(geometry.get('a'), mate['id']+'.a'), _entity(geometry.get('b'), mate['id']+'.b')
    order = ('point', 'axis', 'plane')
    sign = 1
    if order.index(a['kind']) < order.index(b['kind']):
        a, b, sign = b, a, -1
    pair = (a['kind'], b['kind'])  # a is the reference side, b moves
    distance = quantity(geometry.get('distance'), 'mm', minimum=0) if kind == 'distance' else None
    if kind == 'angle':
        target = math.radians(quantity(geometry.get('angle'), 'deg'))
        if pair not in (('plane', 'plane'), ('axis', 'axis')): raise ValueError(mate['id']+': angle needs two planes or two axes')
        rows.angle(b['d'], a['d'], target); return sign
    lookup = {
        ('coincident', ('plane', 'plane')): lambda: (rows.parallel(b['d'], a['d']), rows.on_plane(b['p'], a)),
        ('coincident', ('plane', 'point')): lambda: rows.on_plane(b['p'], a),
        ('coincident', ('point', 'point')): lambda: rows.same_point(b['p'], a['p']),
        ('coincident', ('axis', 'point')): lambda: rows.on_line(b['p'], a),
        ('coincident', ('plane', 'axis')): lambda: (rows.on_plane(b['p'], a), rows.perpendicular(b['d'], a['d'])),
        ('coincident', ('axis', 'axis')): lambda: (rows.parallel(b['d'], a['d']), rows.on_line(b['p'], a)),
        ('concentric', ('axis', 'axis')): lambda: (rows.parallel(b['d'], a['d']), rows.on_line(b['p'], a)),
        ('concentric', ('axis', 'point')): lambda: rows.on_line(b['p'], a),
        ('distance', ('plane', 'plane')): lambda: (rows.parallel(b['d'], a['d']), rows.on_plane(b['p'], a, distance)),
        ('distance', ('plane', 'point')): lambda: rows.on_plane(b['p'], a, distance),
        ('distance', ('plane', 'axis')): lambda: (rows.on_plane(b['p'], a, distance), rows.perpendicular(b['d'], a['d'])),
        ('distance', ('point', 'point')): lambda: rows.separation(_sub(b['p'], a['p']), b['p'], distance, mate['id']),
        ('distance', ('axis', 'point')): lambda: _line_distance(rows, b['p'], a, distance, mate['id']),
        ('distance', ('axis', 'axis')): lambda: (rows.parallel(b['d'], a['d']), _line_distance(rows, b['p'], a, distance, mate['id'])),
        ('parallel', ('plane', 'plane')): lambda: rows.parallel(b['d'], a['d']),
        ('parallel', ('axis', 'axis')): lambda: rows.parallel(b['d'], a['d']),
        ('parallel', ('plane', 'axis')): lambda: rows.perpendicular(b['d'], a['d']),
        ('perpendicular', ('plane', 'plane')): lambda: rows.perpendicular(b['d'], a['d']),
        ('perpendicular', ('axis', 'axis')): lambda: rows.perpendicular(b['d'], a['d']),
        ('perpendicular', ('plane', 'axis')): lambda: rows.parallel(b['d'], a['d']),
    }
    builder = lookup.get((kind, pair))
    if builder is None: raise ValueError(mate['id']+': unsupported geometric mate '+kind+' '+'-'.join(pair))
    builder()
    return sign


def _line_distance(rows, point, axis, distance, what):
    offset = _sub(point, axis['p'])
    radial = _sub(offset, _mul(axis['d'], _dot(offset, axis['d'])))
    rows.separation(radial, point, distance, what)


def _canonical(direction):
    for x in direction:
        if abs(x) > 1e-9: return direction if x > 0 else _mul(direction, -1.0)
    return direction


def _clean(values, places=6):
    return [round(x, places)+0.0 for x in values]


def _subspace_axes(vectors):
    basis = _span(vectors)
    out = []
    for e in _AXES:
        projected = [0.0, 0.0, 0.0]
        for v in basis: projected = [p+_dot(e, v)*x for p, x in zip(projected, v)]
        _extend(out, projected)
    return [tuple(v) for v in out]


def _motions(span, centre, length):
    """Describe a component's twist span as translations plus rotation axes."""
    k = len(span)
    if not k: return [], []
    omega_rows = [[span[j][3+i] for j in range(k)] for i in range(3)]
    rotation_basis = _span(omega_rows)
    translation_mix = _complement(rotation_basis, k)
    translations = _subspace_axes([[sum(a[j]*span[j][i] for j in range(k)) for i in range(3)] for a in translation_mix])
    twists = [[sum(b[j]*span[j][i] for j in range(k)) for i in range(6)] for b in rotation_basis]
    rotations = []
    for e in _subspace_axes([t[3:] for t in twists]):
        gram = [[_dot(s[3:], t[3:]) for t in twists] for s in twists]
        weights = _solve(gram, [_dot(s[3:], e) for s in twists])
        v = tuple(sum(w*t[i] for w, t in zip(weights, twists))*length for i in range(3))
        for direction in translations: v = _sub(v, _mul(direction, _dot(v, direction)))
        axis = _canonical(e)
        if _dot(axis, e) < 0: v = _mul(v, -1.0)
        point = _add(centre, _cross(axis, v))
        point = _sub(point, _mul(axis, _dot(point, axis)))
        pitch = _dot(axis, v)
        if abs(pitch) < 1e-6*length: pitch = 0.0
        rotations.append({'direction': _clean(axis), 'axis_point_mm': _clean(point, 4), 'pitch_mm_per_rad': round(pitch, 6)+0.0})
    return [_clean(_canonical(t)) for t in translations], rotations


def _expected_twist(motion, centre, length, name):
    if not isinstance(motion, dict) or motion.get('type') not in ('rotation', 'translation'):
        raise ValueError(name+' expected motion type must be rotation or translation')
    direction = _vector(motion.get('direction'), name+' expected direction', unit=True)
    if motion['type'] == 'translation': return list(direction)+[0.0, 0.0, 0.0]
    point = _vector(motion.get('axis_point_mm'), name+' expected axis_point_mm')
    v = _mul(_cross(direction, _sub(centre, point)), 1.0/length)
    return list(v)+list(direction)


def analyse_constraints(components, mates, *, linear_tolerance_mm=0.01, angular_tolerance_deg=0.01):
    """Return rank report for active, reference-valid mates of supported types."""
    linear_tol = number(linear_tolerance_mm, minimum=1e-9)
    angular_tol = math.radians(number(angular_tolerance_deg, minimum=1e-9))
    fixed = {c['id'] for c in components if c.get('fixed')}
    moving = [c['id'] for c in components if c['id'] not in fixed]
    if len(moving) > MAX_MOVING_COMPONENTS:
        raise ValueError('constraint rank supports at most %d moving components; split the subassembly' % MAX_MOVING_COMPONENTS)
    column = {name: 6*i for i, name in enumerate(moving)}
    points = []
    for mate in mates:
        if mate['type'] not in GEOMETRIC_TYPES: raise ValueError(mate['id']+': mate type has no geometric rows')
        if mate['type'] == 'fixed': continue
        geometry = mate.get('geometry')
        if not isinstance(geometry, dict) or geometry.get('unit') != 'mm' or not geometry.get('source'):
            raise ValueError(mate['id']+': geometry needs unit mm and source')
        for side in ('a', 'b'):
            if isinstance(geometry.get(side), dict): points.append(_vector(geometry[side].get('point_mm'), mate['id']+'.'+side+'.point_mm'))
    centre = tuple(sum(p[i] for p in points)/len(points) for i in range(3)) if points else (0.0, 0.0, 0.0)
    length = max([1.0]+[_norm(_sub(p, centre)) for p in points])
    body = lambda name: GROUND if name in fixed else name
    pairs, reports, failures, issues = {}, [], [], []
    for mate in mates:
        rows = _Rows(centre, length)
        sign = _mate_rows(mate, rows)
        linear = max([abs(x) for x in rows.linear], default=0.0)
        angular = max([abs(x) for x in rows.angular], default=0.0)
        if linear > linear_tol or angular > angular_tol: failures.append('mate_geometry_unsatisfied:'+mate['id'])
        reports.append({'id': mate['id'], 'equations': len(rows.rows),
                        'residual': {'linear_mm': round(linear, 6), 'angular_deg': round(math.degrees(angular), 6)}})
        key = (body(mate['a']), body(mate['b']))
        if key[0] == key[1]:
            issues.append('mate_between_fixed_components:'+mate['id'])
            reports[-1]['between_fixed_components'] = True
            continue
        if key[0] > key[1]: key, sign = (key[1], key[0]), -sign
        pairs.setdefault(key, []).append((mate, [[sign*x for x in row] for row in rows.rows]))
    total = sum(len(r) for group in pairs.values() for _, r in group)
    if total > MAX_EQUATIONS:
        raise ValueError('constraint rank supports at most %d equations; split the subassembly' % MAX_EQUATIONS)
    by_id = {r['id']: r for r in reports}
    reduced, owners, pair_redundancy = [], [], 0
    for (left, right), group in pairs.items():
        flat = [row for _, rows in group for row in rows]
        pair_rank = len(_span(flat))
        pair_redundancy += len(flat)-pair_rank
        removable = []
        for mate, rows in group:
            others = [row for other, rs in group if other is not mate for row in rs]
            by_id[mate['id']]['removable_within_pair'] = len(_span(others)) == pair_rank
            if by_id[mate['id']]['removable_within_pair']: removable.append(mate['id'])
        if removable:
            issues.append('redundant_mates:%s/%s:%s' % (left, right, ','.join(removable)))
        basis = []
        for mate, rows in group:
            for row in rows:
                if not _extend(basis, row): continue
                full = [0.0]*(6*len(moving))
                for name, factor in ((right, 1.0), (left, -1.0)):
                    if name == GROUND: continue
                    for i in range(6): full[column[name]+i] += factor*row[i]
                reduced.append(full); owners.append(mate['id'])
    rank, dependencies = _dependencies(reduced)
    involved = set()
    for combo in dependencies:
        scale = max(abs(w) for w in combo.values())
        involved.update(owners[k] for k, w in combo.items() if abs(w) > 1e-7*scale)
    loop = [r['id'] for r in reports if r['id'] in involved]
    loop_redundancy = len(reduced)-rank
    if loop_redundancy:
        issues.append('overconstrained_loop:%d:%s' % (loop_redundancy, ','.join(loop)))
    null = _complement(_span(reduced), 6*len(moving))
    expected = {c['id']: c for c in components}
    states = []
    for name in moving:
        span = _span([z[column[name]:column[name]+6] for z in null])
        translations, rotations = _motions(span, centre, length)
        row = {'id': name, 'dof': len(span), 'translations': translations, 'rotations': rotations}
        spec = expected[name]
        motions = spec.get('expected_motions')
        if motions is not None:
            if not isinstance(motions, list): raise ValueError(name+' expected_motions must be a list')
            twists = [_expected_twist(m, centre, length, name) for m in motions]
            blocked = []
            for index, twist in enumerate(twists):
                residual = list(twist)
                for _ in range(2):
                    for vector in span:
                        d = _dot(residual, vector); residual = [x-d*y for x, y in zip(residual, vector)]
                if _norm(residual) > 1e-6*_norm(twist): blocked.append(index)
            row['expected_motions_blocked'] = blocked
            if blocked: failures.append('expected_motion_blocked:'+name)
            if len(span) > len(_span(twists)): failures.append('unexpected_free_motion:'+name)
        if 'expected_dof' in spec:
            if isinstance(spec['expected_dof'], bool) or not isinstance(spec['expected_dof'], int):
                raise ValueError(name+' expected_dof must be an integer')
            if spec['expected_dof'] != len(span): failures.append('constraint_dof_mismatch:'+name)
        elif motions is None and span:
            issues.append('free_motion_unreviewed:'+name)
        states.append(row)
    return {'mode': 'first_order_constraint_rank', 'equations': total, 'rank': rank,
            'mobility': 6*len(moving)-rank, 'pair_redundant_equations': pair_redundancy,
            'loop_redundant_equations': loop_redundancy, 'loop_mates': loop,
            'components': states, 'mates': reports,
            'tolerances': {'linear_mm': linear_tol, 'angular_deg': math.degrees(angular_tol)},
            'issues': issues, 'failures': failures,
            'note': 'Instantaneous rank of declared current-pose geometry; not a SolidWorks mate solve, motion study or collision proof.'}
