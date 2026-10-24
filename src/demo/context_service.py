"""Durable demo-only context and immutable Operations evidence."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3


def now():
    return datetime.now(timezone.utc).isoformat()


class DemoContextService:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS demo_financial_contexts '
                       '(event_id TEXT PRIMARY KEY, revision INTEGER NOT NULL, '
                       'payload_json TEXT NOT NULL, updated_at TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS demo_operations_evidence '
                       '(event_id TEXT PRIMARY KEY, payload_json TEXT NOT NULL, created_at TEXT NOT NULL)')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path)
        try:
            with db:
                yield db
        finally:
            db.close()

    def list_events(self):
        with self.connect() as db:
            return [r[0] for r in db.execute(
                'SELECT event_id FROM demo_financial_contexts ORDER BY updated_at DESC')]

    def create(self, payload):
        with self.connect() as db:
            db.execute('INSERT INTO demo_financial_contexts VALUES (?, ?, ?, ?)',
                       (payload['event_id'], 1, json.dumps(payload), now()))
        return self.load(payload['event_id'])

    def load(self, event_id):
        with self.connect() as db:
            row = db.execute('SELECT revision, payload_json FROM demo_financial_contexts '
                             'WHERE event_id=?', (event_id,)).fetchone()
        if row is None:
            raise ValueError('Unknown demo activity')
        payload = json.loads(row[1])
        if payload.get('schema_version') != 1 or payload.get('event_id') != event_id:
            raise ValueError('Invalid demo context; review required')
        return {**payload, 'revision': row[0]}

    def save(self, payload, expected_revision):
        content = {k: v for k, v in payload.items() if k != 'revision'}
        with self.connect() as db:
            changed = db.execute('UPDATE demo_financial_contexts SET revision=revision+1, '
                                 'payload_json=?, updated_at=? WHERE event_id=? AND revision=?',
                                 (json.dumps(content), now(), payload['event_id'], expected_revision))
            if changed.rowcount != 1:
                raise ValueError('Context changed; reload before continuing')
        return self.load(payload['event_id'])

    def evidence(self, event_id):
        with self.connect() as db:
            row = db.execute('SELECT payload_json FROM demo_operations_evidence WHERE event_id=?',
                             (event_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def save_evidence(self, event_id, payload):
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO demo_operations_evidence VALUES (?, ?, ?)',
                       (event_id, json.dumps(payload), now()))
        return self.evidence(event_id)
