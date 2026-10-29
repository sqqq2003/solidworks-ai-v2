"""Durable request receipts and unresolved-session quarantine, without COM.

SQLite serializes admission across processes. The existing SessionLease OS
writer lock still owns native execution; this ledger survives its process.
"""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
import uuid

from cad_checkpoint import json_bytes

UNRESOLVED = frozenset({'RUNNING', 'RECOVERING', 'OUTCOME_UNKNOWN',
                        'RETURNED_LATE', 'ROLLBACK_UNCONFIRMED'})


class ReconcileRequired(RuntimeError):
    pass


class IdempotencyConflict(ValueError):
    pass


def default_database():
    base = Path(os.environ.get('LOCALAPPDATA', Path.home() / '.local' / 'state'))
    return base / 'SolidWorksAI' / 'control-v1.sqlite3'


def assert_no_unresolved():
    """Gate legacy owned write paths too, without creating a database on import."""
    path = default_database()
    if path.exists() and ReceiptStore(path).unresolved():
        raise ReconcileRequired('SolidWorks durable session unresolved; reconcile before new writes')


def request_identity(document, revision, payload, key=None):
    if not isinstance(revision, str) or not revision.strip():
        raise ValueError('nonempty document revision required')
    document = os.path.normcase(str(Path(document).expanduser().resolve()))
    payload_sha = hashlib.sha256(json_bytes(payload)).hexdigest()
    identity = {'document': document, 'revision': revision, 'payload_sha256': payload_sha}
    computed = hashlib.sha256(json_bytes(identity)).hexdigest()
    if key is not None and (not isinstance(key, str) or not key.strip()):
        raise ValueError('nonempty idempotency key required')
    return {'key': key or computed, **identity}


class ReceiptStore:
    def __init__(self, path=None):
        self.path = Path(path if path is not None else default_database()).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS requests (
                    key TEXT PRIMARY KEY, document TEXT NOT NULL, revision TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL, owner TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('RUNNING','COMPLETED','FAILED')),
                    session_state TEXT NOT NULL, metadata TEXT NOT NULL, result TEXT,
                    updated REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT, key TEXT NOT NULL,
                    state TEXT NOT NULL, detail TEXT NOT NULL, created REAL NOT NULL);
            ''')

    @contextmanager
    def _connection(self):
        db = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA synchronous=FULL')
        try:
            yield db
        finally:
            db.close()

    @contextmanager
    def _write(self):
        with self._connection() as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise

    @staticmethod
    def _row(row):
        if row is None:
            raise KeyError('request receipt not found')
        result = dict(row)
        result['metadata'] = json.loads(result['metadata'])
        result['result'] = json.loads(result['result']) if result['result'] else None
        return result

    def get(self, key):
        with self._connection() as db:
            return self._row(db.execute('SELECT * FROM requests WHERE key=?', (key,)).fetchone())

    def unresolved(self):
        with self._connection() as db:
            return [self._row(row) for row in db.execute('SELECT * FROM requests ORDER BY updated')
                    if row['session_state'] in UNRESOLVED]

    def _event(self, db, key, state, detail):
        db.execute('INSERT INTO events(key,state,detail,created) VALUES(?,?,?,?)',
                   (key, state, json_bytes(detail).decode(), time.time()))

    def begin(self, document, revision, payload, *, key=None, metadata=None):
        identity = request_identity(document, revision, payload, key)
        with self._write() as db:
            existing = db.execute('SELECT * FROM requests WHERE key=?', (identity['key'],)).fetchone()
            if existing:
                row = self._row(existing)
                if any(row[k] != identity[k] for k in ('document', 'revision', 'payload_sha256')):
                    raise IdempotencyConflict('IDEMPOTENCY_CONFLICT')
                if row['session_state'] in UNRESOLVED:
                    raise ReconcileRequired('request unresolved; reconcile before replay')
                return {**row, 'replayed': True}
            # One SW engine writer domain, deliberately broader than document.
            if any(row['session_state'] in UNRESOLVED for row in db.execute('SELECT session_state FROM requests')):
                raise ReconcileRequired('previous SolidWorks session unresolved; reconcile before new writes')
            owner = uuid.uuid4().hex
            db.execute('INSERT INTO requests VALUES(?,?,?,?,?,?,?,?,?,?)',
                       (identity['key'], identity['document'], identity['revision'], identity['payload_sha256'],
                        owner, 'RUNNING', 'RUNNING', json_bytes(metadata or {}).decode(), None, time.time()))
            self._event(db, identity['key'], 'RUNNING', {'owner': owner})
        return {**self.get(identity['key']), 'replayed': False}

    def assert_writer(self, key, owner):
        row = self.get(key)
        if row['owner'] != owner or row['status'] != 'RUNNING' or row['session_state'] != 'RUNNING':
            raise ReconcileRequired('durable session is quarantined; writes refused')

    def update_metadata(self, key, owner, **metadata):
        with self._write() as db:
            row = self._row(db.execute('SELECT * FROM requests WHERE key=?', (key,)).fetchone())
            if row['owner'] != owner or row['session_state'] != 'RUNNING':
                raise ReconcileRequired('cannot update quarantined session')
            row['metadata'].update(metadata)
            db.execute('UPDATE requests SET metadata=?, updated=? WHERE key=?',
                       (json_bytes(row['metadata']).decode(), time.time(), key))
            self._event(db, key, 'RUNNING', {'metadata_fields': sorted(metadata)})

    def quarantine(self, key, owner, state, *, detail=None):
        if state not in UNRESOLVED - {'RUNNING', 'RECOVERING'}:
            raise ValueError('invalid quarantine state')
        with self._write() as db:
            row = self._row(db.execute('SELECT * FROM requests WHERE key=?', (key,)).fetchone())
            if row['owner'] != owner or row['session_state'] == 'RESOLVED':
                raise ReconcileRequired('receipt ownership changed or already resolved')
            # A late return cannot erase a failed rollback diagnosis.
            if row['session_state'] == 'ROLLBACK_UNCONFIRMED':
                state = 'ROLLBACK_UNCONFIRMED'
            db.execute('UPDATE requests SET session_state=?, updated=? WHERE key=?', (state, time.time(), key))
            self._event(db, key, state, detail or {})

    def returned(self, key, owner):
        row = self.get(key)
        if row['session_state'] not in {'RUNNING', 'RESOLVED'}:
            self.quarantine(key, owner, 'RETURNED_LATE', detail={'previous_state': row['session_state']})

    def finish(self, key, owner, result, *, succeeded):
        with self._write() as db:
            row = self._row(db.execute('SELECT * FROM requests WHERE key=?', (key,)).fetchone())
            if row['owner'] != owner or row['session_state'] != 'RUNNING':
                raise ReconcileRequired('late result cannot resolve a quarantined attempt')
            status = 'COMPLETED' if succeeded else 'FAILED'
            db.execute('UPDATE requests SET status=?,session_state=?,result=?,updated=? WHERE key=?',
                       (status, 'RESOLVED', json_bytes(result).decode(), time.time(), key))
            self._event(db, key, 'RESOLVED', {'status': status})

    def reconcile(self, key, verifier):
        """Trusted native verifier, never a caller-supplied `confirmed: true`.

        Admission stays blocked while verification runs. A crash leaves
        RECOVERING. A repeated reconciliation may verify that state again.
        No request is re-executed, and no FAILED key is retried here.
        """
        with self._write() as db:
            row = self._row(db.execute('SELECT * FROM requests WHERE key=?', (key,)).fetchone())
            if row['session_state'] not in UNRESOLVED:
                return row
            db.execute('UPDATE requests SET session_state=?,updated=? WHERE key=?', ('RECOVERING', time.time(), key))
            self._event(db, key, 'RECOVERING', {'previous_state': row['session_state']})
        # Persist RECOVERING before external verification. A process crash or
        # rejected proof must leave durable quarantine rather than reset state.
        with self._write() as db:
            row = self._row(db.execute('SELECT * FROM requests WHERE key=?', (key,)).fetchone())
            if row['session_state'] == 'RESOLVED':
                return row
            if row['session_state'] != 'RECOVERING':
                raise ReconcileRequired('session changed during reconciliation')
            # Hold the SQLite admission transaction while verifying. Concurrent
            # reconcilers cannot release a different session under this proof.
            proof = verifier(row)
            if not isinstance(proof, dict) or proof.get('quiescent') is not True or proof.get('baseline_bytes_verified') is not True:
                raise ReconcileRequired('reconciliation did not prove quiescence and baseline bytes')
            result = {'status': 'failed', 'recovery': 'baseline_bytes_reconciled',
                      'proof': proof, 'native_acceptance': 'pending_windows_validation',
                      'manufacturing_approved': False}
            db.execute('UPDATE requests SET status=?,session_state=?,result=?,updated=? WHERE key=?',
                       ('FAILED', 'RESOLVED', json_bytes(result).decode(), time.time(), key))
            self._event(db, key, 'RESOLVED', result)
        return self.get(key)
