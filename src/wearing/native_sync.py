"""Opt-in, one-way phone sources -> personal records. No absence-based deletion."""
import hashlib
import json
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .life import LifeBook, LifeDraft
from .store import now


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(encoded(value).encode()).hexdigest()


class SyncError(Exception):
    def __init__(self, message, status=409):
        super().__init__(message)
        self.status = status


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class SyncSource(Strict):
    kind: Literal['event', 'reminder']
    id: str = Field(min_length=1, max_length=512)
    title: str = Field(min_length=1, max_length=200)


class SyncItem(Strict):
    external_id: str = Field(min_length=1, max_length=512)
    occurrence_id: str = Field(default='', max_length=512)
    record: LifeDraft


class SyncSnapshot(Strict):
    source: SyncSource
    items: list[SyncItem] = Field(max_length=500)
    complete: bool
    window_start: str | None = None
    window_end: str | None = None

    @model_validator(mode='after')
    def validate_items(self):
        keys = [(v.external_id, v.occurrence_id) for v in self.items]
        if len(set(keys)) != len(keys):
            raise ValueError('Duplicate native identifiers')
        expected = 'event' if self.source.kind == 'event' else 'task'
        if any(v.record.kind != expected for v in self.items):
            raise ValueError('Wrong native record kind')
        if any(len(v.record.content) > 4000 for v in self.items):
            raise ValueError('Native notes exceed allowed size')
        if self.source.kind == 'event':
            start, end = parse_stamp(self.window_start), parse_stamp(self.window_end)
            if not 0 < (end - start).total_seconds() <= 45 * 86400:
                raise ValueError('Invalid read window')
        elif self.window_start is not None or self.window_end is not None or any(v.occurrence_id for v in self.items):
            raise ValueError('Invalid reminder window')
        return self


def parse_stamp(value):
    if not isinstance(value, str):
        raise ValueError('Missing timestamp')
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('Missing timestamp zone')
    return result


class NativeSyncBook:
    def __init__(self, store):
        self.store = store
        LifeBook(store)
        with store.connection() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS native_sync_settings (
                    identity TEXT NOT NULL, owner TEXT NOT NULL, installation TEXT NOT NULL,
                    revision INTEGER NOT NULL, enabled INTEGER NOT NULL, sources TEXT NOT NULL,
                    PRIMARY KEY(identity,owner,installation));
                CREATE TABLE IF NOT EXISTS native_sync_requests (
                    identity TEXT NOT NULL, owner TEXT NOT NULL, installation TEXT NOT NULL,
                    request_id TEXT NOT NULL, hash TEXT NOT NULL, receipt TEXT NOT NULL,
                    PRIMARY KEY(identity,owner,installation,request_id));
                CREATE TABLE IF NOT EXISTS native_sync_objects (
                    identity TEXT NOT NULL, owner TEXT NOT NULL, installation TEXT NOT NULL,
                    source_kind TEXT NOT NULL, source_id TEXT NOT NULL, external_id TEXT NOT NULL,
                    occurrence_id TEXT NOT NULL, record_id TEXT NOT NULL,
                    applied_revision INTEGER NOT NULL, source_hash TEXT NOT NULL, latest_body TEXT NOT NULL,
                    observed_at TEXT NOT NULL, state TEXT NOT NULL, source_title TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(identity,owner,installation,source_kind,source_id,external_id,occurrence_id));
            ''')
            if 'source_title' not in {row['name'] for row in db.execute('PRAGMA table_info(native_sync_objects)')}:
                db.execute("ALTER TABLE native_sync_objects ADD COLUMN source_title TEXT NOT NULL DEFAULT ''")
            db.execute('CREATE INDEX IF NOT EXISTS native_sync_owner_index ON native_sync_objects(identity,owner,observed_at DESC,record_id)')

    def index(self, identity, owner):
        """Bounded display metadata only; credentials and installation IDs stay private."""
        self.store.identity(identity)
        with self.store.connection() as db:
            rows = db.execute('SELECT installation,source_kind,source_id,record_id,source_title,state FROM native_sync_objects WHERE identity=? AND owner=? ORDER BY observed_at DESC,record_id LIMIT 1001', (identity, owner)).fetchall()
            return {'checked_at': now(), 'limit': 1000, 'truncated': len(rows) > 1000, 'records': [
                {'record_id': row['record_id'], 'source_key': digest([row['installation'], row['source_kind'], row['source_id']]),
                 'title': row['source_title'] or ('系统日历' if row['source_kind'] == 'event' else '系统提醒事项'),
                 'kind': row['source_kind'], 'state': row['state']} for row in rows[:1000]]}

    @staticmethod
    def _setting(row):
        return {'revision': row['revision'], 'enabled': bool(row['enabled']), 'sources': json.loads(row['sources'])}

    def state(self, identity, owner, installation):
        self.store.identity(identity)
        with self.store.connection() as db:
            row = db.execute('SELECT * FROM native_sync_settings WHERE identity=? AND owner=? AND installation=?', (identity, owner, installation)).fetchone()
            records = db.execute('SELECT record_id,source_kind,source_id,state,observed_at FROM native_sync_objects WHERE identity=? AND owner=? AND installation=?', (identity, owner, installation)).fetchall()
            return {**(self._setting(row) if row else {'revision': 0, 'enabled': False, 'sources': []}), 'records': [dict(r) for r in records]}

    def _previous(self, db, scope, request_id, fingerprint):
        old = db.execute('SELECT * FROM native_sync_requests WHERE identity=? AND owner=? AND installation=? AND request_id=?', (*scope, request_id)).fetchone()
        if old:
            if old['hash'] != fingerprint:
                raise SyncError('同步请求编号已用于其他内容。')
            return json.loads(old['receipt'])

    def _remember(self, db, scope, request_id, fingerprint, receipt):
        db.execute('INSERT INTO native_sync_requests VALUES(?,?,?,?,?,?)', (*scope, request_id, fingerprint, encoded(receipt)))
        return receipt

    def configure(self, identity, owner, installation, revision, enabled, sources, request_id):
        self.store.identity(identity)
        selected = [SyncSource.model_validate(v).model_dump() for v in sources]
        if len(selected) > 50 or (enabled and not selected) or len({(v['kind'], v['id']) for v in selected}) != len(selected):
            raise SyncError('请选取要同步的不同来源。', 422)
        scope = (identity, owner, installation)
        fingerprint = digest(['configure', revision, enabled, selected])
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            old = self._previous(db, scope, request_id, fingerprint)
            if old is not None:
                return old
            row = db.execute('SELECT * FROM native_sync_settings WHERE identity=? AND owner=? AND installation=?', scope).fetchone()
            if revision != (row['revision'] if row else 0):
                raise SyncError('同步来源已有变化，请重新读取设置。')
            db.execute('INSERT OR REPLACE INTO native_sync_settings VALUES(?,?,?,?,?,?)', (*scope, revision + 1, int(enabled), encoded(selected)))
            return self._remember(db, scope, request_id, fingerprint, {'revision': revision + 1, 'enabled': enabled, 'sources': selected})

    def upload(self, identity, owner, installation, revision, request_id, observed_at, snapshots):
        self.store.identity(identity)
        stamp = parse_stamp(observed_at)
        values = [SyncSnapshot.model_validate(v) for v in snapshots]
        if not values or len(values) > 50 or sum(len(s.items) for s in values) > 500 or len({(s.source.kind, s.source.id) for s in values}) != len(values):
            raise SyncError('来源快照不完整。', 422)
        scope = (identity, owner, installation)
        fingerprint = digest(['upload', revision, observed_at, snapshots])
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            setting = db.execute('SELECT * FROM native_sync_settings WHERE identity=? AND owner=? AND installation=?', scope).fetchone()
            # Even a historical receipt cannot grant a disabled uploader fresh access.
            if not setting or not setting['enabled'] or setting['revision'] != revision:
                raise SyncError('同步已停用或来源已有变化；这份旧读取没有写入。')
            selected = {(s['kind'], s['id']): s for s in json.loads(setting['sources'])}
            if any((s.source.kind, s.source.id) not in selected for s in values):
                raise SyncError('快照包含未选择的来源。', 403)
            previous = self._previous(db, scope, request_id, fingerprint)
            if previous is not None:
                return previous
            counts = {'created': 0, 'updated': 0, 'unchanged': 0, 'conflicts': 0, 'unseen': 0,
                      'truncated': sum(not snapshot.complete for snapshot in values)}
            ids = []
            for snapshot in values:
                source = selected[(snapshot.source.kind, snapshot.source.id)]
                source_scope = (*scope, snapshot.source.kind, snapshot.source.id)
                seen = set()
                for item in snapshot.items:
                    key = (*source_scope, item.external_id, item.occurrence_id)
                    seen.add((item.external_id, item.occurrence_id))
                    old = db.execute('SELECT * FROM native_sync_objects WHERE identity=? AND owner=? AND installation=? AND source_kind=? AND source_id=? AND external_id=? AND occurrence_id=?', key).fetchone()
                    if old and parse_stamp(old['observed_at']) > stamp:
                        counts['unchanged'] += 1
                        ids.append(old['record_id'])
                        continue
                    draft = item.record.model_dump()
                    label = '系统日历' if source['kind'] == 'event' else '系统提醒事项'
                    draft['content'] = f"来自{label}「{source['title']}」的单向副本。修改这里不会回写系统。\n\n" + draft['content'][:11500]
                    body, source_hash = encoded(draft), digest(draft)
                    current = db.execute('SELECT * FROM life_records WHERE id=? AND identity_id=?', (old['record_id'], identity)).fetchone() if old else None
                    if old and (not current or current['revision'] != old['applied_revision'] or current['deleted_at']):
                        db.execute('UPDATE native_sync_objects SET latest_body=?,source_hash=?,observed_at=?,state=?,source_title=? WHERE identity=? AND owner=? AND installation=? AND source_kind=? AND source_id=? AND external_id=? AND occurrence_id=?', (body, source_hash, observed_at, 'conflict', source['title'], *key))
                        counts['conflicts'] += 1
                        ids.append(old['record_id'])
                        continue
                    if current:
                        record_id = current['id']
                        if current['body'] != body:
                            db.execute('UPDATE life_records SET body=?,revision=revision+1,updated_at=? WHERE id=?', (body, now(), record_id))
                            counts['updated'] += 1
                        else:
                            counts['unchanged'] += 1
                    else:
                        record_id = 'life_' + uuid.uuid4().hex
                        created = now()
                        db.execute('INSERT INTO life_records VALUES(?,?,?,?,?,?,?,?,?)', (record_id, identity, 1, body, None, created, created, 'native-sync:' + digest(key), source_hash))
                        counts['created'] += 1
                    record = LifeBook.unpack(db.execute('SELECT * FROM life_records WHERE id=?', (record_id,)).fetchone())
                    if not current or current['revision'] != record['revision']:
                        LifeBook.receipt(db, record, 'user')
                    db.execute('INSERT OR REPLACE INTO native_sync_objects VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)', (*key, record_id, record['revision'], source_hash, body, observed_at, 'synced', source['title']))
                    ids.append(record_id)
                if snapshot.complete:
                    prior = db.execute('SELECT * FROM native_sync_objects WHERE identity=? AND owner=? AND installation=? AND source_kind=? AND source_id=?', source_scope).fetchall()
                    for old in prior:
                        if (old['external_id'], old['occurrence_id']) in seen or parse_stamp(old['observed_at']) > stamp:
                            continue
                        # A rolling range, lost calendar, deleted object or changed recurrence cannot prove a tombstone.
                        if old['state'] != 'conflict':
                            db.execute('UPDATE native_sync_objects SET state=? WHERE record_id=?', ('unseen', old['record_id']))
                            counts['unseen'] += 1
            return self._remember(db, scope, request_id, fingerprint, {'request_id': request_id, 'revision': revision, 'observed_at': observed_at, 'record_ids': ids, **counts})
