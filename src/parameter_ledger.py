"""Portable parameter provenance. Recognition is a proposal, never confirmation."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
import hashlib
import json
import math

UNITS = frozenset({'mm', 'deg', 'count', 'ratio', 'text'})
STATES = frozenset({'proposed', 'confirmed', 'rejected'})
ORIGINS = frozenset({'drawing_text', 'measurement', 'user', 'derived', 'template'})


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False, separators=(',', ':')).encode()).hexdigest()


@dataclass(frozen=True)
class Parameter:
    key: str
    value: float | int | str
    unit: str
    origin: str
    source: str
    state: str = 'proposed'
    minimum: float | None = None
    maximum: float | None = None
    depends_on: tuple[str, ...] = ()
    confirmed_by: str | None = None
    confirmed_at: str | None = None
    dependency_digest: str | None = None

    def validate(self):
        if not self.key or self.unit not in UNITS or self.origin not in ORIGINS or self.state not in STATES:
            raise ValueError('invalid parameter identity, unit, origin or state')
        if not self.source.strip():
            raise ValueError(f'{self.key}: parameter source is required')
        if self.unit == 'text':
            if not isinstance(self.value, str) or not self.value.strip():
                raise ValueError(f'{self.key}: nonempty text required')
            if self.minimum is not None or self.maximum is not None:
                raise ValueError('text cannot have numeric bounds')
        else:
            if isinstance(self.value, bool) or not isinstance(self.value, (float, int)) or not math.isfinite(self.value):
                raise ValueError(f'{self.key}: finite numeric value required')
            if self.unit == 'count' and (int(self.value) != self.value or self.value < 1):
                raise ValueError(f'{self.key}: positive integral count required')
            for bound in (self.minimum, self.maximum):
                if bound is not None and (isinstance(bound, bool) or not isinstance(bound, (float, int)) or not math.isfinite(bound)):
                    raise ValueError('finite numeric bounds required')
            if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
                raise ValueError('minimum exceeds maximum')
            if self.minimum is not None and self.value < self.minimum:
                raise ValueError(f'{self.key}: below minimum')
            if self.maximum is not None and self.value > self.maximum:
                raise ValueError(f'{self.key}: above maximum')
        if self.state == 'confirmed':
            if not self.confirmed_by or not self.confirmed_at:
                raise ValueError('confirmation requires actor and timezone-aware timestamp')
            timestamp = datetime.fromisoformat(self.confirmed_at)
            if timestamp.utcoffset() is None:
                raise ValueError('confirmation timestamp requires timezone')


@dataclass
class ParameterLedger:
    source_sha256: str
    parameters: dict[str, Parameter] = field(default_factory=dict)

    def _validate_graph(self):
        if len(self.source_sha256) != 64 or any(c not in '0123456789abcdef' for c in self.source_sha256):
            raise ValueError('source SHA256 required')
        visited, active = set(), set()

        def visit(key):
            if key in active:
                raise ValueError('cyclic parameter dependency')
            if key in visited:
                return
            if key not in self.parameters:
                raise ValueError(f'missing parameter dependency: {key}')
            item = self.parameters[key]
            if item.key != key:
                raise ValueError('parameter key mismatch')
            item.validate()
            active.add(key)
            for parent in item.depends_on:
                visit(parent)
            active.remove(key)
            visited.add(key)

        for key in self.parameters:
            visit(key)

    def _dependencies(self, key):
        return digest({parent: asdict(self.parameters[parent])
                       for parent in self.parameters[key].depends_on})

    def confirm(self, key: str, actor: str):
        self._validate_graph()
        if not isinstance(actor, str) or not actor.strip():
            raise ValueError('confirmation actor required')
        item = self.parameters[key]
        if item.state == 'rejected':
            raise ValueError('replace rejected proposal before confirmation')
        blockers = self.blockers(item.depends_on)
        if blockers:
            raise ValueError('confirm dependencies first: ' + ', '.join(blockers))
        self.parameters[key] = replace(item, state='confirmed', confirmed_by=actor.strip(),
            confirmed_at=datetime.now(timezone.utc).isoformat(), dependency_digest=self._dependencies(key))

    def blockers(self, required):
        self._validate_graph()
        blocked = set()

        def check(key):
            if key not in self.parameters:
                blocked.add(key)
                return
            item = self.parameters[key]
            if item.state != 'confirmed' or item.dependency_digest != self._dependencies(key):
                blocked.add(key)
            for parent in item.depends_on:
                check(parent)

        for key in required:
            check(key)
        return sorted(blocked)

    def to_dict(self):
        self._validate_graph()
        return {'schema_version': 1, 'source_sha256': self.source_sha256,
                'parameters': {k: asdict(v) for k, v in sorted(self.parameters.items())}}

    @classmethod
    def from_dict(cls, payload):
        if not isinstance(payload, dict) or payload.get('schema_version') != 1:
            raise ValueError('unsupported parameter ledger')
        params = {}
        for key, raw in payload['parameters'].items():
            item = dict(raw)
            item['depends_on'] = tuple(item.get('depends_on', ()))
            params[key] = Parameter(**item)
        ledger = cls(payload['source_sha256'], params)
        ledger._validate_graph()
        return ledger
