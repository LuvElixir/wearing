"""Fixed internal operator freeze/revoke/drain endpoint for an exclusive tenant.

No path, SQL, shell command or resource list is accepted. A separately enrolled
operator key is required. Durable tombstones deny ordinary ingress and restart;
uncertain device writes and unsupported provider revocation remain waiting.
"""
import asyncio
from contextlib import suppress
import json
import os
import re
import secrets
import uuid
from urllib.parse import parse_qs

from starlette.responses import JSONResponse

from ..account_deletion import DeletionError, digest, encoded
from ..service import ACTIVE, TaskError
from ..store import now
from .instance import read_private

PATH = '/internal/account-deletion'
PHASES = ('freeze_tenant', 'revoke_credentials', 'revoke_devices', 'drain_actions')
FIELDS = {'job_id', 'plan_revision', 'operation_id', 'tenant_id', 'instance_id', 'phase', 'owner_scope'}


def tombstoned(root):
    p = root / 'deletion-tombstone.json'
    return p.exists() or p.is_symlink()


def durable_json(path, value):
    # Fixed operator-owned path; no symlink traversal, fsync before rename.
    if path.is_symlink(): raise DeletionError('unsafe_storage')
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.new')
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'w') as f:
            f.write(encoded(value)); f.flush(); os.fsync(f.fileno())
        os.replace(temp, path)
        parent = os.open(path.parent, os.O_RDONLY)
        try: os.fsync(parent)
        finally: os.close(parent)
    finally:
        with suppress(FileNotFoundError): temp.unlink()


class TenantDeletionControl:
    def __init__(self, root, instance, app):
        self.root, self.instance, self.app = root, instance, app
        self.lock, self.active = asyncio.Lock(), set()
        self.marker = root / 'deletion-tombstone.json'
        self.receipts = root / 'deletion-receipts.json'
        if tombstoned(root): self._fence_service()

    def authenticated(self, headers):
        values = [v for k, v in headers if k.lower() == b'authorization']
        try: key = read_private(self.root / 'deletion-operator.key').strip()
        except (OSError, ValueError): return False
        return bool(re.fullmatch(r'[A-Za-z0-9_-]{64}', key) and len(values) == 1 and secrets.compare_digest(values[0], ('Bearer '+key).encode()))

    def _request(self, v):
        if not isinstance(v, dict) or set(v) != FIELDS or v['phase'] not in PHASES: raise DeletionError('adapter_mismatch')
        for k, length in [('job_id', 32), ('plan_revision', 64), ('operation_id', 64), ('owner_scope', 64)]:
            if not isinstance(v[k], str) or not re.fullmatch('[a-f0-9]{'+str(length)+'}', v[k]): raise DeletionError('adapter_mismatch')
        if v['tenant_id'] != self.instance.tenant_id or v['instance_id'] != self.instance.instance_id: raise DeletionError('ownership_changed')
        return v

    def _saved(self):
        if not self.receipts.exists(): return {}
        return json.loads(read_private(self.receipts))

    def _bound(self, v):
        scope = {k: v[k] for k in ('job_id', 'plan_revision', 'tenant_id', 'instance_id', 'owner_scope')}
        if tombstoned(self.root):
            saved = json.loads(read_private(self.marker))
            if saved['scope'] != scope: raise DeletionError('ownership_changed')
        elif v['phase'] == 'freeze_tenant':
            durable_json(self.marker, {'schema': 1, 'scope': scope, 'inflight_review': bool(self.active)})
        else: raise DeletionError('adapter_mismatch')
        return scope

    def _fence_service(self):
        state = self.app.state
        def deny_start(task):
            raise TaskError('账户正在注销，不能开始新的运行。')
        state.service.start_guard = deny_start
        async def existing_client(identity):
            if identity == 'daily': return state.service.hermes
            client = state.identity_clients.get(identity)
            engine = state.identity_runtimes.get(identity)
            if client and engine and engine.status()['running']: return client
            raise TaskError('冻结后不能启动引擎来核对旧运行。')
        state.service.client_resolver = existing_client
        from .relay import RelayStore
        state.service.desktop_relay = lambda: RelayStore(self.root / 'data/device-relay', self.instance.tenant_id)
    async def _freeze(self):
        state = self.app.state
        self._fence_service()
        # Cancel and await ingress before shutting down schedulers. Cancellation
        # does not prove external side effects were reversed; marker records that.
        current = asyncio.current_task()
        pending = [t for t in self.active if t is not current and not t.done()]
        for t in pending: t.cancel()
        if pending:
            done, still_pending = await asyncio.wait(pending, timeout=5)
            for task in done:
                with suppress(asyncio.CancelledError, Exception): task.result()
            if still_pending: raise DeletionError('instance_busy')
        for name in ('recovery_task', 'notification_task', 'health_task', 'files_task', 'phone_task', 'computer_task'):
            task = getattr(state, name, None)
            if task and not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError): await task
        with state.store.connection() as db:
            db.execute('UPDATE messaging_connections SET enabled=0')
        await state.messaging.close()
        await state.capture_worker.close()
        self._devices()
        return {'ingress_frozen': True, 'background_workers_stopped': True, 'tombstone': digest(json.loads(read_private(self.marker)))}

    async def _credentials(self):
        state = self.app.state
        with state.store.connection() as db:
            rows = [(r[0], json.loads(r[1])) for r in db.execute('SELECT identity_id,payload FROM cloud_app_connections')]
        for identity, row in rows:
            await state.cloud_apps.disconnect(identity, row['revision'])
        with state.store.connection() as db:
            pending = db.execute('SELECT COUNT(*) FROM cloud_app_connections').fetchone()[0]
            bots = db.execute('SELECT COUNT(*) FROM messaging_connections').fetchone()[0]
        if pending: raise DeletionError('provider_unavailable')
        # Local disconnect cannot revoke Telegram/Feishu bot credentials upstream;
        # leave disabled records intact for a future genuine revoke adapter.
        if bots: raise DeletionError('adapter_unconfigured')
        return {'cloud_grants_remaining': 0, 'messaging_credentials_remaining': 0}

    def _devices(self):
        state = self.app.state
        with state.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            rows = list(db.execute('SELECT identity,installation FROM native_devices'))
            for row in rows: state.native_actions._invalidate(db, row['identity'], row['installation'])
            db.execute('UPDATE native_devices SET enabled=0,connection=NULL,expires=NULL,epoch=epoch+1')
            db.execute("UPDATE notification_devices SET enabled=0,reason='account_deleted',generation=generation+1")
            db.execute("UPDATE notification_outbox SET state='cancelled' WHERE state IN ('pending','awaiting_registration','sending')")
        # The connector transport is a separate process but shares this fixed root.
        from .relay import RelayStore
        relay = RelayStore(self.root / 'data/device-relay', self.instance.tenant_id)
        with relay.tx() as db:
            ids = [r[0] for r in db.execute('SELECT id FROM connectors')]
        for connector in ids: relay.revoke(connector)
        with state.store.connection() as db:
            enabled = db.execute('SELECT COUNT(*) FROM native_devices WHERE enabled=1').fetchone()[0]
            push = db.execute('SELECT COUNT(*) FROM notification_devices WHERE enabled=1').fetchone()[0]
        with relay.tx() as db:
            remote = db.execute('SELECT COUNT(*) FROM connectors WHERE revoked=0').fetchone()[0]
        if enabled or push or remote: raise DeletionError('instance_busy')
        return {'native_enabled': 0, 'push_enabled': 0, 'remote_enabled': 0}

    async def _drain(self):
        state = self.app.state
        # Queued messages are draft rows with durable handoff consent; withdraw
        # only those never admitted. A missing run_id after reserve_start is NOT
        # proof of non-execution (the Hermes response may have been lost).
        for queued in state.store.queued_messages():
            with suppress(TaskError): await state.service.cancel_message(queued['task_id'])
        async with state.service.lock:
            with state.store.connection() as db:
                db.execute('BEGIN IMMEDIATE')
                db.execute("UPDATE tasks SET status='stopped',updated_at=? WHERE status='starting' AND run_id IS NULL AND idempotency_key IS NULL AND payload IS NULL AND attempt=0", (now(),))
        for task in state.store.list():
            if task['status'] in ACTIVE and task.get('run_id'):
                # The ordinary recovery poll is intentionally stopped. Explicit
                # readback here is the only way an acknowledged stop can drain.
                with suppress(Exception): task = await state.service.refresh(task['id'])
                if task['status'] in {'starting', 'running', 'waiting_for_approval'}:
                    with suppress(Exception): await state.service.stop(task['id'])
                with suppress(Exception): task = await state.service.refresh(task['id'])
            if task['status'] in ACTIVE: raise DeletionError('instance_busy')
        for runtime in [state.runtime, *state.identity_runtimes.values()]:
            await runtime.close()
            if runtime.status()['running']: raise DeletionError('instance_busy')
        if state.capture_worker.process_busy or self.active: raise DeletionError('instance_busy')
        with state.store.connection() as db:
            unresolved = db.execute("SELECT COUNT(*) FROM native_commands WHERE state IN ('queued','executing') OR (state='unknown' AND reviewed=0)").fetchone()[0]
        from .relay import RelayStore
        relay = RelayStore(self.root / 'data/device-relay', self.instance.tenant_id)
        with relay.tx() as db:
            unresolved += db.execute("SELECT COUNT(*) FROM commands WHERE state IN ('queued','executing') OR (state='unknown' AND resolved=0)").fetchone()[0]
        if unresolved or json.loads(read_private(self.marker))['inflight_review']: raise DeletionError('instance_busy')
        return {'active_tasks': 0, 'unresolved_device_actions': 0, 'owned_engines_running': 0, 'active_requests': 0}

    async def execute(self, v):
        v = self._request(v)
        async with self.lock:
            self._bound(v)
            saved = self._saved()
            prior = saved.get(v['operation_id'])
            if prior and prior['request'] != v: raise DeletionError('adapter_mismatch')
            for phase in PHASES[:PHASES.index(v['phase'])]:
                if not any(r['request']['phase'] == phase and r['state'] == 'done' for r in saved.values()): raise DeletionError('adapter_mismatch')
            try:
                if v['phase'] == 'freeze_tenant': proof = await self._freeze()
                elif v['phase'] == 'revoke_credentials': proof = await self._credentials()
                elif v['phase'] == 'revoke_devices': proof = self._devices()
                else: proof = await self._drain()
                receipt = {'request': v, 'state': 'done', 'evidence': digest(proof)}
            except DeletionError as error:
                receipt = {'request': v, 'state': 'waiting', 'code': error.code}
            saved[v['operation_id']] = receipt
            durable_json(self.receipts, saved)
            return receipt

    async def endpoint(self, scope, receive, send):
        if not self.authenticated(scope.get('headers', [])):
            return await JSONResponse({'error': 'operator_required'}, status_code=401)(scope, receive, send)
        try:
            if scope['method'] == 'GET':
                query = parse_qs(scope.get('query_string', b'').decode(), strict_parsing=True)
                if set(query) != {'job_id', 'plan_revision', 'phase', 'operation_id'} or any(len(v) != 1 for v in query.values()): raise ValueError()
                query = {k: v[0] for k, v in query.items()}
                value = self._saved().get(query['operation_id'])
                if not value or any(value['request'][k] != v for k, v in query.items()): raise DeletionError('job_not_found', 404)
            elif scope['method'] == 'POST':
                body = b''
                while True:
                    event = await receive()
                    if event['type'] != 'http.request': raise ValueError()
                    body += event.get('body', b'')
                    if len(body) > 4096: raise ValueError()
                    if not event.get('more_body'): break
                value = await self.execute(json.loads(body))
            else: raise DeletionError('method_not_allowed', 405)
            response = JSONResponse(value, headers={'Cache-Control': 'no-store'})
        except DeletionError as error:
            response = JSONResponse({'error': error.code}, status_code=error.status)
        except Exception:
            response = JSONResponse({'error': 'operator_request_failed'}, status_code=409)
        await response(scope, receive, send)


class DeletionBoundary:
    def __init__(self, app, controller): self.app, self.controller = app, controller

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'lifespan': return await self.app(scope, receive, send)
        if scope['type'] == 'http' and scope.get('path') == PATH:
            return await self.controller.endpoint(scope, receive, send)
        if tombstoned(self.controller.root):
            if scope['type'] == 'websocket': return await send({'type': 'websocket.close', 'code': 1008})
            return await JSONResponse({'error': 'account_frozen'}, status_code=410)(scope, receive, send)
        task = asyncio.current_task()
        self.controller.active.add(task)
        try: return await self.app(scope, receive, send)
        finally: self.controller.active.discard(task)
