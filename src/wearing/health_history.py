"""Bounded, tenant-local health evidence. Observations are not heartbeats.

No log/message/error text is read or stored. The monitor never repairs, starts or
stops an engine, sends an alert, or uploads diagnostics. Export requires an
explicit caller action and remains a local, expiring artifact.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
import uuid
from datetime import datetime, timezone

from .diagnostics import TASK_STATES, reference, stamp

RETENTION = 7 * 86400
EXPORT_TTL = 86400
INTERVAL = 300
MAX_SAMPLES = 2016
MAX_EVENTS = 1000
MAX_EXPORT_BYTES = 1024 * 1024
CATEGORIES = frozenset({'chat', 'voice', 'sync', 'files', 'notifications', 'devices', 'performance', 'other'})
STATUSES = frozenset({'ok', 'fault', 'review', 'waiting', 'inactive', 'ended', 'unknown', 'not_configured'})
EVENT_KINDS = frozenset({'condition_started', 'condition_changed', 'condition_cleared', 'condition_ended', 'state_changed'})
CODES = frozenset({'observed', 'runtime_unavailable', 'runtime_error', 'engine_unavailable', 'engine_timeout',
    'device_source_unavailable', 'device_disconnected', 'device_review', 'run_failed', 'engine_connection_lost',
    'run_state_unknown', 'stop_unconfirmed', 'progress_check', 'collection_failed'})
COMPONENTS = frozenset({'runtime', 'engine', 'devices', 'task', 'collector'})
OWNER = re.compile(r'^(?:local|[a-f0-9]{64})$')
KEY = re.compile(r'^[a-zA-Z0-9_-]{16,80}$')


def at(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


def safe_ref(value):
    return value if isinstance(value, str) and re.fullmatch(r'ref_[a-f0-9]{16}', value) else reference(value)


class HealthError(ValueError):
    def __init__(self, code, status=400):
        self.code, self.status = code, status
        super().__init__(code)


def observation(component, status, code='observed', *, task_id=None, run_id=None, attempt=None, phase=None, state_at=None, owner=None):
    return {'component': component, 'status': status, 'code': code, 'task_id': task_id,
            'run_id': run_id, 'attempt': attempt, 'phase': phase, 'last_state_event_at': state_at, 'owner_scope': owner}


def project_observation(raw):
    """Re-project persisted evidence at every read/export, never passthrough JSON."""
    if not isinstance(raw, dict) or raw.get('component') not in COMPONENTS:
        return None
    return observation(raw['component'], raw.get('status') if raw.get('status') in STATUSES else 'unknown',
        raw.get('code') if raw.get('code') in CODES else 'observed',
        task_id=safe_ref(raw.get('task_id')), run_id=safe_ref(raw.get('run_id')),
        attempt=min(100000, max(0, raw['attempt'])) if type(raw.get('attempt')) is int else None,
        phase=raw.get('phase') if raw.get('phase') in TASK_STATES else None,
        state_at=stamp(raw.get('last_state_event_at')),
        owner=raw.get('owner_scope') if isinstance(raw.get('owner_scope'), str) and OWNER.fullmatch(raw['owner_scope']) else None)


def signals(snapshot, principals, require_owner):
    result = []
    runtime = snapshot.get('runtime', {})
    if runtime.get('state') == 'unavailable':
        result.append(observation('runtime', 'fault', 'runtime_unavailable'))
    elif runtime.get('error_present') is True or runtime.get('phase') == 'failed':
        result.append(observation('runtime', 'fault', 'runtime_error'))
    else:
        result.append(observation('runtime', 'ok' if runtime.get('running') is True else
            'not_configured' if runtime.get('installed') is False else
            'inactive' if runtime.get('running') is False else 'unknown'))
    state = snapshot.get('engine_probe', {}).get('state')
    result.append(observation('engine', 'ok' if state == 'reachable' else 'fault' if state in {'timeout', 'unavailable'} else
        'not_configured' if state == 'not_configured' else 'unknown',
        'engine_timeout' if state == 'timeout' else 'engine_unavailable' if state == 'unavailable' else 'observed'))
    devices = snapshot.get('devices', {})
    items = devices.get('items', [])
    active = [row for row in items if isinstance(row, dict) and row.get('paused') is not True]
    if devices.get('state') == 'unavailable':
        result.append(observation('devices', 'fault', 'device_source_unavailable'))
    elif devices.get('state') != 'observed':
        result.append(observation('devices', 'unknown'))
    elif any(row.get('needs_review') is True for row in active):
        result.append(observation('devices', 'review', 'device_review'))
    elif any(row.get('online') is False or row.get('connected') is False for row in active):
        result.append(observation('devices', 'fault', 'device_disconnected'))
    else:
        result.append(observation('devices', 'not_configured' if not items else 'inactive' if not active else
            'ok' if devices.get('truncated') is not True and all(row.get('online') is True or row.get('connected') is True for row in active) else 'unknown'))
    for row in snapshot.get('tasks', {}).get('items', [])[:30]:
        if not isinstance(row, dict):
            continue
        task_id = row.get('task_id')
        owner = principals.get(task_id)
        if require_owner and not owner:
            continue
        phase = row.get('phase')
        error = row.get('error_category')
        status, code = 'unknown', 'observed'
        if error in {'run_failed', 'engine_connection_lost', 'run_state_unknown', 'stop_unconfirmed'}:
            status, code = ('review' if error in {'run_state_unknown', 'stop_unconfirmed'} else 'fault'), error
        elif phase in {'stopped', 'closed', 'verified', 'completed_unverified'}:
            status = 'ended'
        elif phase == 'waiting_for_approval':
            status = 'waiting'
        elif row.get('needs_progress_check') is True:
            status, code = 'review', 'progress_check'
        elif phase in {'running', 'starting', 'stopping', 'queued', 'draft'}:
            status = 'ok'
        result.append(observation('task', status, code, task_id=safe_ref(task_id),
            run_id=safe_ref(row.get('run_id')),
            attempt=min(100000, max(0, row['attempt'])) if type(row.get('attempt')) is int else None,
            phase=phase if phase in TASK_STATES else None, state_at=stamp(row.get('last_state_event_at')),
            owner=owner or 'local'))
    return [*result, observation('collector', 'ok')]


class HealthHistory:
    def __init__(self, store, *, clock=time.time, require_owner=False, retention=RETENTION,
                 max_samples=MAX_SAMPLES, max_events=MAX_EVENTS, interval=INTERVAL):
        self.store, self.clock, self.require_owner = store, clock, require_owner
        self.retention, self.max_samples, self.max_events = retention, max_samples, max_events
        self.interval = interval
        with store.connection() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS health_samples (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, identity_id TEXT NOT NULL,
                    observed_at REAL NOT NULL, source TEXT NOT NULL, deployment TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS health_samples_scope ON health_samples(identity_id,id);
                CREATE TABLE IF NOT EXISTS health_conditions (
                    identity_id TEXT NOT NULL, component TEXT NOT NULL, subject TEXT NOT NULL, owner_scope TEXT NOT NULL,
                    status TEXT NOT NULL, code TEXT NOT NULL, condition_code TEXT, open_since REAL, observed_at REAL NOT NULL,
                    PRIMARY KEY(identity_id,component,subject,owner_scope));
                CREATE TABLE IF NOT EXISTS health_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, identity_id TEXT NOT NULL, sample_id INTEGER NOT NULL,
                    observed_at REAL NOT NULL, kind TEXT NOT NULL, component TEXT NOT NULL,
                    subject TEXT NOT NULL, owner_scope TEXT NOT NULL, status TEXT NOT NULL, code TEXT NOT NULL,
                    previous_status TEXT, previous_code TEXT, condition_started_at REAL);
                CREATE INDEX IF NOT EXISTS health_events_scope ON health_events(identity_id,id);
                CREATE TABLE IF NOT EXISTS health_exports (
                    id TEXT PRIMARY KEY, identity_id TEXT NOT NULL, owner_scope TEXT NOT NULL,
                    request_key TEXT NOT NULL, category TEXT NOT NULL, created_at REAL NOT NULL,
                    expires_at REAL NOT NULL, payload TEXT NOT NULL, sha256 TEXT NOT NULL,
                    UNIQUE(identity_id,owner_scope,request_key));
            ''')
            if 'previous_code' not in {row[1] for row in db.execute('PRAGMA table_info(health_events)')}:
                db.execute('ALTER TABLE health_events ADD COLUMN previous_code TEXT')
            if 'condition_code' not in {row[1] for row in db.execute('PRAGMA table_info(health_conditions)')}:
                db.execute('ALTER TABLE health_conditions ADD COLUMN condition_code TEXT')
                db.execute('UPDATE health_conditions SET condition_code=code WHERE open_since IS NOT NULL')

    def owner(self, value):
        if not self.require_owner and value is None:
            return 'local'
        if not isinstance(value, str) or not OWNER.fullmatch(value) or (self.require_owner and value == 'local'):
            raise HealthError('account_scope_required', 401)
        return value

    def identities(self):
        with self.store.connection() as db:
            return [row[0] for row in db.execute('SELECT id FROM identities ORDER BY id')]

    def record(self, identity, snapshot, *, source='scheduled', failed=False):
        self.store.identity(identity)
        if source not in {'scheduled', 'manual'} or not isinstance(snapshot, dict):
            raise HealthError('invalid_observation')
        if not failed and snapshot.get('identity_id') != identity:
            raise HealthError('observation_scope_mismatch')
        now = self.clock()
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            # Principals are server-owned, never taken from diagnostics/request JSON.
            principals = {reference(row[0]): row[1] for row in db.execute('''SELECT t.id,p.owner_scope FROM tasks t
                JOIN task_principals p ON t.id=p.task_id WHERE t.identity_id=? ORDER BY t.created_at DESC,t.id DESC LIMIT 31''', (identity,))
                if isinstance(row[1], str) and OWNER.fullmatch(row[1]) and (not self.require_owner or row[1] != 'local')}
            rows = [observation('collector', 'fault', 'collection_failed')] if failed else signals(snapshot, principals, self.require_owner)
            payload = json.dumps(rows, separators=(',', ':'))
            deployment = snapshot.get('service', {}).get('deployment')
            if deployment not in {'local', 'cloud', 'synthetic'}:
                deployment = 'unknown'
            sample_id = db.execute('INSERT INTO health_samples(identity_id,observed_at,source,deployment,payload) VALUES(?,?,?,?,?)',
                (identity, now, source, deployment, payload)).lastrowid
            for row in rows:
                key = (identity, row['component'], row['task_id'] or '', row['owner_scope'] or '')
                previous = db.execute('SELECT * FROM health_conditions WHERE identity_id=? AND component=? AND subject=? AND owner_scope=?', key).fetchone()
                opened = previous['open_since'] if previous else None
                condition_code = previous['condition_code'] if previous else None
                previous_code = condition_code or (previous['code'] if previous else None)
                kind = None
                if row['status'] in {'fault', 'review'}:
                    if opened is None:
                        opened, kind = now, 'condition_started'
                    elif condition_code != row['code']:
                        kind = 'condition_changed'
                    condition_code = row['code']
                elif opened is not None and row['status'] in {'ok', 'ended'}:
                    kind = 'condition_cleared' if row['status'] == 'ok' else 'condition_ended'
                elif previous and previous['status'] != row['status']:
                    kind = 'state_changed'
                if kind:
                    db.execute('''INSERT INTO health_events(identity_id,sample_id,observed_at,kind,component,subject,
                        owner_scope,status,code,previous_status,previous_code,condition_started_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
                        (identity, sample_id, now, kind, row['component'], row['task_id'] or '', row['owner_scope'] or '',
                         row['status'], row['code'], previous['status'] if previous else None, previous_code, opened))
                # Unknown/inactive/unconfigured cannot prove an earlier issue recovered.
                if kind in {'condition_cleared', 'condition_ended'}:
                    opened, condition_code = None, None
                db.execute('''INSERT OR REPLACE INTO health_conditions
                    (identity_id,component,subject,owner_scope,status,code,condition_code,open_since,observed_at)
                    VALUES(?,?,?,?,?,?,?,?,?)''', (*key, row['status'], row['code'], condition_code, opened, now))
            self._purge(db, now)
        return sample_id

    def _purge(self, db, now):
        cutoff = now - self.retention
        db.execute('DELETE FROM health_samples WHERE observed_at<?', (cutoff,))
        db.execute('DELETE FROM health_events WHERE observed_at<?', (cutoff,))
        db.execute('DELETE FROM health_conditions WHERE observed_at<?', (cutoff,))
        db.execute('DELETE FROM health_exports WHERE expires_at<=?', (now,))
        for row in db.execute('SELECT DISTINCT identity_id FROM health_samples').fetchall():
            db.execute('DELETE FROM health_samples WHERE identity_id=? AND id NOT IN (SELECT id FROM health_samples WHERE identity_id=? ORDER BY id DESC LIMIT ?)',
                (row[0], row[0], self.max_samples))
        for row in db.execute('SELECT DISTINCT identity_id FROM health_events').fetchall():
            db.execute('DELETE FROM health_events WHERE identity_id=? AND id NOT IN (SELECT id FROM health_events WHERE identity_id=? ORDER BY id DESC LIMIT ?)',
                (row[0], row[0], self.max_events))
        # Subject churn also remains bounded independently of the sample/event caps.
        for row in db.execute('SELECT DISTINCT identity_id FROM health_conditions').fetchall():
            db.execute('DELETE FROM health_conditions WHERE identity_id=? AND rowid NOT IN (SELECT rowid FROM health_conditions WHERE identity_id=? ORDER BY observed_at DESC,rowid DESC LIMIT 1000)', (row[0], row[0]))

    def _sample(self, row, owner):
        result = []
        for raw in json.loads(row['payload']):
            value = project_observation(raw)
            if value is None or (value['component'] == 'task' and value['owner_scope'] != owner):
                continue
            value.pop('owner_scope')
            result.append(value)
        return {'id': row['id'], 'observed_at': at(row['observed_at']), 'source': row['source'] if row['source'] in {'manual', 'scheduled'} else 'unknown',
            'deployment': row['deployment'] if row['deployment'] in {'cloud', 'local', 'synthetic'} else 'unknown', 'observations': result}

    def _read(self, db, identity, owner, sample_limit, event_limit, now, before_sample=None, before_event=None):
        rows = db.execute('''SELECT * FROM health_samples WHERE identity_id=? AND observed_at>=?
            AND (? IS NULL OR id<?) ORDER BY id DESC LIMIT ?''',
            (identity, now-self.retention, before_sample, before_sample, sample_limit+1)).fetchall()
        events = db.execute('''SELECT * FROM health_events WHERE identity_id=? AND observed_at>=? AND
            (component!='task' OR owner_scope=?) AND (? IS NULL OR id<?) ORDER BY id DESC LIMIT ?''',
            (identity, now-self.retention, owner, before_event, before_event, event_limit+1)).fetchall()
        result = []
        for row in events[:event_limit]:
            if row['component'] not in COMPONENTS or row['kind'] not in EVENT_KINDS:
                continue
            result.append({'id': row['id'], 'sample_id': row['sample_id'], 'observed_at': at(row['observed_at']),
                'kind': row['kind'], 'component': row['component'], 'task_id': safe_ref(row['subject']),
                'status': row['status'] if row['status'] in STATUSES else 'unknown',
                'code': row['code'] if row['code'] in CODES else 'observed',
                'previous_status': row['previous_status'] if row['previous_status'] in STATUSES else None,
                'previous_code': row['previous_code'] if row['previous_code'] in CODES else None,
                'condition_started_at': at(row['condition_started_at']) if row['condition_started_at'] is not None else None})
        bounds = db.execute('SELECT MIN(observed_at),MAX(observed_at) FROM health_samples WHERE identity_id=? AND observed_at>=?', (identity, now-self.retention)).fetchone()
        earliest, latest = bounds
        age = max(0, int(now-latest)) if latest is not None else None
        return {'schema': 1, 'scope': 'current_identity', 'read_at': at(now),
            'coverage': {'retention_seconds': self.retention, 'sample_interval_seconds': self.interval,
                'latest_observed_at': at(latest) if latest is not None else None, 'seconds_since_observation': age,
                'earliest_retained_at': at(earliest) if earliest is not None else None,
                'freshness': 'never_observed' if age is None else 'stale' if age > self.interval*2 else 'recent',
                'continuous_uptime_proven': False, 'mode': 'point_in_time_samples'},
            'samples': [self._sample(row, owner) for row in rows[:sample_limit]], 'samples_truncated': len(rows)>sample_limit,
            'next_before_sample': rows[sample_limit-1]['id'] if len(rows)>sample_limit else None,
            'events': result, 'events_truncated': len(events)>event_limit,
            'next_before_event': events[event_limit-1]['id'] if len(events)>event_limit else None}

    def history(self, identity, owner_scope=None, *, sample_limit=48, event_limit=100, before_sample=None, before_event=None):
        owner = self.owner(owner_scope)
        self.store.identity(identity)
        if type(sample_limit) is not int or not 1 <= sample_limit <= 288 or type(event_limit) is not int or not 1 <= event_limit <= 500:
            raise HealthError('invalid_limit')
        if any(value is not None and (type(value) is not int or not 1 <= value <= 2**63-1) for value in (before_sample, before_event)):
            raise HealthError('invalid_cursor')
        with self.store.connection() as db:
            # One SQLite read snapshot, so IDs/events/export refer to the same view.
            db.execute('BEGIN')
            return self._read(db, identity, owner, sample_limit, event_limit, self.clock(), before_sample, before_event)

    def create_export(self, identity, owner_scope, request_key, category):
        owner = self.owner(owner_scope)
        self.store.identity(identity)
        if not isinstance(request_key, str) or not KEY.fullmatch(request_key) or category not in CATEGORIES:
            raise HealthError('invalid_export')
        now = self.clock()
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            self._purge(db, now)
            prior = db.execute('SELECT * FROM health_exports WHERE identity_id=? AND owner_scope=? AND request_key=?', (identity, owner, request_key)).fetchone()
            if prior:
                if prior['category'] != category:
                    raise HealthError('export_request_conflict', 409)
                return self._export_metadata(prior)
            count = db.execute('SELECT COUNT(*) FROM health_exports WHERE identity_id=? AND owner_scope=?', (identity, owner)).fetchone()[0]
            if count >= 5:
                raise HealthError('export_limit', 429)
            report_id = uuid.uuid4().hex
            value = {'schema': 1, 'report_id': report_id, 'created_at': at(now), 'expires_at': at(now+EXPORT_TTL),
                'category': category, 'transmission': 'not_sent',
                'contents': self._read(db, identity, owner, 288, 500, now)}
            payload = json.dumps(value, ensure_ascii=False, indent=2)
            while len(payload.encode()) > MAX_EXPORT_BYTES and value['contents']['samples']:
                value['contents']['samples'].pop()
                value['contents']['samples_truncated'] = True
                value['contents']['next_before_sample'] = value['contents']['samples'][-1]['id'] if value['contents']['samples'] else None
                payload = json.dumps(value, ensure_ascii=False, indent=2)
            if len(payload.encode()) > MAX_EXPORT_BYTES:
                raise HealthError('export_too_large', 503)
            digest = hashlib.sha256(payload.encode()).hexdigest()
            db.execute('INSERT INTO health_exports VALUES(?,?,?,?,?,?,?,?,?)',
                (report_id, identity, owner, request_key, category, now, now+EXPORT_TTL, payload, digest))
            row = db.execute('SELECT * FROM health_exports WHERE id=?', (report_id,)).fetchone()
            return self._export_metadata(row)

    @staticmethod
    def _export_metadata(row):
        return {'schema': 1, 'id': row['id'], 'created_at': at(row['created_at']), 'expires_at': at(row['expires_at']),
            'category': row['category'], 'sha256': row['sha256'], 'bytes': len(row['payload'].encode()),
            'filename': f'pajio-diagnostics-{row["id"]}.json', 'transmission': 'not_sent'}

    def download(self, identity, owner_scope, export_id):
        owner = self.owner(owner_scope)
        self.store.identity(identity)
        if not isinstance(export_id, str) or not re.fullmatch(r'[a-f0-9]{32}', export_id):
            raise HealthError('export_not_found', 404)
        with self.store.connection() as db:
            row = db.execute('SELECT * FROM health_exports WHERE id=? AND identity_id=? AND owner_scope=? AND expires_at>?',
                (export_id, identity, owner, self.clock())).fetchone()
            if row is None:
                raise HealthError('export_not_found', 404)
            return row['payload'].encode(), self._export_metadata(row)


class HealthMonitor:
    def __init__(self, history, diagnostics, *, deployment='local', timeout=20, minimum_interval=15):
        self.history, self.diagnostics = history, diagnostics
        self.deployment, self.timeout, self.minimum_interval = deployment, timeout, minimum_interval
        self._lock = asyncio.Lock()
        self._last = {}
        self.running = False

    async def collect(self, identity, *, source='scheduled'):
        async with self._lock:
            self.history.store.identity(identity)
            now = self.history.clock()
            if identity in self._last and now-self._last[identity] < self.minimum_interval:
                return False
            try:
                async with asyncio.timeout(self.timeout):
                    snapshot = await self.diagnostics.snapshot(identity, self.deployment)
            except asyncio.CancelledError:
                raise
            except Exception:
                self.history.record(identity, {}, source=source, failed=True)
            else:
                self.history.record(identity, snapshot, source=source)
            self._last[identity] = now
            return True

    async def run(self, stop):
        if self.running:
            raise RuntimeError('Health monitor is already running')
        self.running = True
        try:
            while not stop.is_set():
                try:
                    identities = self.history.identities()
                except Exception:
                    identities = []
                self._last = {key: value for key, value in self._last.items() if key in identities}
                for identity in identities:
                    if stop.is_set():
                        break
                    try:
                        await self.collect(identity)
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        # A failed DB cannot record its own outage. Subsequent stale
                        # coverage remains truthful; never invent a successful sample.
                        pass
                try:
                    await asyncio.wait_for(stop.wait(), self.history.interval)
                except TimeoutError:
                    pass
        finally:
            self.running = False
