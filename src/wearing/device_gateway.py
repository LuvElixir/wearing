"""Persistent ownership fence for Pajio's known Android entry points.

This is not an OS sandbox or a media transport. Private sessions are disabled
unless a trusted host composition explicitly supplies readiness. No screen,
input text, credentials or media keys are accepted by this module.
"""
from contextlib import contextmanager
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import sqlite3
import time

class GatewayError(PermissionError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,127}', value):
        raise GatewayError('invalid_gateway_identifier')
    return value


@dataclass(frozen=True)
class GatewayScope:
    tenant_id: str
    identity_id: str
    user_id: str
    connector_id: str
    resource_id: str

    def __post_init__(self):
        for value in vars(self).values():
            identifier(value)

    def serialized(self):
        return json.dumps(vars(self), sort_keys=True, separators=(',', ':'))


@dataclass(frozen=True)
class AgentPermit:
    resource_id: str
    epoch: int


def action_lock_path(resource_id):
    return Path.home() / '.wearing/phone-locks' / (identifier(resource_id) + '.lock')


class DeviceGateway:
    def __init__(self, root=None, *, private_access_ready=False, clock=time.time):
        self.root = Path(root) if root is not None else Path.home() / '.wearing/device-gateway'
        if self.root.is_symlink():
            raise GatewayError('unsafe_gateway_directory')
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if os.name != 'nt':
            self.root.chmod(0o700)
        self.path = self.root / 'ownership.sqlite3'
        if self.path.is_symlink():
            raise GatewayError('unsafe_gateway_database')
        self.private_access_ready = private_access_ready is True
        self.clock = clock
        with self.tx() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS ownership(
                resource TEXT PRIMARY KEY, epoch INTEGER NOT NULL, state TEXT NOT NULL,
                scope TEXT, session TEXT, expires REAL, remote_revision INTEGER NOT NULL DEFAULT 0)''')
        if os.name != 'nt':
            self.path.chmod(0o600)

    @contextmanager
    def tx(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            db.execute('PRAGMA synchronous=FULL')
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _row(self, db, resource_id):
        identifier(resource_id)
        db.execute("INSERT OR IGNORE INTO ownership(resource,epoch,state) VALUES (?,0,'agent_ready')", (resource_id,))
        row = db.execute('SELECT * FROM ownership WHERE resource=?', (resource_id,)).fetchone()
        if row['state'] in ('handoff_pending', 'human_private', 'awaiting_scope') and (row['expires'] or 0) <= self.clock():
            db.execute("UPDATE ownership SET state='paused',epoch=epoch+1,expires=NULL WHERE resource=?", (resource_id,))
            row = db.execute('SELECT * FROM ownership WHERE resource=?', (resource_id,)).fetchone()
        return row

    @staticmethod
    def _public(row):
        return {'resource_id': row['resource'], 'epoch': row['epoch'], 'state': row['state'],
                'session_id': row['session'], 'expires_at': row['expires']}

    def snapshot(self, resource_id):
        with self.tx() as db:
            return self._public(self._row(db, resource_id))

    def permit_agent(self, resource_id):
        value = self.snapshot(resource_id)
        if value['state'] != 'agent_ready':
            raise GatewayError('device_private_or_paused')
        return AgentPermit(resource_id, value['epoch'])

    def validate_agent(self, permit):
        if not isinstance(permit, AgentPermit) or self.permit_agent(permit.resource_id) != permit:
            raise GatewayError('device_epoch_changed')

    def _ready(self):
        if not self.private_access_ready:
            raise GatewayError('private_access_unavailable')

    def begin_human(self, scope, session_id, *, expected_epoch, ttl=30):
        self._ready()
        if not isinstance(scope, GatewayScope) or type(expected_epoch) is not int or not 0 < ttl <= 60:
            raise GatewayError('invalid_gateway_request')
        identifier(session_id)
        self.snapshot(scope.resource_id)  # Persist expiry even when this request is rejected.
        with self.tx() as db:
            row = self._row(db, scope.resource_id)
            if row['epoch'] != expected_epoch:
                raise GatewayError('device_epoch_changed')
            if row['state'] not in ('agent_ready', 'paused'):
                raise GatewayError('device_owned_by_another_session')
            db.execute("UPDATE ownership SET epoch=epoch+1,state='handoff_pending',scope=?,session=?,expires=? WHERE resource=?",
                       (scope.serialized(), session_id, self.clock()+ttl, scope.resource_id))
            return self._public(self._row(db, scope.resource_id))

    def _session(self, db, scope, session_id, epoch):
        if not isinstance(scope, GatewayScope) or type(epoch) is not int:
            raise GatewayError('invalid_gateway_request')
        row = self._row(db, scope.resource_id)
        if row['scope'] != scope.serialized() or row['session'] != session_id:
            raise GatewayError('gateway_scope_mismatch')
        if row['epoch'] != epoch:
            raise GatewayError('device_epoch_changed')
        return row

    @contextmanager
    def native_lock(self, resource_id):
        # Same nonblocking OS advisory lock as phone_proxy.DeviceLock. This
        # module also runs in Hermes' separately managed Python, so importing
        # it must not require Pajio's filelock dependency.
        path = action_lock_path(resource_id)
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        try:
            try:
                if os.name == 'nt':
                    import msvcrt
                    if not os.fstat(fd).st_size:
                        os.write(fd, b'\0')
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as error:
                raise GatewayError('device_action_inflight') from error
            yield
        finally:
            # Closing releases the OS lock even if the guarded operation raises.
            # Keep the inode: unlinking permits contenders to lock different files.
            os.close(fd)

    def activate_human(self, scope, session_id, epoch):
        self._ready()
        # Uses exactly the OS lock held by phone_proxy. No private frames before
        # the previous native action has finished and its result is fenced.
        with self.native_lock(scope.resource_id), self.tx() as db:
            row = self._session(db, scope, session_id, epoch)
            if row['state'] not in ('handoff_pending', 'human_private'):
                raise GatewayError('human_session_not_active')
            db.execute("UPDATE ownership SET state='human_private' WHERE resource=?", (scope.resource_id,))
            return self._public(self._row(db, scope.resource_id))

    def validate_human(self, scope, session_id, epoch):
        self._ready()
        self.snapshot(scope.resource_id)
        with self.tx() as db:
            row = self._session(db, scope, session_id, epoch)
            if row['state'] != 'human_private':
                raise GatewayError('human_session_not_active')
            return self._public(row)

    @contextmanager
    def human_guard(self, scope, session_id, epoch):
        with self.native_lock(scope.resource_id):
            self.validate_human(scope, session_id, epoch)
            yield
            self.validate_human(scope, session_id, epoch)

    def renew_human(self, scope, session_id, epoch, *, ttl=30):
        if type(ttl) not in (int, float) or not 0 < ttl <= 60:
            raise GatewayError('invalid_gateway_request')
        self.validate_human(scope, session_id, epoch)
        with self.tx() as db:
            row = self._session(db, scope, session_id, epoch)
            if row['state'] != 'human_private':
                raise GatewayError('human_session_not_active')
            db.execute('UPDATE ownership SET expires=? WHERE resource=?', (self.clock()+ttl, scope.resource_id))
            return self._public(self._row(db, scope.resource_id))

    def pause(self, scope, session_id, epoch):
        self.snapshot(scope.resource_id)
        with self.tx() as db:
            row = self._session(db, scope, session_id, epoch)
            if row['state'] != 'paused':
                db.execute("UPDATE ownership SET epoch=epoch+1,state='paused',expires=NULL WHERE resource=?", (scope.resource_id,))
            return self._public(self._row(db, scope.resource_id))

    def finish_human(self, scope, session_id, epoch, *, safe_screen_confirmed=False,
                     scope_confirmed=False, clear_media=None):
        self._ready()
        # A lost ACK may repeat a completed return. Preserve only non-secret
        # scope/session metadata so that this can be acknowledged safely.
        with self.tx() as db:
            previous = self._row(db, scope.resource_id)
            if previous['scope'] == scope.serialized() and previous['session'] == session_id and previous['state'] == 'agent_ready' and previous['epoch'] == epoch:
                return self._public(previous)
        self.validate_human(scope, session_id, epoch)
        if safe_screen_confirmed is not True or scope_confirmed is not True or not callable(clear_media):
            raise GatewayError('human_return_confirmation_required')
        with self.native_lock(scope.resource_id):
            self.validate_human(scope, session_id, epoch)
            # Trusted media adapter callback, never a client-supplied bool. The
            # agent stays fenced while buffers and the private channel close.
            try:
                cleared = clear_media() is True
            except Exception:
                cleared = False
            if not cleared:
                self.pause(scope, session_id, epoch)
                raise GatewayError('private_media_not_cleared')
            with self.tx() as db:
                row = self._session(db, scope, session_id, epoch)
                if row['state'] != 'human_private':
                    raise GatewayError('human_session_not_active')
                db.execute("UPDATE ownership SET epoch=epoch+1,state='agent_ready',expires=NULL WHERE resource=?", (scope.resource_id,))
                return self._public(self._row(db, scope.resource_id))

    def recover(self, resources):
        """Process restart does not restore a private session or agent ownership."""
        with self.tx() as db:
            for resource in resources:
                identifier(resource)
                db.execute("UPDATE ownership SET epoch=epoch+1,state='paused',expires=NULL WHERE resource=? AND state IN ('handoff_pending','human_private','awaiting_scope')", (resource,))
