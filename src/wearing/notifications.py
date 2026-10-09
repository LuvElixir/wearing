"""Private, durable notification outbox. Provider acceptance is not device delivery.

Only metadata enters Expo payloads. Uncertain sends are retained, never blindly
replayed. Unique events prevent polling/restarts from repeating the same update.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import json
import logging
import math
import os
import re
import time
import uuid

import httpx

from .activity import ActivityBook
from .quiet_hours import DEFAULT as QUIET_DEFAULT, quiet_until, validate_quiet_hours

TOKEN = re.compile(r"^(?:Expo|Exponent)PushToken\[[A-Za-z0-9_-]{10,200}\]$")
INSTALLATION = re.compile(r"^[A-Za-z0-9_-]{16,100}$")
PROJECT = re.compile(r"^[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12}$")
OWNER = re.compile(r"^[a-f0-9]{64}$")
SEND_URL = "https://exp.host/--/api/v2/push/send"
RECEIPT_URL = "https://exp.host/--/api/v2/push/getReceipts"


class NotificationError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class NotificationConfig:
    enabled: bool = False
    project_id: str = ""
    access_token: str = ""

    @classmethod
    def from_env(cls):
        return cls(os.getenv("PAJIO_PUSH_ENABLED") == "1", os.getenv("PAJIO_EXPO_PROJECT_ID", ""),
                   os.getenv("PAJIO_EXPO_ACCESS_TOKEN", ""))

    @property
    def configured(self):
        return self.enabled and bool(PROJECT.fullmatch(self.project_id))


class NotificationService:
    def __init__(self, store, *, config=None, client=None, clock=time.time):
        self.store, self.config, self.clock = store, config or NotificationConfig.from_env(), clock
        self.activity = ActivityBook(store)
        self.client = client or httpx.AsyncClient(timeout=20, follow_redirects=False)
        self.owns_client = client is None
        with store.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS notification_meta (key TEXT PRIMARY KEY,value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS notification_devices (
                  identity_id TEXT NOT NULL, installation_id TEXT NOT NULL, token TEXT NOT NULL,
                  project_id TEXT NOT NULL, platform TEXT NOT NULL, enabled INTEGER NOT NULL,
                  generation INTEGER NOT NULL, updated_at REAL NOT NULL, reason TEXT,
                  PRIMARY KEY(identity_id,installation_id));
                CREATE TABLE IF NOT EXISTS notification_preferences (
                  owner_scope TEXT NOT NULL, identity_id TEXT NOT NULL, installation_id TEXT NOT NULL,
                  enabled INTEGER NOT NULL, start_minute INTEGER NOT NULL,
                  end_minute INTEGER NOT NULL, timezone TEXT NOT NULL, revision INTEGER NOT NULL,
                  PRIMARY KEY(owner_scope,identity_id,installation_id));
                CREATE TABLE IF NOT EXISTS notification_revoked_owners (
                  owner_scope TEXT PRIMARY KEY, revoked_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS notification_events (
                  event_key TEXT PRIMARY KEY, identity_id TEXT NOT NULL, task_id TEXT NOT NULL,
                  kind TEXT NOT NULL, version TEXT NOT NULL, created_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS notification_outbox (
                  event_key TEXT NOT NULL, identity_id TEXT NOT NULL, installation_id TEXT NOT NULL,
                  state TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                  next_at REAL NOT NULL, claimed_at REAL, ticket_id TEXT, token TEXT,
                  generation INTEGER, error_code TEXT, updated_at REAL NOT NULL,
                  PRIMARY KEY(event_key,identity_id,installation_id));
                CREATE INDEX IF NOT EXISTS notification_due ON notification_outbox(state,next_at);
            """)
            db.execute("BEGIN IMMEDIATE")
            if "expires_at" not in {r[1] for r in db.execute("PRAGMA table_info(notification_devices)")}:
                # Old unbounded registrations fail closed until explicit refresh.
                db.execute("ALTER TABLE notification_devices ADD COLUMN expires_at REAL NOT NULL DEFAULT 0")
            for table in ("notification_devices", "notification_outbox"):
                if "owner_scope" not in {r[1] for r in db.execute(f"PRAGMA table_info({table})")}:
                    db.execute(f"ALTER TABLE {table} ADD COLUMN owner_scope TEXT NOT NULL DEFAULT ''")
            if "owner_scope" not in {r[1] for r in db.execute("PRAGMA table_info(notification_preferences)")}:
                # The account which wrote legacy preferences is unknowable. Do
                # not assign them to whichever account happens to sign in next.
                db.execute("ALTER TABLE notification_preferences RENAME TO notification_preferences_legacy_v1")
                db.execute("""CREATE TABLE notification_preferences (
                  owner_scope TEXT NOT NULL, identity_id TEXT NOT NULL, installation_id TEXT NOT NULL,
                  enabled INTEGER NOT NULL, start_minute INTEGER NOT NULL, end_minute INTEGER NOT NULL,
                  timezone TEXT NOT NULL, revision INTEGER NOT NULL,
                  PRIMARY KEY(owner_scope,identity_id,installation_id))""")
            db.execute("UPDATE notification_devices SET enabled=0,reason='owner_unknown' WHERE owner_scope=''")
            db.execute("UPDATE notification_outbox SET state='cancelled',error_code='OwnerUnknown' WHERE owner_scope='' AND state IN ('pending','awaiting_registration','sending')")
            db.execute("INSERT OR IGNORE INTO notification_meta VALUES('server_id',?)", (uuid.uuid4().hex,))
            self.server_id = db.execute("SELECT value FROM notification_meta WHERE key='server_id'").fetchone()[0]
        from .record_reminders import RecordReminderBook
        self.reminders = RecordReminderBook(store, clock=clock)

    @staticmethod
    def _owner(owner_scope):
        if not isinstance(owner_scope, str) or (owner_scope != "local" and not OWNER.fullmatch(owner_scope)):
            raise NotificationError("账户通知关联无效，请重新登录。", 401)
        return owner_scope

    def _owner_allowed(self, db, owner_scope):
        self._owner(owner_scope)
        if db.execute("SELECT 1 FROM notification_revoked_owners WHERE owner_scope=?", (owner_scope,)).fetchone():
            raise NotificationError("此账户的通知授权已撤销。", 403)

    def _expire(self, db):
        stamp = self.clock()
        # Quarantine any pre-upgrade outbox entry that was fanned out to the
        # wrong account. Already handed-off pushes cannot be recalled, but
        # neither queued sends nor resolution may reuse that old authority.
        db.execute("""UPDATE notification_outbox SET state='cancelled',error_code='TaskNotVisible',updated_at=?
          WHERE state IN ('pending','awaiting_registration','sending') AND EXISTS
          (SELECT 1 FROM notification_events e JOIN task_principals p ON p.task_id=e.task_id
           WHERE e.event_key=notification_outbox.event_key AND p.owner_scope!=notification_outbox.owner_scope)""", (stamp,))
        db.execute("UPDATE notification_devices SET enabled=0,reason='expired',updated_at=? WHERE enabled=1 AND expires_at<=?", (stamp, stamp))
        db.execute("""UPDATE notification_outbox SET state='awaiting_registration',error_code='RegistrationExpired',updated_at=? WHERE state='pending' AND EXISTS
          (SELECT 1 FROM notification_devices d WHERE d.identity_id=notification_outbox.identity_id
          AND d.installation_id=notification_outbox.installation_id AND d.owner_scope=notification_outbox.owner_scope
          AND d.enabled=0 AND d.reason='expired')""", (stamp,))

    def _collect(self, db, identity):
        stamp = self.clock()
        silent = self._silent_scheduled(db, identity)
        for task_id in silent:
            # Pre-upgrade entries which have not reached the provider can still
            # be suppressed. Never rewrite an accepted/uncertain send as unsent.
            db.execute("""UPDATE notification_outbox SET state='cancelled',error_code='SilentSchedule',updated_at=?
              WHERE identity_id=? AND state IN ('pending','awaiting_registration') AND event_key IN
              (SELECT event_key FROM notification_events WHERE identity_id=? AND task_id=? AND kind='result')""",
                       (stamp, identity, identity, task_id))
        for item in self.activity._items(db, identity):
            if item['task_id'] in silent:
                continue
            # A user checking/closing a result is not a new agent result.
            kind = ("approval" if item["status"] == "waiting_for_approval" and item["label"] == "等你确认"
                    else "result" if item["status"] in {"completed_unverified", "failed"} else None)
            if not kind:
                continue
            key = hashlib.sha256(f'{identity}:{item["task_id"]}:{kind}:{item["version"]}'.encode()).hexdigest()
            inserted = db.execute("INSERT OR IGNORE INTO notification_events VALUES(?,?,?,?,?,?)",
                                  (key, identity, item["task_id"], kind, item["version"], stamp)).rowcount
            if inserted:
                db.execute("""INSERT OR IGNORE INTO notification_outbox(event_key,identity_id,installation_id,state,next_at,updated_at,owner_scope)
                  SELECT ?,identity_id,installation_id,CASE WHEN enabled=1 THEN 'pending' ELSE 'awaiting_registration' END,?,?,owner_scope
                  FROM notification_devices d WHERE identity_id=? AND owner_scope!='' AND (enabled=1 OR reason='expired')
                  AND NOT EXISTS (SELECT 1 FROM task_principals p WHERE p.task_id=? AND p.owner_scope!=d.owner_scope)""",
                           (key, stamp, stamp, identity, item["task_id"]))

    @staticmethod
    def _silent_scheduled(db, identity, task_id=None):
        """A model token is silent only for its trusted scheduler occurrence.

        Inspect the terminal task output, not the asynchronously reconciled
        occurrence status, so collector/reconciler ordering cannot cause a push.
        Both identity and inherited account ownership must match the schedule.
        """
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {'schedule_occurrences', 'personal_schedules', 'task_principals', 'background_principals'} <= tables:
            return set()
        rows = db.execute("""SELECT DISTINCT t.id,t.output FROM tasks t
          JOIN schedule_occurrences o ON o.task_id=t.id
          JOIN personal_schedules s ON s.id=o.schedule_id AND s.identity_id=t.identity_id
          LEFT JOIN task_principals tp ON tp.task_id=t.id
          LEFT JOIN background_principals bp ON bp.kind='schedule' AND bp.source_id=s.id
          WHERE t.identity_id=? AND t.status IN ('completed_unverified','verified')
          AND tp.owner_scope IS bp.owner_scope AND (? IS NULL OR t.id=?)""",
                          (identity, task_id, task_id)).fetchall()
        return {row['id'] for row in rows if (row['output'] or '').strip() == '[SILENT]'}

    def collect(self):
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._expire(db)
            for row in db.execute("SELECT id FROM identities").fetchall():
                self._collect(db, row[0])
            self.reminders.collect(db)

    def status(self, identity, installation, *, owner_scope="local"):
        self.store.identity(identity)
        if not INSTALLATION.fullmatch(installation):
            raise NotificationError("通知设备标识无效。")
        with self.store.connection() as db:
            self._owner_allowed(db, owner_scope)
            self._expire(db)
            row = db.execute("SELECT enabled,reason,expires_at FROM notification_devices WHERE identity_id=? AND installation_id=? AND owner_scope=?", (identity, installation, owner_scope)).fetchone()
            counts = dict(db.execute("SELECT state,count(*) FROM notification_outbox WHERE identity_id=? AND installation_id=? AND owner_scope=? GROUP BY state", (identity, installation, owner_scope)))
            latest = db.execute("SELECT state,error_code FROM notification_outbox WHERE identity_id=? AND installation_id=? AND owner_scope=? ORDER BY updated_at DESC LIMIT 1", (identity, installation, owner_scope)).fetchone()
        return {"identity_id": identity, "installation_id": installation, "server_id": self.server_id,
                "configured": self.config.configured, "project_id": self.config.project_id if PROJECT.fullmatch(self.config.project_id) else None,
                "enabled": bool(row and row["enabled"]), "reason": row["reason"] if row else None,
                "expires_at": row["expires_at"] if row else None,
                "provider_status": latest["state"] if latest else "unverified", "provider_error": latest["error_code"] if latest else None,
                "counts": counts}

    def _preferences(self, db, identity, installation, owner_scope="local"):
        row = db.execute("SELECT enabled,start_minute,end_minute,timezone,revision FROM notification_preferences WHERE identity_id=? AND installation_id=? AND owner_scope=?", (identity, installation, owner_scope)).fetchone()
        return {**dict(row), "enabled": bool(row["enabled"])} if row else dict(QUIET_DEFAULT)

    def preferences(self, identity, installation, *, owner_scope="local"):
        self.store.identity(identity)
        if not INSTALLATION.fullmatch(installation):
            raise NotificationError("通知设备标识无效。")
        with self.store.connection() as db:
            self._owner_allowed(db, owner_scope)
            return {"identity_id": identity, "installation_id": installation, **self._preferences(db, identity, installation, owner_scope)}

    def update_preferences(self, identity, installation, revision, enabled, start_minute, end_minute, timezone, *, owner_scope="local"):
        self.preferences(identity, installation, owner_scope=owner_scope)
        try:
            validate_quiet_hours(enabled, start_minute, end_minute, timezone)
        except ValueError as error:
            raise NotificationError(str(error)) from error
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._owner_allowed(db, owner_scope)
            current = self._preferences(db, identity, installation, owner_scope)
            if type(revision) is not int or revision != current["revision"]:
                raise NotificationError("通知时段已在别处修改，请重新读取后核对。", 409)
            db.execute("""INSERT INTO notification_preferences VALUES(?,?,?,?,?,?,?,?)
              ON CONFLICT(owner_scope,identity_id,installation_id) DO UPDATE SET enabled=excluded.enabled,
              start_minute=excluded.start_minute,end_minute=excluded.end_minute,
              timezone=excluded.timezone,revision=excluded.revision""",
              (owner_scope, identity, installation, int(enabled), start_minute, end_minute, timezone, revision + 1))
            # Re-evaluate quiet-held messages promptly when the window changes;
            # never reset provider backoff or uncertain/in-flight deliveries.
            db.execute("UPDATE notification_outbox SET next_at=?,error_code=NULL WHERE identity_id=? AND installation_id=? AND owner_scope=? AND state='pending' AND error_code='QuietHours'",
                       (self.clock(), identity, installation, owner_scope))
            return {"identity_id": identity, "installation_id": installation, **self._preferences(db, identity, installation, owner_scope)}

    def register(self, identity, installation, token, project_id, platform, session_expires=None, *, owner_scope="local"):
        self.store.identity(identity)
        if not INSTALLATION.fullmatch(installation) or not TOKEN.fullmatch(token) or platform not in {"ios", "android"}:
            raise NotificationError("通知登记信息无效。")
        if not self.config.configured or project_id != self.config.project_id:
            raise NotificationError("推送服务尚未配置，或 App 的推送项目与服务不一致。", 409)
        self._owner(owner_scope)
        if owner_scope != "local" and session_expires is None:
            # Keep this invariant in the service as well as the HTTP adapter:
            # an internal caller must not accidentally grant a cloud account
            # the longer, unauthenticated local-installation lease.
            raise NotificationError("登录关联尚未通过验证，请重新登录后开启通知。", 401)
        stamp = self.clock()
        expiry = stamp + 7 * 86400
        if session_expires is not None:
            if type(session_expires) not in {int, float} or not math.isfinite(session_expires) or session_expires <= stamp:
                raise NotificationError("登录已到期，请重新登录后开启通知。", 401)
            expiry = min(expiry, session_expires)
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._owner_allowed(db, owner_scope)
            self._expire(db)
            # One physical installation can belong to only the currently
            # authenticated owner. A new owner never inherits an old queue.
            db.execute("""UPDATE notification_devices SET enabled=0,reason='owner_changed',
              generation=generation+1,updated_at=? WHERE installation_id=? AND owner_scope!=? AND reason IS NOT 'owner_changed'""",
                       (stamp, installation, owner_scope))
            db.execute("""UPDATE notification_outbox SET state='cancelled',error_code='OwnerChanged',updated_at=?
              WHERE installation_id=? AND owner_scope!=? AND state IN ('pending','awaiting_registration','sending')""",
                       (stamp, installation, owner_scope))
            # Establish a baseline BEFORE enabling a new installation. Historical
            # tasks do not all arrive as a burst when a user first opts in.
            self._collect(db, identity)
            self.reminders.collect(db)
            db.execute("""INSERT INTO notification_devices(identity_id,installation_id,token,project_id,platform,enabled,generation,updated_at,reason,expires_at,owner_scope)
              VALUES(?,?,?,?,?,1,1,?,NULL,?,?)
              ON CONFLICT(identity_id,installation_id) DO UPDATE SET token=excluded.token,
              project_id=excluded.project_id,platform=excluded.platform,enabled=1,reason=NULL,
              generation=notification_devices.generation+1,owner_scope=excluded.owner_scope,
              updated_at=excluded.updated_at,expires_at=excluded.expires_at""", (identity, installation, token, project_id, platform, stamp, expiry, owner_scope))
            # Only expired, explicitly opted-in work is recoverable. Disabled,
            # revoked, old-owner and uncertain sends stay terminal.
            db.execute("""UPDATE notification_outbox SET state='pending',next_at=?,error_code=NULL,updated_at=?
              WHERE identity_id=? AND installation_id=? AND owner_scope=? AND state='awaiting_registration'""",
                       (stamp, stamp, identity, installation, owner_scope))
        return self.status(identity, installation, owner_scope=owner_scope)

    def disable(self, identity, installation, *, owner_scope="local"):
        self.status(identity, installation, owner_scope=owner_scope)
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._owner_allowed(db, owner_scope)
            db.execute("UPDATE notification_devices SET enabled=0,reason='disabled',generation=generation+1,updated_at=? WHERE identity_id=? AND installation_id=? AND owner_scope=? AND reason IS NOT 'disabled'", (self.clock(), identity, installation, owner_scope))
            db.execute("UPDATE notification_outbox SET state='cancelled',updated_at=? WHERE identity_id=? AND installation_id=? AND owner_scope=? AND state IN ('pending','awaiting_registration','sending')", (self.clock(), identity, installation, owner_scope))
        return self.status(identity, installation, owner_scope=owner_scope)

    def disable_installation(self, identity, installation, *, owner_scope="local"):
        """Logout stops this installation across this tenant's identities."""
        self.status(identity, installation, owner_scope=owner_scope)
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._owner_allowed(db, owner_scope)
            db.execute("UPDATE notification_devices SET enabled=0,reason='disabled',generation=generation+1,updated_at=? WHERE installation_id=? AND owner_scope=? AND reason IS NOT 'disabled'", (self.clock(), installation, owner_scope))
            db.execute("UPDATE notification_outbox SET state='cancelled',updated_at=? WHERE installation_id=? AND owner_scope=? AND state IN ('pending','awaiting_registration','sending')", (self.clock(), installation, owner_scope))
        return self.status(identity, installation, owner_scope=owner_scope)

    def revoke_owner_scope(self, owner_scope):
        """Idempotent operator hook. Never accepts an App-supplied scope."""
        if not isinstance(owner_scope, str) or not OWNER.fullmatch(owner_scope):
            raise NotificationError("账户通知关联无效。", 400)
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            stamp = self.clock()
            db.execute("INSERT OR IGNORE INTO notification_revoked_owners VALUES(?,?)", (owner_scope, stamp))
            disabled = db.execute("""UPDATE notification_devices SET enabled=0,reason='owner_revoked',generation=generation+1,updated_at=?
              WHERE owner_scope=? AND reason IS NOT 'owner_revoked'""", (stamp, owner_scope)).rowcount
            cancelled = db.execute("""UPDATE notification_outbox SET state='cancelled',error_code='OwnerRevoked',updated_at=?
              WHERE owner_scope=? AND state IN ('pending','awaiting_registration','sending')""", (stamp, owner_scope)).rowcount
            return {"disabled": disabled, "pending_cancelled": cancelled}

    def resolve(self, identity, event_key, *, owner_scope="local"):
        self.store.identity(identity)
        with self.store.connection() as db:
            self._owner_allowed(db, owner_scope)
            event = db.execute("SELECT kind FROM notification_events WHERE event_key=? AND identity_id=?", (event_key, identity)).fetchone()
            if event and event['kind'] == 'record_reminder':
                from .record_reminders import ReminderError
                try:
                    return {**self.reminders.resolve(db, identity, event_key, owner_scope), 'server_id': self.server_id}
                except ReminderError as error:
                    raise NotificationError(str(error), error.status) from error
            row = db.execute("""SELECT e.event_key,e.task_id,e.identity_id,e.kind FROM notification_events e
              JOIN tasks t ON t.id=e.task_id AND t.identity_id=e.identity_id
              WHERE e.event_key=? AND e.identity_id=? AND NOT EXISTS
              (SELECT 1 FROM task_principals p WHERE p.task_id=e.task_id AND p.owner_scope!=?) AND EXISTS
              (SELECT 1 FROM notification_outbox o WHERE o.event_key=e.event_key AND o.owner_scope=?)""", (event_key, identity, owner_scope, owner_scope)).fetchone()
        if not row:
            raise NotificationError("这条通知不属于当前身份，或任务已不存在。", 404)
        return {**dict(row), "server_id": self.server_id}

    def _finish(self, row, state, *, code=None, ticket=None, delay=0):
        stamp = self.clock()
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if state == "pending":
                device = db.execute("SELECT enabled,reason FROM notification_devices WHERE identity_id=? AND installation_id=? AND owner_scope=? AND token=? AND generation=?",
                                    (row["identity_id"], row["installation_id"], row["owner_scope"], row["token"], row["generation"])).fetchone()
                if not device or not device["enabled"]:
                    state = "awaiting_registration" if device and device["reason"] == "expired" else "cancelled"
            updated = db.execute("""UPDATE notification_outbox SET state=?,error_code=?,ticket_id=coalesce(?,ticket_id),next_at=?,updated_at=?
              WHERE event_key=? AND identity_id=? AND installation_id=? AND state=? AND attempts=?
              AND token=? AND coalesce(ticket_id,'')=? AND owner_scope=? AND generation=?""", (state, code, ticket, stamp + delay, stamp, row["event_key"], row["identity_id"], row["installation_id"], row["state"], row["attempts"], row["token"], row.get("ticket_id") or "", row["owner_scope"], row["generation"])).rowcount
            if updated and code == "DeviceNotRegistered":
                # A late receipt cannot revoke a newer registration, even when
                # the physical device token happens to be unchanged.
                db.execute("UPDATE notification_devices SET enabled=0,reason=?,generation=generation+1,updated_at=? WHERE identity_id=? AND installation_id=? AND token=? AND owner_scope=? AND generation=?",
                           (code, stamp, row["identity_id"], row["installation_id"], row["token"], row["owner_scope"], row["generation"]))
                db.execute("""UPDATE notification_outbox SET state='cancelled',updated_at=? WHERE state IN ('pending','awaiting_registration') AND EXISTS
                  (SELECT 1 FROM notification_devices d WHERE d.identity_id=notification_outbox.identity_id
                   AND d.installation_id=notification_outbox.installation_id AND d.owner_scope=notification_outbox.owner_scope
                   AND d.enabled=0 AND d.reason='DeviceNotRegistered')""", (stamp,))

    def _claim(self):
        stamp = self.clock()
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._expire(db)
            # The process may have died after Expo accepted the request. There is
            # no provider idempotency API, so replay would risk duplicate alerts.
            db.execute("UPDATE notification_outbox SET state='unknown',error_code='InterruptedSend',updated_at=? WHERE state='sending' AND claimed_at<?", (stamp, stamp - 120))
            for _ in range(100):
                row = db.execute("""SELECT o.*,d.token AS current_token,d.generation AS current_generation,e.kind,e.task_id
                  FROM notification_outbox o JOIN notification_devices d USING(identity_id,installation_id)
                  JOIN notification_events e USING(event_key) WHERE o.state='pending' AND o.next_at<=? AND d.enabled=1
                  AND o.owner_scope=d.owner_scope AND o.owner_scope!=''
                  AND d.project_id=? ORDER BY o.next_at LIMIT 1""", (stamp, self.config.project_id)).fetchone()
                if not row:
                    return None
                row = dict(row)
                if row['kind'] == 'record_reminder':
                    valid = self.reminders.current_event(db, row['event_key'], row['identity_id'], row['task_id'], row['owner_scope'])
                    if valid:
                        from .record_reminders import WINDOW
                        row['reminder_expires'] = db.execute('SELECT anchor_at FROM record_reminder_events WHERE event_key=?', (row['event_key'],)).fetchone()[0] + WINDOW
                else:
                    current = next((item for item in self.activity._items(db, row["identity_id"], owner_scope=row["owner_scope"])
                                    if item["task_id"] == row["task_id"]), None)
                    event = db.execute("SELECT version FROM notification_events WHERE event_key=?", (row["event_key"],)).fetchone()
                    valid = bool(current and current["version"] == event[0])
                    if row['task_id'] in self._silent_scheduled(db, row['identity_id'], row['task_id']):
                        valid = False
                if not valid:
                    db.execute("UPDATE notification_outbox SET state='cancelled',error_code='Superseded',updated_at=? WHERE event_key=? AND identity_id=? AND installation_id=?",
                               (stamp, row["event_key"], row["identity_id"], row["installation_id"]))
                    continue
                deferred = quiet_until(self._preferences(db, row["identity_id"], row["installation_id"], row["owner_scope"]), stamp)
                if deferred is not None:
                    db.execute("UPDATE notification_outbox SET next_at=?,error_code='QuietHours',updated_at=? WHERE event_key=? AND identity_id=? AND installation_id=?",
                               (deferred, stamp, row["event_key"], row["identity_id"], row["installation_id"]))
                    continue
                row["token"], row["generation"] = row.pop("current_token"), row.pop("current_generation")
                row["attempts"] += 1
                row["state"] = "sending"
                db.execute("""UPDATE notification_outbox SET state='sending',claimed_at=?,attempts=?,token=?,generation=?,updated_at=?
                  WHERE event_key=? AND identity_id=? AND installation_id=?""", (stamp, row["attempts"], row["token"], row["generation"], stamp, row["event_key"], row["identity_id"], row["installation_id"]))
                return row

    def _delivery_authorized(self, row):
        """Final handoff fence. Already handed-off provider requests cannot be recalled."""
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._expire(db)
            pending = db.execute("""SELECT 1 FROM notification_outbox WHERE event_key=? AND identity_id=?
              AND installation_id=? AND owner_scope=? AND state='sending' AND attempts=? AND token=? AND generation=?""",
              (row["event_key"], row["identity_id"], row["installation_id"], row["owner_scope"], row["attempts"], row["token"], row["generation"])).fetchone()
            if not pending:
                return False
            if row['kind'] != 'record_reminder' and row['task_id'] in self._silent_scheduled(db, row['identity_id'], row['task_id']):
                db.execute("""UPDATE notification_outbox SET state='cancelled',error_code='SilentSchedule',updated_at=?
                  WHERE event_key=? AND identity_id=? AND installation_id=? AND owner_scope=? AND state='sending'""",
                           (self.clock(), row['event_key'], row['identity_id'], row['installation_id'], row['owner_scope']))
                return False
            visible = (self.reminders.current_event(db, row['event_key'], row['identity_id'], row['task_id'], row['owner_scope'])
                       if row['kind'] == 'record_reminder' else db.execute("""SELECT 1 FROM tasks t LEFT JOIN task_principals p ON p.task_id=t.id
              WHERE t.id=? AND t.identity_id=? AND (p.task_id IS NULL OR p.owner_scope=?)""",
                                 (row["task_id"], row["identity_id"], row["owner_scope"])).fetchone())
            if not visible:
                db.execute("""UPDATE notification_outbox SET state='cancelled',error_code='TaskNotVisible',updated_at=?
                  WHERE event_key=? AND identity_id=? AND installation_id=? AND owner_scope=? AND state='sending'""",
                           (self.clock(), row["event_key"], row["identity_id"], row["installation_id"], row["owner_scope"]))
                return False
            device = db.execute("SELECT * FROM notification_devices WHERE identity_id=? AND installation_id=?",
                                (row["identity_id"], row["installation_id"])).fetchone()
            same_owner = device and device["owner_scope"] == row["owner_scope"]
            if same_owner and device["enabled"] and device["token"] == row["token"] and device["generation"] == row["generation"]:
                return True
            state = ("awaiting_registration" if same_owner and device["reason"] == "expired" else
                     "pending" if same_owner and device["enabled"] else "cancelled")
            db.execute("UPDATE notification_outbox SET state=?,error_code='RegistrationChanged',next_at=?,updated_at=? WHERE event_key=? AND identity_id=? AND installation_id=? AND owner_scope=?",
                       (state, self.clock(), self.clock(), row["event_key"], row["identity_id"], row["installation_id"], row["owner_scope"]))
            return False

    @property
    def headers(self):
        return {"Content-Type": "application/json", **({"Authorization": "Bearer " + self.config.access_token} if self.config.access_token else {})}

    def _provider_error(self, row, value):
        code = value.get("details", {}).get("error") if isinstance(value.get("details"), dict) else None
        code = code if code in {"DeviceNotRegistered", "MessageTooBig", "MessageRateExceeded", "MismatchSenderId", "InvalidCredentials"} else "ProviderRejected"
        if code == "MessageRateExceeded" and row["attempts"] < 5:
            self._finish(row, "pending", code=code, delay=min(3600, 30 * 2 ** row["attempts"]))
        else:
            self._finish(row, "failed", code=code)

    async def send_one(self):
        if not self.config.configured:
            return False
        row = self._claim()
        if not row:
            return False
        if not self._delivery_authorized(row):
            return True
        body = "有一步需要你确认，打开 Pajio 查看。" if row["kind"] == "approval" else "你交代的事有新进展，打开 Pajio 查看。"
        is_record = row['kind'] == 'record_reminder'
        if is_record:
            body = '有一项日程或待办到了提醒时间，打开 Pajio 查看。'
        payload = {"to": row["token"], "title": "Pajio", "body": body, "channelId": "pajio-progress", "ttl": 3600,
                   "collapseId": row["event_key"], "tag": row["event_key"],
                   "data": {"v": 1, "type": "pajio.record" if is_record else "pajio.task", "server_id": self.server_id, "event_key": row["event_key"], "record_id" if is_record else "task_id": row["task_id"], "identity_id": row["identity_id"]}}
        if is_record:
            payload['ttl'] = max(1, min(3600, int(row['reminder_expires'] - self.clock())))
        try:
            response = await self.client.post(SEND_URL, json=payload, headers=self.headers)
            if response.status_code == 429:
                self._finish(row, "pending" if row["attempts"] < 5 else "failed", code="RateLimited", delay=30 * 2 ** row["attempts"])
            elif 400 <= response.status_code < 500:
                self._finish(row, "failed", code="InvalidCredentials" if response.status_code in {401, 403} else "ProviderRejected")
            elif response.status_code != 200:
                self._finish(row, "unknown", code="ProviderUnavailable")
            else:
                value = response.json().get("data")
                if isinstance(value, list) and len(value) == 1:
                    value = value[0]
                if isinstance(value, dict) and value.get("status") == "ok" and isinstance(value.get("id"), str) and 1 <= len(value["id"]) <= 200:
                    self._finish(row, "ticket", ticket=value["id"], delay=900)
                elif isinstance(value, dict) and value.get("status") == "error":
                    self._provider_error(row, value)
                else:
                    self._finish(row, "unknown", code="MalformedTicket")
        except httpx.ConnectError:
            self._finish(row, "pending" if row["attempts"] < 5 else "failed", code="ConnectionFailed", delay=30 * 2 ** row["attempts"])
        except (httpx.HTTPError, ValueError, TypeError, AttributeError):
            self._finish(row, "unknown", code="UncertainSend")
        return True

    async def receipts(self):
        if not self.config.configured:
            return
        stamp = self.clock()
        with self.store.connection() as db:
            rows = [dict(r) for r in db.execute("SELECT * FROM notification_outbox WHERE state='ticket' AND next_at<=? LIMIT 100", (stamp,))]
        if not rows:
            return
        try:
            response = await self.client.post(RECEIPT_URL, json={"ids": [r["ticket_id"] for r in rows]}, headers=self.headers)
            response.raise_for_status()
            values = response.json()["data"]
            if not isinstance(values, dict):
                raise ValueError()
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            values = {}
        for row in rows:
            value = values.get(row["ticket_id"])
            if isinstance(value, dict) and value.get("status") == "ok":
                self._finish(row, "provider_accepted")
            elif isinstance(value, dict) and value.get("status") == "error":
                self._provider_error(row, value)
            elif stamp - row["claimed_at"] >= 24 * 3600:
                self._finish(row, "unknown", code="ReceiptUnavailable")
            else:
                self._finish(row, "ticket", delay=300)

    async def tick(self):
        self.collect()
        if self.config.configured:
            await self.receipts()
            for _ in range(20):
                if not await self.send_one():
                    break

    async def run(self, stop: asyncio.Event):
        """Run once per tenant Store in app lifespan; stop before closing Store."""
        while not stop.is_set():
            try:
                await self.tick()
            except Exception:
                # Keep the durable queue and retry the worker, never leak tokens.
                logging.getLogger(__name__).warning("Notification worker iteration failed; durable queue retained")
            try:
                await asyncio.wait_for(stop.wait(), timeout=5)
            except TimeoutError:
                pass

    async def close(self):
        if self.owns_client:
            await self.client.aclose()
