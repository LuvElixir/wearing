#!/usr/bin/env python3
"""Disposable native-UI QA server. All records are synthetic; no agent can run.

Run from the repository root with .venv/bin/python. The database, files and
request audit are created in a fresh system temporary directory (or resumed
from this fixture's own verified temporary manifest). Only
127.0.0.1:8891 is bound. There is no Hermes client, runtime, capture worker,
scheduler, subprocess launcher, credentials loader or outbound network client.
Cloud/messaging/push use explicit MockTransport adapters only. This verifies
UI/API wiring, not AI/ASR/device-provider behavior.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import asynccontextmanager, suppress
import html
import json
import os
import secrets
import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Literal

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from qa_support import FixtureSupport

from wearing.activity import ActivityBook
from wearing.activity_api import install_activity_routes
from wearing.app import public_task
from wearing.artifact_api import install_artifact_routes
from wearing.artifacts import ArtifactBook, ArtifactDraft
from wearing.capture import CaptureBook, CaptureDraft, OrganizedNote
from wearing.capture_api import install_capture_routes
from wearing.confirmation_api import install_confirmation_routes
from wearing.briefing_api import install_briefing_routes
from wearing.goals import GoalBook, GoalError
from wearing.life import LifeBook, LifeDraft, LifeError
from wearing.life_api import install_life_routes
from wearing.task_lists import install_task_list_routes
from wearing.schedule_api import install_schedule_routes
from wearing.schedules import ScheduleBook, ScheduleDraft
from wearing.store import Store, now
from wearing.service import TaskService, TaskError
from wearing.workspace import WorkspaceError, list_files, workspace_file
from wearing.workspace_upload import install_workspace_import_routes
from wearing.workspace_api import install_workspace_page_routes
from wearing.workspace_text import install_workspace_text_routes
from wearing.native_sync import NativeSyncBook
from wearing.native_sync_api import install_native_sync_routes
from wearing.health_history import HealthHistory, HealthMonitor
from wearing.health_history_api import install_health_history_routes
from wearing.identity_export import IdentityExports
from wearing.identity_export_api import install_identity_export_routes
from wearing.usage import UsageBook
from wearing.usage_api import install_usage_routes
from wearing.diagnostics_api import install_diagnostic_routes
from wearing.search import SearchBook
from wearing.search_api import install_search_routes
from wearing.native_actions import NativeActions
from wearing.native_actions_api import install_native_action_routes
from wearing.onboarding import OnboardingBook
from wearing.onboarding_api import install_onboarding_routes

QA = 'qa'
REPO = Path(__file__).resolve().parents[3]


class GoalControl(BaseModel):
    model_config = ConfigDict(extra='forbid')
    revision: int = Field(ge=1, strict=True)
    action: Literal['resume', 'pause', 'cancel', 'complete', 'note']
    note: str = Field(default='', max_length=2000)
    add_steps: int = Field(default=0, ge=0, le=1000, strict=True)


class NewGoal(BaseModel):
    model_config = ConfigDict(extra='forbid')
    objective: str = Field(min_length=2, max_length=2000)
    boundaries: str = Field(min_length=2, max_length=2000)
    success_criteria: str = Field(min_length=2, max_length=2000)
    max_steps: int = Field(default=100, ge=1, le=1000, strict=True)
    request_key: str | None = Field(default=None, pattern=r'^[A-Za-z0-9_-]{16,120}$')


class FixtureCaptureWorker:
    """Only metadata: never extracts, transcribes, invokes or imports a provider."""
    def capabilities(self):
        return {'images': {'available': True, 'message': 'QA 合成原件'}, 'audio': {'available': False},
                'organize': {'available': False}, 'qa': True}

    async def transcribe_voice(self, identity, asset_id):
        raise LifeError('QA 不调用语音服务；请只验收已有合成资料。', 409)


class FixtureBriefClient:
    """Wire-contract implementation, not a real model; cannot open a connection."""
    async def probe(self): return {'state': 'reachable', 'message': 'QA synthetic task client',
        'wearing': {'confirmation_guard': 'durable-v1', 'session_recall_guard': 'sources-v1'}, 'qa': True}
    async def start(self, payload, request_key): return {'run_id': 'qa-brief-' + secrets.token_hex(8)}


def create_fixture(root: Path):
    root.chmod(0o700)
    store = Store(root / 'qa.sqlite3')
    with store.connection() as db:
        db.execute('INSERT INTO identities VALUES(?,?,?,?,?,?)', (QA, 'QA 验收（合成数据）', '仅供本地 App 按钮验收', 'CN', now(), now()))
        db.execute('INSERT INTO identity_conversations(identity_id,session_id) VALUES(?,?)', (QA, 'qa-synthetic-session'))
    life, goals, schedules = LifeBook(store), GoalBook(store), ScheduleBook(store)
    captures, artifacts = CaptureBook(life), ArtifactBook(store)
    workspace = artifacts.workspace(QA)
    (workspace / '关于你').mkdir(parents=True)
    (workspace / 'QA 结果').mkdir()
    (workspace / '关于你' / '偏好.md').write_text('# QA 合成记忆\n\n喜欢清晰的进展说明。\n所有内容只供按钮验收，不是真实用户记忆。\n')
    (workspace / 'QA 结果' / '测试记录.txt').write_text('QA 合成文件\n可以预览、搜索与打开原件。\n')
    image = REPO / 'clients/mobile/assets/icon.png'
    shutil.copyfile(image, workspace / 'QA 结果' / '测试图片.png')
    (workspace / 'QA 结果' / '图文简报.html').write_text('<!doctype html><html lang="zh"><meta charset="utf-8"><title>QA 合成简报</title><body style="font-family:system-ui;padding:24px"><h1>QA 合成简报</h1><p>这是隔离验收数据，不是模型输出。</p><ul><li>原生任务管理</li><li>资料预览</li><li>记录编辑与恢复</li></ul></body></html>')
    records = []
    future = datetime.now(timezone.utc) + timedelta(days=1)
    for key, draft in [
        ('note', LifeDraft(kind='note', title='QA 笔记：周末阅读清单', content='合成资料。可以测试修改标题与内容、移除和恢复。')),
        ('task', LifeDraft(kind='task', title='QA 待办：整理书桌', content='合成待办，用于测试完成与取消完成。')),
        ('event', LifeDraft(kind='event', title='QA 日程：产品验收', content='合成日程，不会邀请任何人。', start_at=future.isoformat(), end_at=(future + timedelta(hours=1)).isoformat())),
    ]:
        records.append(life.create(QA, draft, 'seed-' + key))
    asset = captures.upload(QA, image.read_bytes(), 'QA-测试图片.png', 'image/png', 'seed-image')
    job = captures.create(QA, CaptureDraft(record=LifeDraft(kind='note', title='QA 图片笔记：整理失败', content='这是一条可重试的合成图片笔记。'), asset_ids=[asset['id']], request_key='seed-failed', organize=True))
    captures.state(job, 'failed', error='QA 合成失败：点击重新整理可验收恢复流程。')
    paused = goals.create(QA, 'QA 目标：整理旅行资料', '只处理合成资料，不预订、不付款', '形成一份清晰的资料清单', 100)
    active = goals.create(QA, 'QA 目标：汇总本周进展', '只处理合成资料，不发送任何消息', '给出三项可检查的进展', 100)
    active = goals.control(active['id'], active['revision'], 'resume')
    schedule = schedules.create(QA, ScheduleDraft(title='QA 每日简报', instruction='整理合成日程和待办，不调用任何模型。', kind='cron', cron='0 9 * * *'), 'seed-schedule')

    first = store.create_message('QA 验收：展示一份合成简报。', QA)
    store.update(first['id'], status='running', run_id='qa-synthetic-run')
    artifact = artifacts.publish(QA, ArtifactDraft(path='QA 结果/图文简报.html', title='QA 合成简报', summary='仅供界面打开结果验收。', limitations=['无模型生成，无外部事实，无真实用户资料']), 'seed-artifact')
    store.update(first['id'], status='completed_unverified', output='QA 合成响应：资料已准备好。这不是模型生成的结果。可以打开简报或查看文件。')
    task = store.create('QA 执行中：整理合成进展', 'computer', QA)
    store.update(task['id'], status='running', run_id='qa-goal-run', output='')
    with store.connection() as db:
        db.execute('INSERT INTO goal_steps(task_id,goal_id,revision,created_at) VALUES(?,?,?,?)', (task['id'], active['id'], active['revision'], now()))
        db.execute('UPDATE personal_goals SET used_steps=1 WHERE id=?', (active['id'],))
    manifest = {'qa': True, 'identity': QA, 'root': str(root), 'database': str(store.path), 'audit': str(root / 'requests.jsonl'),
                'records': [{'id': record['id'], 'kind': record['kind'], 'title': record['title']} for record in records],
                'capture': {'id': job['id'], 'record_id': job['record_id'], 'asset_id': asset['id']},
                'goals': {'paused': paused['id'], 'active': active['id']}, 'schedule': schedule['id'], 'artifact': artifact['id'], 'task': task['id'],
                'limitations': ['No model/ASR/device calls', 'No scheduler/background worker', 'All data synthetic', 'Capture retry completes deterministically in QA only']}
    (root / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    return store, life, goals, schedules, captures, artifacts, workspace, manifest


def build_app(root: Path, resume=False):
    if resume:
        root = root.resolve()
        if root.parent != Path('/tmp').resolve() or not root.name.startswith('pajio-core-qa-'):
            raise ValueError('Only an existing synthetic QA temporary directory can be resumed.')
        manifest = json.loads((root / 'manifest.json').read_text())
        if manifest.get('qa') is not True or manifest.get('identity') != QA or manifest.get('root') != str(root) or manifest.get('database') != str(root / 'qa.sqlite3'):
            raise ValueError('The existing directory is not this synthetic fixture.')
        store = Store(root / 'qa.sqlite3')
        life, goals, schedules = LifeBook(store), GoalBook(store), ScheduleBook(store)
        captures, artifacts = CaptureBook(life), ArtifactBook(store)
        workspace = artifacts.workspace(QA)
    else:
        store, life, goals, schedules, captures, artifacts, workspace, manifest = create_fixture(root)
    token = secrets.token_urlsafe(32)
    app = FastAPI(title='Pajio QA synthetic fixture', docs_url=None, redoc_url=None, openapi_url=None)
    audit = root / 'requests.jsonl'
    qa_service = TaskService(store, FixtureBriefClient())
    support = FixtureSupport(app, root, store, qa_service, manifest)
    from wearing.record_reminders_api import install_record_reminder_routes
    install_record_reminder_routes(app, support.notifications.reminders)
    install_confirmation_routes(app, qa_service, lambda task: public_task(task, store=store, local_devices=True))
    support.seed_confirmation(qa_service, manifest)

    def complete_synthetic_brief():
        with store.connection() as db:
            rows = db.execute('''SELECT b.id,b.brief_date,b.version,t.id AS task_id FROM daily_briefings b
                JOIN message_handoffs h ON h.identity_id=b.identity_id AND h.request_id=b.task_request_id
                JOIN tasks t ON t.id=h.task_id WHERE b.identity_id=? AND t.status='running' ''', (QA,)).fetchall()
        for row in rows:
            title = f"QA 合成简报 · {row['brief_date']} · 第 {row['version']} 版"
            relative = f"QA 结果/{row['id']}.html"
            (workspace / relative).write_text('<!doctype html><html lang="zh"><meta charset="utf-8"><title>QA 合成简报</title><body style="font-family:system-ui;padding:24px"><h1>' + html.escape(title) + '</h1><p>这是验收程序确定性生成的合成结果，未调用模型、云应用或设备。</p><ul><li>任务、版本和来源状态已保存。</li><li>关闭页面后可继续读取原成果。</li></ul></body></html>')
            artifacts.publish(QA, ArtifactDraft(path=relative, title=title, summary='QA 确定性成果，用于验证原生生成、持久版本与打开图文按钮。', presentation='dashboard', sources=['QA 合成记录', 'QA 合成文件'], limitations=['没有模型生成，也未读取外部信息。']), 'qa-brief-result')
            store.update(row['task_id'], status='completed_unverified', output='QA 合成简报已保存。此内容仅用于按钮验收，不是模型输出。')

    @app.middleware('http')
    async def guard_and_audit(request: Request, call_next):
        started = datetime.now(timezone.utc)
        path = request.url.path
        identity = request.headers.get('x-wearing-identity') or request.query_params.get('identity') or QA
        request.state.identity_id = QA
        safe_body = {}
        if request.headers.get('content-type', '').startswith('application/json'):
            try:
                body = await request.json()
                safe_body = {key: body[key] for key in ('action', 'revision', 'add_steps') if key in body}
                safe_body['fields'] = sorted(body) if isinstance(body, dict) else []
            except (ValueError, TypeError):
                pass
        if path.startswith('/api/') and path != '/api/bootstrap' and identity != QA:
            response = JSONResponse({'detail': 'QA 服务只有合成验收身份。'}, status_code=404)
        elif request.method not in {'GET', 'HEAD', 'OPTIONS'} and request.headers.get('x-wearing-token') != token:
            response = JSONResponse({'detail': 'QA 页面会话已失效，请刷新。'}, status_code=403)
        else:
            response = await call_next(request)
            if response.status_code < 300 and request.method == 'POST' and (path == '/api/briefings' or path.startswith('/api/tasks/') or path.startswith('/api/goals/')):
                await qa_service.dispatch_message()
                complete_synthetic_brief()
            if response.status_code < 300 and request.method == 'POST' and path.startswith('/api/captures/') and path.endswith('/retry'):
                # Deterministic fixture processing after the real retry transaction.
                retried = captures.get(QA, path.split('/')[3])
                if retried['state'] == 'queued':
                    captures.state(retried, 'organizing')
                    captures.apply(retried, OrganizedNote(title='QA 图片笔记：已重新整理', content='QA 确定性整理回执。原图片仍保留，未调用模型。'))
        if response.status_code < 300 and path.startswith('/api/'):
            await support.tick(path, request.method)
        response.headers['X-Pajio-QA'] = 'synthetic-no-model'
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers.setdefault('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        entry = {'at': started.isoformat(), 'method': request.method, 'path': path, 'identity': identity, 'status': response.status_code, **safe_body}
        with audit.open('a') as stream:
            stream.write(json.dumps(entry, ensure_ascii=False) + '\n')
        return response

    @app.exception_handler(GoalError)
    async def goal_error(request, error): return JSONResponse({'detail': str(error)}, status_code=409)

    @app.exception_handler(TaskError)
    async def task_error(request, error): return JSONResponse({'detail': str(error)}, status_code=409)

    @app.exception_handler(WorkspaceError)
    async def file_error(request, error): return JSONResponse({'detail': str(error)}, status_code=404)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error): return JSONResponse({'detail': 'QA 请求字段不完整，请检查输入。'}, status_code=422)

    # These are the real production record, capture, schedule and activity routers.
    install_life_routes(app, life)
    from wearing.bookmark_api import install_bookmark_routes
    install_bookmark_routes(app, life)
    install_task_list_routes(app, life)
    from wearing.calendar_series import CalendarSeriesBook
    from wearing.calendar_series_api import install_calendar_series_routes
    install_calendar_series_routes(app, CalendarSeriesBook(store))
    install_capture_routes(app, captures, FixtureCaptureWorker())
    install_schedule_routes(app, schedules)
    install_activity_routes(app, ActivityBook(store))
    install_artifact_routes(app, artifacts)
    install_workspace_import_routes(app, store, lambda identity: SimpleNamespace(workspace=workspace))
    install_workspace_page_routes(app, store, lambda identity: SimpleNamespace(workspace=workspace))
    install_workspace_text_routes(app, store, lambda identity: SimpleNamespace(workspace=workspace))
    install_native_sync_routes(app, NativeSyncBook(store))
    install_onboarding_routes(app, OnboardingBook(store))
    install_identity_export_routes(app, IdentityExports(store))
    install_usage_routes(app, UsageBook(root, enabled=False))
    install_search_routes(app, SearchBook(store))
    from wearing.conversation_sources import ConversationSources
    from wearing.conversation_sources_api import install_conversation_source_routes
    install_conversation_source_routes(app, ConversationSources(store))
    # Configuration/history only in UI QA: no Agent enqueues device commands.
    install_native_action_routes(app, NativeActions(store))
    async def diagnostic_probe(identity):
        # Explicit synthetic capability snapshot; never invoke an engine/provider.
        return {'state': 'not_configured'}
    install_diagnostic_routes(app, store, lambda identity: SimpleNamespace(status=lambda: {
        'running': False, 'installed': False, 'phase': 'idle', 'files': {'phase': 'ready', 'active': True},
        'phone': {'phase': 'idle', 'active': False}, 'computer': {'phase': 'idle', 'active': False}}),
        probe_for=diagnostic_probe, deployment='synthetic')
    history = HealthHistory(store)
    monitor = HealthMonitor(history, app.state.diagnostics, deployment='synthetic')
    install_health_history_routes(app, history, monitor)
    @asynccontextmanager
    async def qa_lifespan(_app):
        stop = asyncio.Event()
        task = asyncio.create_task(monitor.run(stop))
        try:
            yield
        finally:
            stop.set()
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
    app.router.lifespan_context = qa_lifespan

    # Idempotent additions live only in this verified synthetic Store. Existing
    # edited fixture rows remain unchanged across restarts.
    search_seed = store.setting('qa_search_seed')
    if not search_seed:
        note = life.create(QA, LifeDraft(kind='note', title='QA 搜索验收：会前资料', content='搜索验收合成笔记，可以打开详情编辑。'), 'qa-search-note-001')
        foreign = life.create('daily', LifeDraft(kind='note', title='QA 搜索验收：另一个身份', content='QA_FOREIGN_SEARCH_CANARY'), 'qa-search-foreign-001')
        with store.connection() as db:
            task_id = store.insert_message(db, 'QA 搜索验收：请整理会前资料。', QA)
            db.execute('UPDATE tasks SET status=?,output=? WHERE id=?', ('completed_unverified', 'QA 合成搜索回复：已整理三项会前资料。没有调用模型。', task_id))
            message_id = db.execute('SELECT id FROM messages WHERE task_id=?', (task_id,)).fetchone()[0]
            search_seed = {'query': '搜索验收', 'record_id': note['id'], 'task_id': task_id, 'message_id': message_id, 'foreign_record_id': foreign['id']}
            db.execute('INSERT INTO settings(key,value) VALUES(?,?)', ('qa_search_seed', json.dumps(search_seed)))
    manifest['search'] = search_seed
    briefings = install_briefing_routes(app, store, qa_service, artifacts, cloud_apps=support.cloud)
    from wearing.briefing_automation_api import install_briefing_automation_routes
    install_briefing_automation_routes(app, store, briefings, schedules)

    @app.get('/_qa/manifest')
    async def qa_manifest(): return manifest

    @app.get('/api/bootstrap')
    async def bootstrap():
        return {'token': token, 'version': '0.2.0', 'default_identity_id': QA, 'identities': [store.identity(QA)], 'hermes_url': 'http://127.0.0.1:8891',
                'configured': True, 'deployment': 'local', 'goal_policy': {'default_steps': 100, 'max_steps': 1000, 'extension_steps': 100}, 'qa': True}

    @app.get('/api/status')
    async def status(): return {'hermes': {'state': 'ready', 'message': 'QA 合成环境，不运行模型', 'wearing': {'web_tools': []}}, 'other_active': [], 'device_report': None, 'qa': True}

    @app.get('/api/runtime')
    async def runtime(): return {'running': False, 'installed': False, 'phase': 'idle', 'error': 'QA 环境不运行模型', 'product': {'applied': False}, 'model': {'state': 'not_configured', 'provider': None}, 'files': {'active': True}, 'phone': {'active': False}, 'computer': {'active': False}, 'qa': True}

    @app.get('/api/identities')
    async def identities(): return [store.identity(QA)]

    @app.get('/api/identity')
    async def identity(): return {**store.identity(QA), 'devices': [], 'accounts': 'not_connected'}

    @app.get('/api/workspace')
    async def files(): return list_files(workspace)

    @app.get('/api/workspace/file')
    async def file(path: str): return FileResponse(workspace_file(workspace, path), content_disposition_type='inline')

    @app.get('/api/goals')
    async def list_goals(): return goals.list(QA)

    @app.post('/api/goals', status_code=201)
    async def new_goal(body: NewGoal): return goals.create(QA, **body.model_dump())

    @app.get('/api/goals/{goal_id}')
    async def goal_detail(goal_id: str): return goals.detail(goal_id, QA)

    @app.post('/api/goals/{goal_id}/control')
    async def goal_control(goal_id: str, body: GoalControl):
        detail = goals.detail(goal_id, QA)
        if body.action in {'note', 'complete'} and len(body.note.strip()) < 3: raise HTTPException(422, '请写下具体内容。')
        if body.action == 'complete' and any(step['task_status'] == 'running' for step in detail['steps']): raise GoalError('QA 本轮仍在执行，请先暂停并查看记录。')
        result = goals.control(goal_id, body.revision, body.action, body.note.strip(), body.add_steps)
        if body.action in {'pause', 'cancel', 'note'}:
            for step in detail['steps']:
                if step['task_status'] == 'running': store.update(step['task_id'], status='stopped', output='QA 合成执行已停止，没有真实设备或模型动作。')
        return result

    @app.get('/api/goal-updates')
    async def updates(): return goals.updates(QA)

    @app.post('/api/goal-updates/seen')
    async def seen(request: Request): return goals.acknowledge_updates(QA, (await request.json())['ids'])

    def task_data(task):
        if not task or task['identity_id'] != QA: raise HTTPException(404, 'QA 没有这条任务。')
        return public_task(task, store=store, local_devices=True)

    @app.get('/api/tasks')
    async def tasks(): return [task_data(task) for task in store.list(QA)]

    @app.get('/api/tasks/{task_id}')
    async def task(task_id: str): return task_data(app.state.activity.detail_snapshot(QA, task_id))

    @app.post('/api/tasks/{task_id}/{action}')
    async def task_action(task_id: str, action: str):
        current = task_data(store.get(task_id))
        if action == 'cancel-message': return task_data(await qa_service.cancel_message(task_id, identity_id=QA))
        if action == 'stop': return task_data(store.update(task_id, status='stopped', output='QA 合成任务已停止。'))
        if action == 'refresh': return current
        if action == 'start': return task_data(await qa_service.start(task_id))
        raise HTTPException(409, 'QA 不执行该任务操作，不会调用模型或设备。')

    @app.get('/api/conversation')
    async def conversation():
        results = artifacts.for_conversation(QA)
        messages = [{**row, 'turn': {**task_data(store.get(row['task_id'])), 'artifacts': results.get(row['task_id'], []), 'confirmations': []}} for row in store.conversation(QA)]
        from wearing.task_presentation import present_messages
        messages = present_messages(store, messages)
        for row in messages: row.update(store.message_receipt(row['task_id']))
        for goal in goals.list(QA):
            for step in goals.detail(goal['id'], QA)['steps']:
                messages.append({'id': 'goal-' + step['task_id'], 'task_id': step['task_id'], 'kind': 'goal_step', 'goal_id': goal['id'], 'content': goal['objective'], 'created_at': step['created_at'], 'turn': {**task_data(store.get(step['task_id'])), 'artifacts': [], 'confirmations': []}})
        return sorted(messages, key=lambda row: (row['created_at'], str(row['id'])))

    @app.post('/api/conversation', status_code=201)
    async def new_message(request: Request):
        body = await request.json()
        if not isinstance(body.get('content'), str) or not body['content'].strip(): raise HTTPException(422, '请填写合成验收文字。')
        # Explicit synthetic response; no real message leaves this local database.
        task = store.create_message(body['content'][:12000], QA)
        result = store.update(task['id'], status='completed_unverified', output='QA 合成回执：已收到测试文字。未调用模型、外部服务或设备。')
        return task_data(result)

    @app.get('/api/computer')
    async def computer(): return {'connected': False, 'control': {'holder': 'human'}, 'qa': True}

    app.mount('/assets', StaticFiles(directory=REPO / 'src/wearing/web'), name='assets')

    @app.get('/')
    async def index(): return FileResponse(REPO / 'src/wearing/web/index.html')

    @app.api_route('/api/{path:path}', methods=['GET', 'POST', 'PATCH', 'DELETE'])
    async def unavailable(path: str): raise HTTPException(409, 'QA 合成环境未启用此能力，不会调用外部服务。')

    return app, manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8891)
    parser.add_argument('--resume-root', type=Path, help='Resume this server\'s existing synthetic /tmp fixture without reseeding.')
    args = parser.parse_args()
    if args.port != 8891: raise SystemExit('This bounded fixture only uses port 8891.')
    root = args.resume_root.resolve() if args.resume_root else Path(tempfile.mkdtemp(prefix='pajio-core-qa-', dir='/tmp')).resolve()
    app, manifest = build_app(root, resume=bool(args.resume_root))
    manifest.update(endpoint='http://127.0.0.1:8891/', pid=os.getpid())
    (root / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    print(json.dumps(manifest, ensure_ascii=False), flush=True)
    uvicorn.run(app, host='127.0.0.1', port=args.port, log_level='warning', access_log=False, lifespan='on')
