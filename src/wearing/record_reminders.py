"""Owner-bound reminders for existing records; no models, invented times or local alarms."""
from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime, timezone

from .task_visibility import owner

TARGET = re.compile(r'^(?:life_[a-f0-9]{32}|recurrence_[a-f0-9]{32}_\d{8})$')
ADVANCES = (0, 5, 15, 30, 60, 1440)
WINDOW = 3600  # Quiet/expired registrations must not deliver obsolete appointments indefinitely.


class ReminderError(ValueError):
    def __init__(self, message, status=422):
        super().__init__(message)
        self.status = status


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def iso(stamp):
    return datetime.fromtimestamp(stamp, timezone.utc).isoformat() if stamp is not None else None


class RecordReminderBook:
    def __init__(self, store, *, clock=time.time):
        self.store, self.clock = store, clock
        with store.connection() as db:
            db.executescript('''
              CREATE TABLE IF NOT EXISTS record_reminders (
                id TEXT PRIMARY KEY, owner_scope TEXT NOT NULL, identity_id TEXT NOT NULL,
                target_id TEXT NOT NULL, revision INTEGER NOT NULL, enabled INTEGER NOT NULL,
                advance_minutes INTEGER NOT NULL, anchor_at REAL, activation INTEGER NOT NULL,
                reason TEXT, checked_at REAL NOT NULL, updated_at REAL NOT NULL,
                UNIQUE(owner_scope,identity_id,target_id));
              CREATE TABLE IF NOT EXISTS record_reminder_events (
                event_key TEXT PRIMARY KEY, reminder_id TEXT NOT NULL,
                anchor_at REAL NOT NULL, fire_at REAL NOT NULL, activation INTEGER NOT NULL);
              CREATE TABLE IF NOT EXISTS record_reminder_requests (
                owner_scope TEXT NOT NULL, identity_id TEXT NOT NULL, request_key TEXT NOT NULL,
                request_hash TEXT NOT NULL, receipt TEXT NOT NULL, created_at REAL NOT NULL,
                PRIMARY KEY(owner_scope,identity_id,request_key));
            ''')

    def _authorize(self, db, identity, owner_scope):
        try:
            owner(owner_scope)
        except ValueError as error:
            raise ReminderError(str(error), 401) from error
        if not db.execute('SELECT 1 FROM identities WHERE id=?', (identity,)).fetchone():
            raise ReminderError('当前身份不可用。', 404)
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='notification_revoked_owners'").fetchone() and db.execute('SELECT 1 FROM notification_revoked_owners WHERE owner_scope=?', (owner_scope,)).fetchone():
            raise ReminderError('账户通知授权已撤销。', 403)

    @staticmethod
    def source(db, identity, target):
        if not isinstance(target, str) or not TARGET.fullmatch(target):
            raise ReminderError('记录提醒目标无效。')
        record = None
        if target.startswith('life_'):
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='life_records'").fetchone():
                row = db.execute('SELECT * FROM life_records WHERE identity_id=? AND id=?', (identity, target)).fetchone()
                if row:
                    from .life import LifeBook
                    record = LifeBook.unpack(row)
        elif db.execute("SELECT 1 FROM sqlite_master WHERE name='calendar_series'").fetchone():
            from .calendar_series import CalendarSeriesBook, SeriesDraft, civil, dates
            series_id, raw = 'series_' + target[11:43], target[-8:]
            key = raw[:4] + '-' + raw[4:6] + '-' + raw[6:]
            row = db.execute('SELECT * FROM calendar_series WHERE identity_id=? AND id=?', (identity, series_id)).fetchone()
            if row and not row['deleted_at']:
                try:
                    day = civil(key)
                    original = next(dates(SeriesDraft.model_validate_json(row['body']), day, day), None)
                except (ValueError, OverflowError):
                    original = None
                exception = db.execute('SELECT * FROM calendar_exceptions WHERE series_id=? AND occurrence_key=?', (series_id, key)).fetchone()
                if original and not (exception and exception['cancelled']):
                    record = CalendarSeriesBook._record(row, key, json.loads(exception['body']) if exception and exception['body'] else original[1], exception)
        if record is None:
            return None, None, 'missing'
        if record['deleted_at']:
            return record, None, 'removed'
        if record['kind'] == 'task' and record.get('completed'):
            return record, None, 'completed'
        if record['kind'] == 'event' and record.get('all_day'):
            return record, None, 'all_day'
        when = record.get('start_at') if record['kind'] == 'event' else record.get('due_at') if record['kind'] == 'task' else None
        if not when:
            return record, None, 'no_time'
        try:
            value = datetime.fromisoformat(when.replace('Z', '+00:00'))
            if value.tzinfo is None:
                raise ValueError()
            return record, value.timestamp(), None
        except (ValueError, OverflowError):
            return record, None, 'no_time'

    @staticmethod
    def _cancel(db, reminder_id, stamp):
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='notification_outbox'").fetchone():
            db.execute("""UPDATE notification_outbox SET state='cancelled',error_code='ReminderChanged',updated_at=?
              WHERE state IN ('pending','awaiting_registration','sending') AND event_key IN
              (SELECT event_key FROM record_reminder_events WHERE reminder_id=?)""", (stamp, reminder_id))

    def _refresh(self, db, row):
        return refresh_row(db, row, self.clock())

    def _view(self, db, identity, target, owner_scope, row=None):
        record, anchor, reason = self.source(db, identity, target)
        if record is None and row is None:
            raise ReminderError('当前身份没有这条记录，或这次日程已取消。', 404)
        enabled = bool(row and row['enabled'])
        advance = row['advance_minutes'] if row else 15
        fire = anchor - advance * 60 if anchor is not None else None
        state = 'unavailable' if reason else 'disabled' if not enabled else 'expired' if self.clock() > anchor + WINDOW else 'scheduled' if self.clock() < fire else 'due'
        # Generic provider state is supplementary; it never proves device presentation.
        delivery = None
        if row and db.execute("SELECT 1 FROM sqlite_master WHERE name='notification_outbox'").fetchone():
            value = db.execute('''SELECT o.state FROM notification_outbox o JOIN record_reminder_events e ON e.event_key=o.event_key
              WHERE e.reminder_id=? AND e.activation=? AND o.owner_scope=? ORDER BY o.updated_at DESC LIMIT 1''', (row['id'], row['activation'], owner_scope)).fetchone()
            delivery = value[0] if value else None
        return {'identity_id': identity, 'target_id': target, 'revision': row['revision'] if row else 0,
                'record_revision': record['revision'] if record else None, 'enabled': enabled,
                'advance_minutes': advance, 'anchor_at': iso(anchor), 'fire_at': iso(fire),
                'status': state, 'reason': reason or (row['reason'] if row else None), 'provider_status': delivery}

    def get(self, identity, target, *, owner_scope='local'):
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            self._authorize(db, identity, owner_scope)
            row = db.execute('SELECT * FROM record_reminders WHERE identity_id=? AND owner_scope=? AND target_id=?', (identity, owner_scope, target)).fetchone()
            if row:
                row, _, _, _ = self._refresh(db, row)
            return self._view(db, identity, target, owner_scope, row)

    def save(self, identity, target, revision, record_revision, enabled, advance_minutes, request_key, *, owner_scope='local'):
        if type(revision) is not int or revision < 0 or type(record_revision) is not int or record_revision < 1 or type(enabled) is not bool or type(advance_minutes) is not int or advance_minutes not in ADVANCES or not isinstance(request_key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,120}', request_key):
            raise ReminderError('请核对提醒时间和版本。')
        digest = hashlib.sha256(encode([target, revision, record_revision, enabled, advance_minutes]).encode()).hexdigest()
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            self._authorize(db, identity, owner_scope)
            old = db.execute('SELECT request_hash,receipt FROM record_reminder_requests WHERE identity_id=? AND owner_scope=? AND request_key=?', (identity, owner_scope, request_key)).fetchone()
            if old:
                if old['request_hash'] != digest:
                    raise ReminderError('这个操作编号已经用于另一份提醒设置。', 409)
                return json.loads(old['receipt'])
            row = db.execute('SELECT * FROM record_reminders WHERE identity_id=? AND owner_scope=? AND target_id=?', (identity, owner_scope, target)).fetchone()
            record, anchor, reason = self.source(db, identity, target)
            if not record:
                raise ReminderError('这条记录或这次日程已不可用。', 404)
            if record['revision'] != record_revision or (row['revision'] if row else 0) != revision:
                raise ReminderError('记录或提醒设置已有变化，请读取最新版本后核对。', 409)
            if enabled and (reason or anchor - advance_minutes * 60 <= self.clock()):
                raise ReminderError('请先设置未来的具体时间；提醒时间必须还未到达。', 422)
            if not row and db.execute('SELECT count(*) FROM record_reminders WHERE identity_id=? AND owner_scope=?', (identity, owner_scope)).fetchone()[0] >= 500:
                raise ReminderError('当前身份已达到 500 条提醒设置上限。')
            if db.execute('SELECT count(*) FROM record_reminder_requests WHERE identity_id=? AND owner_scope=?', (identity, owner_scope)).fetchone()[0] >= 20000:
                raise ReminderError('提醒操作账本已达上限，请联系服务维护。')
            reminder_id = row['id'] if row else 'reminder_' + hashlib.sha256(encode([identity, owner_scope, target]).encode()).hexdigest()
            self._cancel(db, reminder_id, self.clock())
            db.execute('''INSERT INTO record_reminders VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
              ON CONFLICT(id) DO UPDATE SET revision=excluded.revision,enabled=excluded.enabled,
              advance_minutes=excluded.advance_minutes,anchor_at=excluded.anchor_at,activation=excluded.activation,
              reason=excluded.reason,checked_at=excluded.checked_at,updated_at=excluded.updated_at''',
                       (reminder_id, owner_scope, identity, target, revision + 1, int(enabled), advance_minutes, anchor,
                        (row['activation'] if row else 0) + 1, reason, self.clock(), self.clock()))
            current = db.execute('SELECT * FROM record_reminders WHERE id=?', (reminder_id,)).fetchone()
            result = {**self._view(db, identity, target, owner_scope, current), 'request_key': request_key}
            db.execute('INSERT INTO record_reminder_requests VALUES(?,?,?,?,?,?)', (owner_scope, identity, request_key, digest, encode(result), self.clock()))
            return result

    def collect(self, db):
        stamp = self.clock()
        # Rotate bounded work; no model or external account reads.
        for row in db.execute('SELECT * FROM record_reminders WHERE enabled=1 ORDER BY checked_at,id LIMIT 1000').fetchall():
            try:
                self._authorize(db, row['identity_id'], row['owner_scope'])
            except ReminderError:
                self._cancel(db, row['id'], stamp)
                db.execute('UPDATE record_reminders SET enabled=0,revision=revision+1,updated_at=? WHERE id=?', (stamp, row['id']))
                continue
            row, _, anchor, reason = self._refresh(db, row)
            if not row['enabled'] or reason:
                continue
            fire = anchor - row['advance_minutes'] * 60
            if stamp < fire or stamp > anchor + WINDOW:
                continue
            event = hashlib.sha256(encode(['record_reminder', row['id'], row['activation'], anchor, fire]).encode()).hexdigest()
            inserted = db.execute('INSERT OR IGNORE INTO record_reminder_events VALUES(?,?,?,?,?)', (event, row['id'], anchor, fire, row['activation'])).rowcount
            if not inserted:
                continue
            db.execute('INSERT INTO notification_events VALUES(?,?,?,?,?,?)', (event, row['identity_id'], row['target_id'], 'record_reminder', str(row['activation']), stamp))
            db.execute('''INSERT OR IGNORE INTO notification_outbox(event_key,identity_id,installation_id,state,next_at,updated_at,owner_scope)
              SELECT ?,identity_id,installation_id,CASE WHEN enabled=1 THEN 'pending' ELSE 'awaiting_registration' END,?,?,owner_scope
              FROM notification_devices WHERE identity_id=? AND owner_scope=? AND (enabled=1 OR reason='expired')''',
                       (event, stamp, stamp, row['identity_id'], row['owner_scope']))

    def current_event(self, db, event, identity, target, owner_scope):
        row = db.execute('''SELECT r.*,e.anchor_at AS event_anchor,e.fire_at,e.activation AS event_activation
          FROM record_reminder_events e JOIN record_reminders r ON r.id=e.reminder_id
          WHERE e.event_key=? AND r.identity_id=? AND r.target_id=? AND r.owner_scope=?''', (event, identity, target, owner_scope)).fetchone()
        if not row or not row['enabled'] or row['activation'] != row['event_activation']:
            return False
        try:
            self._authorize(db, identity, owner_scope)
            _, anchor, reason = self.source(db, identity, target)
        except ReminderError:
            return False
        return not reason and anchor == row['event_anchor'] and row['fire_at'] <= self.clock() <= anchor + WINDOW

    def resolve(self, db, identity, event, owner_scope):
        self._authorize(db, identity, owner_scope)
        row = db.execute('''SELECT r.target_id FROM record_reminders r JOIN record_reminder_events e ON e.reminder_id=r.id
          WHERE e.event_key=? AND r.identity_id=? AND r.owner_scope=? AND EXISTS
          (SELECT 1 FROM notification_outbox o WHERE o.event_key=e.event_key AND o.owner_scope=?)''', (event, identity, owner_scope, owner_scope)).fetchone()
        if not row:
            raise ReminderError('这条提醒不属于当前账户与身份。', 404)
        record, _, _ = self.source(db, identity, row['target_id'])
        if record is None:
            raise ReminderError('这次日程已取消或记录已不可用。', 404)
        recurring = record.get('recurrence') or {}
        return {'event_key': event, 'record_id': row['target_id'], 'identity_id': identity, 'kind': 'record_reminder',
                'series_id': recurring.get('series_id'), 'occurrence_key': recurring.get('occurrence_key')}


def refresh_row(db, row, stamp):
    row = dict(row)
    record, anchor, reason = RecordReminderBook.source(db, row['identity_id'], row['target_id'])
    if row['enabled'] and (reason or anchor != row['anchor_at']):
        RecordReminderBook._cancel(db, row['id'], stamp)
        # Restoring a removed/completed source does not silently opt the user in again.
        row.update(revision=row['revision'] + 1, anchor_at=anchor, enabled=int(not reason), reason=reason,
                   activation=row['activation'] + 1, updated_at=stamp)
        db.execute('UPDATE record_reminders SET revision=?,anchor_at=?,enabled=?,reason=?,activation=?,updated_at=? WHERE id=?',
                   tuple(row[k] for k in ('revision', 'anchor_at', 'enabled', 'reason', 'activation', 'updated_at', 'id')))
    db.execute('UPDATE record_reminders SET checked_at=? WHERE id=?', (stamp, row['id']))
    return row, record, anchor, reason


def refresh_source_reminders(db, identity, *, target_id=None, series_id=None):
    """Inside the source write transaction: rapid complete/reopen cannot lose invalidation."""
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='record_reminders'").fetchone():
        return
    if target_id:
        rows = db.execute('SELECT * FROM record_reminders WHERE identity_id=? AND target_id=? AND enabled=1', (identity, target_id)).fetchall()
    elif series_id:
        prefix = 'recurrence_' + series_id[7:] + '_'
        rows = db.execute('SELECT * FROM record_reminders WHERE identity_id=? AND substr(target_id,1,?)=? AND enabled=1', (identity, len(prefix), prefix)).fetchall()
    else:
        return
    for row in rows:
        refresh_row(db, row, time.time())
