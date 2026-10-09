"""Synthetic adapters for QA only. Every HTTP client has an explicit MockTransport.

Production routers and business ledgers are reused. No environment credentials,
user runtime directory, real OAuth browser URL, socket or process is required.
"""
from __future__ import annotations
import json
import os
import time
import uuid
from pathlib import Path
from types import SimpleNamespace
import httpx
from fastapi import HTTPException, Request
from filelock import FileLock

from wearing.cloud_apps import CloudApps, FeishuCloudNetwork, FEATURES, TOKEN_PATH
from wearing.cloud_apps_api import install_cloud_app_routes
from wearing.messaging import MessagingBridge, ChannelNetwork
from wearing.messaging_api import install_messaging_routes
from wearing.memory_controls import mutate_memory, revision
from wearing.notifications import NotificationService, NotificationConfig, NotificationError, SEND_URL, RECEIPT_URL
from wearing.notifications_api import install_notification_routes
from wearing.skills_api import install_skill_routes
from wearing.store import now
from wearing.durable_confirmations import encoded

APP_ID = 'cli_QASYNTHETIC'
SECRET = 'QA_SYNTHETIC_SECRET_001'
BOT_TOKEN = '123456:QA_SYNTHETIC_BOT_TOKEN_001'
PROJECT_ID = '00000000-0000-4000-8000-000000000001'
PUSH_TOKEN = 'ExpoPushToken[qa_synthetic_push_001]'
DELIMITER = '\n§\n'


def write_json(path, value):
    if path.is_symlink(): raise ValueError('QA fixture refuses linked state')
    temporary = path.with_name('.' + path.name + '.' + uuid.uuid4().hex)
    with temporary.open('x') as f: json.dump(value, f, ensure_ascii=False)
    temporary.chmod(0o600)
    os.replace(temporary, path)


class FixtureMemoryStore:
    """Minimal file-backed store protocol for the real mutate_memory function.

    This substitutes only the upstream storage adapter; memory_controls performs
    actual target/action validation, revisions, entry edits and capacity checks.
    The synthetic app never exposes these entries to an Agent.
    """
    def __init__(self, root):
        self.path = root / 'qa-memory.json'
        self.lock = FileLock(root / 'qa-memory.lock')
        with self.lock:
            if not self.path.exists():
                write_json(self.path, {'user': ['QA 合成记忆：喜欢清晰的进展说明。'], 'memory': ['QA 合成经验：变更后核对实际回执。']})
    def target_enabled(self, target): return target in {'user', 'memory'}
    def read(self):
        if self.path.is_symlink() or self.path.stat().st_size > 65536: raise ValueError('Unsafe QA memory')
        return json.loads(self.path.read_text())
    def snapshot(self):
        with self.lock: values = self.read()
        return {'available': True, 'observed_at': now(), 'qa': True, 'identity_id': 'qa', 'targets': {target: {'enabled': True, 'entries': values[target],
          'revision': revision(values[target]), 'used_chars': len(DELIMITER.join(values[target])), 'limit_chars': 12000} for target in ('user', 'memory')}}
    def _mutate(self, target, apply):
        with self.lock:
            values = self.read()
            changed = apply(values[target], 12000)
            if isinstance(changed, dict): return changed
            values[target] = changed[0]
            write_json(self.path, values)
            return {'success': True}


class SyntheticTransport:
    def __init__(self, root): self.root, self.calls = root, []
    def __call__(self, request):
        host, path = request.url.host, request.url.path
        call = {'host': host, 'path': path, 'method': request.method, 'synthetic': True}
        self.calls.append(call)
        with (self.root / 'mock-transports.jsonl').open('a') as log: log.write(json.dumps(call) + '\n')
        body = {}
        if request.headers.get('content-type', '').startswith('application/json'):
            body = json.loads(request.content or b'{}')
        if host == 'api.telegram.org':
            if path == f'/bot{BOT_TOKEN}/getMe': data = {'id': 123456, 'is_bot': True, 'username': 'QA_Synthetic_Bot'}
            elif path == f'/bot{BOT_TOKEN}/getWebhookInfo': data = {'url': ''}
            elif path == f'/bot{BOT_TOKEN}/getUpdates': data = []
            elif path == f'/bot{BOT_TOKEN}/sendMessage': data = {'message_id': 1}
            else: raise AssertionError('Unexpected synthetic Telegram request')
            return httpx.Response(200, json={'ok': True, 'result': data})
        if host == 'accounts.feishu.cn' and path == '/oauth/v1/revoke': return httpx.Response(200, content=b'')
        if host == 'open.feishu.cn':
            if path == '/open-apis/auth/v3/tenant_access_token/internal':
                assert body == {'app_id': APP_ID, 'app_secret': SECRET}
                return httpx.Response(200, json={'code': 0, 'tenant_access_token': 'qa-tenant-token', 'expire': 7200})
            if path == '/open-apis/authen/v2/oauth/device_authorization':
                data = {'verification_uri_complete': 'https://accounts.feishu.cn/qa-synthetic-never-open', 'device_code': 'qa-device-code', 'user_code': 'QA ONLY', 'expires_in': 600, 'interval': 5}
            elif path == TOKEN_PATH:
                assert body.get('client_id') == APP_ID and body.get('client_secret') == SECRET
                data = {'access_token': 'qa-access-token', 'refresh_token': 'qa-refresh-token', 'expires_in': 3600, 'refresh_token_expires_in': 86400,
                        'scope': ' '.join(['offline_access'] + [scope for feature in FEATURES.values() for scope in feature['scopes']])}
            elif path == '/open-apis/authen/v1/user_info': data = {'name': 'QA 合成飞书账号', 'open_id': 'ou_QASYNTHETIC'}
            elif path == '/open-apis/bot/v3/info': return httpx.Response(200, json={'code': 0, 'bot': {'app_name': 'QA 飞书机器人（模拟）'}})
            elif path == '/open-apis/drive/v1/files': data = {'files': [{'name': 'QA 合成项目简报', 'token': 'qa_document', 'type': 'docx'}], 'has_more': False}
            elif path == '/open-apis/docx/v1/documents/qa_document/raw_content': data = {'content': '# QA 合成项目简报\n\n这是 MockTransport 返回的合成资料，没有读取飞书。'}
            elif path == '/open-apis/wiki/v2/spaces/get_node': data = {'node': {'obj_type': 'docx', 'obj_token': 'qa_document', 'title': 'QA 合成知识库'}}
            elif path == '/open-apis/calendar/v4/calendars': data = {'calendar_list': [{'calendar_id': 'qa_calendar', 'summary': 'QA 合成日历', 'role': 'reader'}], 'has_more': False}
            elif path == '/open-apis/calendar/v4/calendars/qa_calendar/events':
                start = request.url.params.get('start_time', str(int(time.time())))
                data = {'items': [{'event_id': 'qa_event', 'summary': 'QA 合成验收日程', 'description': '没有邀请真实用户。', 'start_time': {'timestamp': start}, 'end_time': {'timestamp': str(int(start) + 1800)}, 'status': 'confirmed'}], 'has_more': False}
            elif path == '/open-apis/im/v1/messages': data = {'message_id': 'qa-message'}
            else: raise AssertionError('Unexpected synthetic Feishu request')
            return httpx.Response(200, json={'code': 0, 'data': data})
        if str(request.url) == SEND_URL:
            assert body.get('to') == PUSH_TOKEN
            return httpx.Response(200, json={'data': {'status': 'ok', 'id': 'qa-ticket-' + body['data']['event_key']}})
        if str(request.url) == RECEIPT_URL:
            return httpx.Response(200, json={'data': {key: {'status': 'ok'} for key in body['ids']}})
        raise AssertionError('QA transport cannot access this destination')


class SyntheticCloudApps(CloudApps):
    async def configure(self, identity, app_id, secret, features):
        if app_id != APP_ID or secret != SECRET: raise HTTPException(422, 'QA 只接受 manifest 中的合成凭据，请勿填写真实凭据。')
        return await super().configure(identity, app_id, secret, features)
    async def authorize(self, identity, revision):
        # Exercise the genuine authorization and token exchange business logic,
        # then finish the MOCK grant before returning. No external browser URL
        # is ever exposed, so native clients cannot open real OAuth accidentally.
        state = await super().authorize(identity, revision)
        row = self._read(identity)
        row['pending']['next_poll'] = 0
        self._write(identity, row)
        return {**await super().poll(identity, state['authorization']['id']), 'qa': True, 'authorization_simulated': True}


class SyntheticReceiver:
    def __init__(self, bridge): self.bridge = bridge
    async def synchronize(self, rows):
        for row in rows: await self.bridge.feishu_status(row, 'connected')
    async def stop(self, identity): pass
    async def close(self): pass


class SyntheticMessaging(MessagingBridge):
    async def configure(self, identity, provider, secret, users, app_id=None):
        if (provider == 'telegram' and (secret != BOT_TOKEN or users != ['123456789'])) or (provider == 'feishu' and (app_id != APP_ID or secret != SECRET or users != ['ou_QASYNTHETIC'])):
            raise HTTPException(422, 'QA 只接受 manifest 中的合成凭据和用户，请勿填写真实凭据。')
        return await super().configure(identity, provider, secret, users, app_id)
    def start(self): pass  # QA only ticks deterministically after an explicit request.


class SyntheticNotifications(NotificationService):
    def register(self, identity, installation, token, project_id, platform, session_expires=None, *, owner_scope="local"):
        if token != PUSH_TOKEN: raise NotificationError('QA 只接受 manifest 中的合成通知凭据。', 422)
        return super().register(identity, installation, token, project_id, platform, session_expires, owner_scope=owner_scope)


class FixtureSupport:
    def __init__(self, app, root, store, service, manifest):
        self.store, self.root, self.app = store, root, app
        self.mock = SyntheticTransport(root)
        self.client = httpx.AsyncClient(transport=httpx.MockTransport(self.mock), trust_env=False)
        self.cloud = SyntheticCloudApps(store, FeishuCloudNetwork(self.client))
        self.messaging = SyntheticMessaging(store, service, ChannelNetwork(self.client))
        self.messaging.feishu = SyntheticReceiver(self.messaging)
        self.notifications = SyntheticNotifications(store, config=NotificationConfig(True, PROJECT_ID), client=self.client)
        self.memory = FixtureMemoryStore(root)
        runtime = SimpleNamespace(home=root / 'qa-runtime', source=root / 'qa-catalog')
        for directory in (runtime.home / 'skills' / 'qa-notes', runtime.source / 'skills' / 'qa-summary'):
            directory.mkdir(parents=True, exist_ok=True)
            skill = directory / 'SKILL.md'
            if not skill.exists(): skill.write_text(f'---\nname: {directory.name}\ndescription: QA 合成技能，仅验证安装与启用。\n---\n\n这是合成技能，不调用任何模型、应用或命令。\n')
        self.runtime = runtime
        install_skill_routes(app, lambda identity: runtime)
        install_cloud_app_routes(app, self.cloud)
        install_messaging_routes(app, self.messaging)
        install_notification_routes(app, self.notifications)
        app.state.qa_support = self
        app.state.store = store
        manifest['mock_capabilities'] = ['skills-real-file-copy', 'memory-real-mutation-controls', 'cloud-feishu-mock', 'messaging-mock', 'expo-push-mock']
        manifest['synthetic_credentials'] = {'feishu_app_id': APP_ID, 'feishu_secret': SECRET, 'feishu_user': 'ou_QASYNTHETIC', 'telegram_token': BOT_TOKEN,
                                           'telegram_user': '123456789', 'expo_project_id': PROJECT_ID, 'expo_push_token': PUSH_TOKEN}
        # First setup only. A resume never restores a user's QA-disconnected app.
        marker = root / 'qa-support-seeded.json'
        if not marker.exists():
            self.cloud._write('qa', {'app_id': APP_ID, 'secret': SECRET, 'features': ['documents', 'calendar'], 'revision': uuid.uuid4().hex})
            write_json(marker, {'synthetic': True})

        @app.get('/api/memory')
        def memory(): return self.memory.snapshot()

        @app.patch('/api/memory')
        async def change_memory(request: Request):
            body = await request.json()
            if not isinstance(body, dict) or set(body) - {'target', 'action', 'content', 'revision', 'index'}:
                raise HTTPException(422, 'QA 记忆请求字段无效。')
            result = mutate_memory(self.memory, body, lambda text: DELIMITER in text or any(ord(c) < 32 and c not in '\n\t' for c in text), DELIMITER)
            if not result.get('success'): raise HTTPException(result.get('status', 409), result.get('error'))
            return self.memory.snapshot()

        @app.post('/_qa/notifications/receipts')
        async def mock_receipts():
            with store.connection() as db: db.execute("UPDATE notification_outbox SET next_at=0 WHERE state='ticket'")
            await self.notifications.receipts()
            return {'qa': True, 'mock_provider_accepted': True, 'actual_device_delivery': False}

    async def tick(self, path, method):
        if path.startswith('/api/messaging'):
            await self.messaging.tick()
        if method in {'POST', 'PATCH', 'DELETE', 'PUT'}:
            await self.notifications.tick()

    def seed_confirmation(self, service, manifest):
        """One expired fixture row; no live waiter, approval or action is created.

        Routes below use the SAME service/ledger. Direct seeding avoids altering
        unrelated existing QA runs just to imitate a formerly live waiter.
        """
        decision_id = 'decision_' + uuid.uuid5(uuid.NAMESPACE_URL, 'pajio-qa-synthetic-recovery-001').hex
        legacy_id = 'decision_qa_synthetic_recovery_001'
        assert service.confirmations.durable.store is self.store
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            # Migrate this one pre-release synthetic fixture ID to the actual
            # contract shape, keeping any already reserved recovery intact.
            if db.execute('SELECT 1 FROM durable_confirmations WHERE id=? AND identity_id=?', (legacy_id, 'qa')).fetchone():
                db.execute('UPDATE durable_confirmations SET id=? WHERE id=? AND identity_id=?', (decision_id, legacy_id, 'qa'))
                db.execute('UPDATE durable_confirmations SET parent_id=? WHERE parent_id=? AND identity_id=?', (decision_id, legacy_id, 'qa'))
                db.execute('UPDATE confirmation_recovery_tasks SET source_id=? WHERE source_id=?', (decision_id, legacy_id))
                db.execute('UPDATE confirmation_resume_requests SET action_id=? WHERE action_id=? AND identity_id=?', (decision_id, legacy_id, 'qa'))
                db.execute('UPDATE message_handoffs SET request_id=? WHERE request_id=? AND identity_id=?', ('confirmation_'+decision_id, 'confirmation_'+legacy_id, 'qa'))
            existing = db.execute('SELECT task_id FROM durable_confirmations WHERE id=?', (decision_id,)).fetchone()
            if existing:
                task_id = existing['task_id']
            else:
                task_id = self.store.insert_message(db, 'QA 合成确认：保存测试笔记。', 'qa')
                stamp = now()
                run_id = 'qa-expired-confirmation-run'
                db.execute("UPDATE tasks SET status='completed_unverified',run_id=?,output=? WHERE id=?",
                           (run_id, 'QA 合成过期提案：未执行保存。可重新核对，不代表批准。', task_id))
                card = {'title': 'QA 保存这份测试笔记？', 'action': '保存一条合成测试笔记。',
                        'impact': 'QA 提案已过期；重新核对不会批准或重放保存。', 'confirm_label': '保存笔记'}
                db.execute('''INSERT INTO durable_confirmations
                    (id,identity_id,task_id,run_id,card,state,expires_at,created_at,updated_at)
                    VALUES(?,?,?,?,?,'pending',?,?,?)''',
                    (decision_id, 'qa', task_id, run_id, encoded(card), '2000-01-01T00:00:00+00:00', stamp, stamp))
        service.confirmations.durable.get('qa', decision_id)  # Actual expiry state transition.
        manifest['confirmation'] = {'id': decision_id, 'task_id': task_id, 'synthetic': True}

    async def close(self):
        if getattr(self.app.state, 'workspace_pager', None): self.app.state.workspace_pager.close()
        await self.messaging.close()
        await self.notifications.close()
        await self.client.aclose()
