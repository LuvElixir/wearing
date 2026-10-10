from .mobile import RegistryError
"""Loopback-only control surface. No credentials are returned to the browser."""

import asyncio
import json
import logging
import re
import secrets
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, SecretStr, ValidationError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .config import Settings, write_private_json
from .doctor import inspect_host
from .hermes import HermesClient, HermesError
from .runtime import HermesRuntime, RuntimeError
from .service import ACTIVE, TaskError, TaskService
from .store import DEFAULT_IDENTITY, IdentityError, MessageConflict, Store, now
from .life import LifeBook
from .life_api import install_life_routes
from .capture import CaptureBook
from .capture_worker import CaptureWorker
from .capture_api import install_capture_routes
from . import computer, mobile
from .workspace import WorkspaceError, list_files, workspace_file
from .artifacts import ArtifactBook
from .artifact_api import install_artifact_routes
from .goals import GoalBook, GoalCoordinator, GoalError, parse_report, DEFAULT_GOAL_STEPS, MAX_GOAL_STEPS, GOAL_EXTENSION_STEPS
from .schedules import ScheduleBook, ScheduleCoordinator
from .schedule_api import install_schedule_routes
from .activity import ActivityBook
from .activity_api import install_activity_routes
from .task_visibility import request_owner, ids as visible_task_ids, visible as task_visible


class NewTask(BaseModel):
    prompt: str = Field(min_length=1, max_length=12000)
    target: Literal["computer", "phone", "sandbox"] = "computer"


class NewMessage(BaseModel):
    content: str = Field(min_length=1, max_length=12000)
    request_id: str | None = Field(default=None, min_length=16, max_length=80, pattern=r"^[A-Za-z0-9_-]+$", strict=True)
    goal_id: str | None = Field(default=None, min_length=1, max_length=64)
    goal_mode: Literal["discuss", "note"] = "discuss"
    goal_revision: int | None = Field(default=None, ge=1, strict=True)
    life_record_id: str | None = Field(default=None, min_length=1, max_length=64)
    life_revision: int | None = Field(default=None, ge=1, strict=True)


class NewGoal(BaseModel):
    request_key: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{16,120}$")
    objective: str = Field(min_length=2, max_length=2000)
    boundaries: str = Field(min_length=2, max_length=2000)
    success_criteria: str = Field(min_length=2, max_length=2000)
    max_steps: int = Field(default=DEFAULT_GOAL_STEPS, ge=1, le=MAX_GOAL_STEPS, strict=True)
    source_task_id: str | None = Field(default=None, max_length=64)


class GoalControl(BaseModel):
    revision: int = Field(ge=1, strict=True)
    action: Literal["resume", "pause", "cancel", "complete", "note"]
    note: str = Field(default="", max_length=2000)
    add_steps: int = Field(default=0, ge=0, le=MAX_GOAL_STEPS, strict=True)


class SeenGoalUpdates(BaseModel):
    ids: list[Annotated[int, Field(gt=0, strict=True)]] = Field(min_length=1, max_length=100)


class IdentityProfile(BaseModel):
    name: str = Field(min_length=1, max_length=24)
    description: str = Field(default="", max_length=240)
    region: Literal["CN", "international", "custom"] = "CN"


class ModelSettings(BaseModel):
    provider: Literal["deepseek", "openai-api", "anthropic", "openrouter", "minimax-cn"]
    model: str = Field(min_length=1, max_length=200)
    key: SecretStr = Field(default=SecretStr(""), max_length=4096)


class Connection(BaseModel):
    url: str = Field(max_length=500)
    key: str = Field(min_length=1, max_length=4096)


class PhoneBinding(BaseModel):
    serial: str = Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_.:-]+$")


class PhoneResource(BaseModel):
    resource_id: str | None = Field(default=None, pattern=r"^phone_[0-9a-f]{20}$")


class Approval(BaseModel):
    request_id: str = Field(min_length=1, max_length=256)
    choice: Literal["task", "once", "deny"]


class Verification(BaseModel):
    note: str = Field(min_length=3, max_length=2000)


class PhoneReport(BaseModel):
    serial: str = Field(max_length=250)
    model: str = Field(default="Android", max_length=250)
    state: str = Field(max_length=50)
    android_version: str | None = Field(default=None, max_length=50)
    sdk_level: str | None = Field(default=None, max_length=50)


class DeviceReport(BaseModel):
    schema_version: Literal[1]
    observed_at: str = Field(max_length=100)
    system: Literal["Darwin", "Windows", "Linux"]
    release: str = Field(max_length=200)
    architecture: str = Field(max_length=100)
    python: str = Field(max_length=100)
    commands: dict[str, bool]
    phones: list[PhoneReport] = Field(default_factory=list, max_length=100)
    phone_check: str = Field(max_length=100)
    desktop_control: str = Field(max_length=100)


def public_task(task, *, store, local_devices=False):
    from .task_presentation import present_task
    return present_task(store, task, local_devices=local_devices)


def create_app(settings: Settings | None = None, hermes: HermesClient | None = None, *,
               allowed_hosts=None, browser_origin=None, engine_autostart=False, local_devices=True):
    settings = settings or Settings.from_env()
    store = Store(settings.data_dir / "wearing.sqlite3")
    def task_view(task):
        return public_task(task, store=store, local_devices=local_devices)
    service = TaskService(store, hermes or HermesClient(settings))
    goals = GoalBook(store)
    goal_coordinator = GoalCoordinator(goals, service)
    schedules = ScheduleBook(store)
    schedule_coordinator = ScheduleCoordinator(schedules, service)
    life = LifeBook(store)
    artifacts = ArtifactBook(store)
    captures = CaptureBook(life)
    capture_worker = CaptureWorker(captures, local_devices=local_devices)
    from .onboarding import OnboardingBook
    onboarding = OnboardingBook(store)
    from .chat_imports import ChatImports
    chat_imports = ChatImports(store)
    service.context_provider = lambda task: goals.context(task) + life.context(task) + schedules.context(task) + onboarding.context(task)
    from .usage import UsageBook, UsageError
    from .usage_api import install_usage_routes
    usage = UsageBook(settings.data_dir)
    from .ai_consent import ConsentBook, ConsentError
    from .ai_consent_api import install_consent_routes
    service.ai_consent_required = not local_devices
    def guard_start(task):
        if not local_devices:
            try:
                with store.connection() as db:
                    principal = db.execute('SELECT owner_scope FROM task_principals WHERE task_id=?', (task['id'],)).fetchone()
                if not principal:
                    raise ConsentError('ai_consent_private_owner_required', 403)
                ConsentBook(settings.data_dir).require(task['identity_id'], actor=principal[0])
            except ConsentError as error:
                raise TaskError(str(error)) from error
        goals.guard(task)
        schedules.guard(task)
        if usage.enabled:
            try:
                if task['identity_id'] == DEFAULT_IDENTITY and service.hermes.http.base_url.__str__().rstrip('/') != (runtime.status().get('url') or '').rstrip('/'):
                    raise UsageError('quota_provider', '试用只允许使用已接入额度管理的 Pajio 执行引擎，请先连接内置引擎。')
                usage.check('model')
            except UsageError as error:
                # Coordinators persist TaskError as a blocked/retryable reason;
                # a quota refusal must not escape the poll loop or lose a draft.
                raise TaskError(error.detail) from error
    service.start_guard = guard_start
    runtime = HermesRuntime(settings.data_dir, local_devices=local_devices)
    identity_runtimes = {}
    identity_clients = {}

    def runtime_for(identity_id):
        store.identity(identity_id)
        if identity_id == DEFAULT_IDENTITY:
            return runtime
        if identity_id not in identity_runtimes:
            identity_runtimes[identity_id] = HermesRuntime(settings.data_dir, identity_id, local_devices=local_devices)
        return identity_runtimes[identity_id]

    async def identity_client(identity_id):
        if identity_id == DEFAULT_IDENTITY:
            return service.hermes
        engine = runtime_for(identity_id)
        if identity_id in identity_clients and engine.status()["running"]:
            return identity_clients[identity_id]
        try:
            # Only one extra identity process is kept warm. Runs are globally
            # serialized by TaskService; their identity never depends on a tab.
            for other_id, other in identity_runtimes.items():
                if other_id != identity_id:
                    await other.stop()
            connection = await engine.start()
        except RuntimeError as error:
            raise TaskError(str(error)) from error
        client = HermesClient(Settings(settings.data_dir, connection["url"], connection["key"], settings.poll_seconds))
        old = identity_clients.get(identity_id)
        identity_clients[identity_id] = client
        if old:
            await old.close()
        return client

    service.client_resolver = identity_client
    if not local_devices:
        from .cloud.relay import instance_relay
        service.desktop_relay=lambda:instance_relay(settings.data_dir.parent)
    token = secrets.token_urlsafe(32)

    async def poll():
        while True:
            await asyncio.sleep(settings.poll_seconds)
            try:
                await service.tick()
                await schedule_coordinator.tick()
                await goal_coordinator.tick()
                capture_worker.tick(busy=any(t['status'] in ACTIVE for t in store.list()))
                await asyncio.to_thread(identity_exports.purge_expired)
            except Exception as error:
                # Keep recovery alive; avoid logging private prompts or receipts.
                logging.getLogger(__name__).error("Background recovery failed: %s", type(error).__name__)

    @asynccontextmanager
    async def lifespan(app):
        if engine_autostart and runtime.status()["installed"]:
            try:
                await attach_local_engine()
            except RuntimeError:
                logging.getLogger(__name__).warning("Managed engine needs configuration or recovery")
        service.recover_startup()
        capture_worker.start()
        messaging.start()
        notification_stop = asyncio.Event()
        notification_worker = asyncio.create_task(notifications.run(notification_stop))
        health_stop = asyncio.Event()
        health_task = asyncio.create_task(health_monitor.run(health_stop))
        worker = asyncio.create_task(poll())
        app.state.recovery_task = worker
        app.state.notification_task = notification_worker
        app.state.notification_stop = notification_stop
        app.state.health_task = health_task
        try:
            yield
        finally:
            health_stop.set()
            health_task.cancel()
            with suppress(asyncio.CancelledError):
                await health_task
            worker.cancel()
            with suppress(asyncio.CancelledError):
                await worker
            notification_stop.set()
            with suppress(asyncio.CancelledError):
                await notification_worker
            await notifications.close()
            await capture_worker.close()
            await cloud_apps.close()
            await messaging.close()
            workspace_pager.close()
            await service.hermes.close()
            for task in (app.state.files_task, app.state.phone_task, app.state.computer_task):
                if task and not task.done():
                    task.cancel()
                    with suppress(asyncio.CancelledError):
                        await task
            await runtime.close()
            for client in identity_clients.values():
                await client.close()
            for engine in identity_runtimes.values():
                await engine.close()

    app = FastAPI(title="Pajio", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.service = service
    app.state.store = store
    app.state.usage = usage
    install_usage_routes(app, usage)
    install_consent_routes(app, settings.data_dir, local_devices=local_devices)
    from .speech_api import install_speech_routes
    install_speech_routes(app, store, token, settings.data_dir, browser_origin)
    install_artifact_routes(app, artifacts, local_devices=local_devices)
    install_life_routes(app, life)
    from .onboarding_api import install_onboarding_routes
    app.state.onboarding = onboarding
    install_onboarding_routes(app, onboarding, local_devices=local_devices)
    from .chat_imports_api import install_chat_import_routes
    install_chat_import_routes(app, chat_imports, local_devices=local_devices)
    from .bookmark_api import install_bookmark_routes
    install_bookmark_routes(app, life)
    from .task_lists import install_task_list_routes
    install_task_list_routes(app, life)
    from .calendar_series import CalendarSeriesBook
    from .calendar_series_api import install_calendar_series_routes
    install_calendar_series_routes(app, CalendarSeriesBook(store))
    install_schedule_routes(app, schedules, local_devices=local_devices)
    install_activity_routes(app, ActivityBook(store, require_owner=not local_devices))
    app.state.schedules = schedules
    app.state.schedule_coordinator = schedule_coordinator
    install_capture_routes(app,captures,capture_worker)
    app.state.captures = captures
    app.state.capture_worker = capture_worker
    app.state.goals = goals
    app.state.goal_coordinator = goal_coordinator
    app.state.runtime = runtime
    app.state.identity_runtimes = identity_runtimes
    app.state.identity_clients = identity_clients
    from .workspace_upload import install_workspace_import_routes
    install_workspace_import_routes(app, store, runtime_for)
    from .workspace_api import install_workspace_page_routes
    workspace_pager = install_workspace_page_routes(app, store, runtime_for)
    from .workspace_text import install_workspace_text_routes
    install_workspace_text_routes(app, store, runtime_for)
    from .identity_export import IdentityExports
    from .identity_export_api import install_identity_export_routes
    identity_exports = IdentityExports(store)
    app.state.identity_exports = identity_exports
    install_identity_export_routes(app, identity_exports, local_devices=local_devices)
    from .skills_api import install_skill_routes
    install_skill_routes(app, runtime_for)
    from .briefing_api import install_briefing_routes
    from .cloud_apps import CloudApps
    from .cloud_apps_api import install_cloud_app_routes
    cloud_apps = CloudApps(store)
    app.state.cloud_apps = cloud_apps
    briefings = install_briefing_routes(app, store, service, artifacts, cloud_apps=cloud_apps, local_devices=local_devices)
    from .briefing_automation_api import install_briefing_automation_routes
    install_briefing_automation_routes(app, store, briefings, schedules, local_devices=local_devices)
    install_cloud_app_routes(app, cloud_apps)
    from .messaging import MessagingBridge
    from .messaging_api import install_messaging_routes
    messaging = MessagingBridge(store, service)
    app.state.messaging = messaging
    install_messaging_routes(app, messaging)
    from .notifications import NotificationService
    from .notifications_api import install_notification_routes
    notifications = NotificationService(store)
    app.state.notifications = notifications
    install_notification_routes(app, notifications)
    from .record_reminders_api import install_record_reminder_routes
    install_record_reminder_routes(app, notifications.reminders, local_devices=local_devices)
    from .native_actions import NativeActions
    from .native_actions_api import install_native_action_routes
    native_actions = NativeActions(store, require_task_owner=not local_devices)
    app.state.native_actions = native_actions
    install_native_action_routes(app, native_actions)
    from .native_sync import NativeSyncBook
    from .native_sync_api import install_native_sync_routes
    install_native_sync_routes(app, NativeSyncBook(store), local_devices=local_devices)
    from .confirmation_api import install_confirmation_routes
    install_confirmation_routes(app, service, task_view, local_devices=local_devices)
    from .search import SearchBook
    from .search_api import install_search_routes
    install_search_routes(app, SearchBook(store), local_devices=local_devices)
    from .conversation_sources import ConversationSources
    from .conversation_sources_api import install_conversation_source_routes
    install_conversation_source_routes(app, ConversationSources(store), local_devices=local_devices)
    from .diagnostics_api import install_diagnostic_routes
    async def diagnostic_probe(identity_id):
        client = service.hermes if identity_id == DEFAULT_IDENTITY else identity_clients.get(identity_id)
        return await client.probe() if client else {"state": "not_observed"}
    install_diagnostic_routes(app, store, runtime_for, probe_for=diagnostic_probe,
                              devices_for=(lambda identity: service.desktop_relay().inventory(identity)) if not local_devices else None,
                              deployment="local" if local_devices else "cloud", require_owner=not local_devices)
    from .health_history import HealthHistory, HealthMonitor
    from .health_history_api import install_health_history_routes
    health_history = HealthHistory(store, require_owner=not local_devices)
    health_monitor = HealthMonitor(health_history, app.state.diagnostics, deployment="local" if local_devices else "cloud")
    app.state.health_history = health_history
    app.state.health_monitor = health_monitor
    app.state.health_task = None
    install_health_history_routes(app, health_history, health_monitor)
    app.state.files_task = None
    app.state.phone_task = None
    app.state.computer_task = None
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts if allowed_hosts is not None else ["localhost", "127.0.0.1", "[::1]", "testserver"])

    @app.middleware("http")
    async def local_access(request: Request, call_next):
        origin = request.headers.get("origin")
        if origin and (origin != browser_origin if browser_origin is not None else urlparse(origin).netloc != request.headers.get("host")):
            return JSONResponse({"detail": "只接受本地 Pajio 页面发起的请求。"}, status_code=403)
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            if not secrets.compare_digest(request.headers.get("x-wearing-token", ""), token):
                return JSONResponse({"detail": "页面会话已失效，请刷新后重试。"}, status_code=403)
        if request.url.path.startswith("/api/"):
            header_id, query_id = request.headers.get("x-wearing-identity"), request.query_params.get("identity")
            if header_id and query_id and header_id != query_id:
                return JSONResponse({"detail": "请求中的身份不一致，请刷新后再试。"}, status_code=409)
            request.state.identity_id = header_id or query_id or DEFAULT_IDENTITY
            try:
                store.identity(request.state.identity_id)
            except IdentityError as error:
                return JSONResponse({"detail": str(error)}, status_code=404)
            path = request.url.path
            if request.state.identity_id != DEFAULT_IDENTITY and (
                path.startswith(("/api/phone", "/api/computer", "/api/doctor", "/api/device-report", "/api/connection", "/api/model"))
                or (request.method != "GET" and path.startswith(("/api/runtime", "/api/workspace/enable")))
            ):
                return JSONResponse({"detail": "这项连接当前属于日常身份。新身份的设备和账户尚未接入。"}, status_code=409)
            if path.startswith("/api/tasks/"):
                task = store.get(path.split("/")[3])
                if not task or task["identity_id"] != request.state.identity_id:
                    return JSONResponse({"detail": "当前身份中没有这件事，请切回原身份。"}, status_code=404)
                try:
                    actor = request_owner(request, local_devices=local_devices)
                except HTTPException as error:
                    return JSONResponse({"detail": error.detail}, status_code=error.status_code)
                with store.connection() as db:
                    permitted = task_visible(db, request.state.identity_id, task['id'], actor)
                if not permitted:
                    return JSONResponse({"detail": "这次任务不属于当前账户。"}, status_code=404)
            if not local_devices and path.startswith("/api/confirmations/"):
                with store.connection() as db:
                    principal = db.execute("SELECT p.owner_scope FROM durable_confirmations d JOIN task_principals p ON p.task_id=d.task_id WHERE d.id=?", (path.split("/")[3],)).fetchone()
                if principal and principal[0] != request.scope.get("pajio.storage_scope"):
                    return JSONResponse({"detail": "这次确认不属于当前账户。"}, status_code=404)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers.setdefault("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(UsageError)
    async def usage_error(request, error):
        return JSONResponse({"detail": error.detail, "code": error.code}, status_code=429)

    @app.exception_handler(TaskError)
    async def task_error(request, error):
        return JSONResponse({"detail": str(error)}, status_code=409)

    @app.exception_handler(IdentityError)
    async def identity_error(request, error):
        return JSONResponse({"detail": str(error)}, status_code=422)

    @app.exception_handler(GoalError)
    async def goal_error(request, error):
        return JSONResponse({"detail": str(error)}, status_code=409)

    @app.exception_handler(MessageConflict)
    async def message_conflict(request, error):
        return JSONResponse({"detail": str(error)}, status_code=409)

    @app.exception_handler(RegistryError)
    @app.exception_handler(RuntimeError)
    async def runtime_error(request, error):
        return JSONResponse({"detail": str(error)}, status_code=409)

    @app.exception_handler(RequestValidationError)
    async def invalid_input(request, error):
        # Validation errors may contain credential values; return only field names.
        fields = sorted({str(item["loc"][-1]) for item in error.errors()})
        return JSONResponse({"detail": "请检查输入字段：" + "、".join(fields)}, status_code=422)

    @app.get("/api/bootstrap")
    async def bootstrap(request: Request):
        return {"token": token, "version": "0.2.0", "default_identity_id": DEFAULT_IDENTITY, "identities": store.identities(), "hermes_url": service.hermes.http.base_url.__str__().rstrip("/"),
                "configured": service.hermes.configured, "deployment": "local" if local_devices else "cloud",
                "storage_scope": request.scope.get("pajio.storage_scope"),
                "goal_policy": {"default_steps": DEFAULT_GOAL_STEPS, "max_steps": MAX_GOAL_STEPS, "extension_steps": GOAL_EXTENSION_STEPS}}

    @app.get("/api/devices")
    async def remote_devices(request: Request):
        if local_devices:
            raise HTTPException(409, "本机设备请从电脑与手机连接器管理。")
        from .cloud.relay import instance_relay
        return {"devices": instance_relay(settings.data_dir.parent).inventory(request.state.identity_id)}

    from .cloud.relay import ResourceControl, RelayError
    from .cloud.device_setup import DeviceOffer, PairDevices, create_pairing, download_pairing
    from .cloud.device_permissions import ChangePermission, create_permission, read_permission
    from .cloud.relay import DeviceReview
    from .cloud.desktop_approval import InputDecision, list_proposals, decide

    def cloud_relay():
        if local_devices:
            raise HTTPException(409, "请在云端 Pajio 的设备设置里接入。")
        from .cloud.relay import instance_relay
        return instance_relay(settings.data_dir.parent)

    from .device_access_api import install_device_access_routes
    install_device_access_routes(app, cloud_relay, local_devices=local_devices)
    from .cloud.device_files import install_device_file_routes
    install_device_file_routes(app, store, runtime_for, cloud_relay)

    def device_error(error):
        copy = {'resource_already_paired':'这里有已接入的设备，请取消选择后再继续。',
                'pairing_request_changed':'接入选择有变化，请重新生成配对文件。',
                'pairing_expired':'配对文件已过期，请重新生成。',
                'command_not_found':'当前身份没有这条设备记录。',
                'review_changed':'操作记录刚有变化，请重新查看后核对。',
                'device_review_required':'请确认已查看设备，并写下具体核对结果。',
                'device_not_ready_for_review':'先等旧动作结束、设备重新在线，再核对。'}
        copy.update({'desktop_approval_changed':'这一步已经处理、过期或设备发生变化。请重新查看。',
                     'desktop_approval_required':'这次动作没有有效的任务授权。',
                     'previous_action_needs_review':'先核对旧动作的结果，再进行新操作。'})
        copy.update({'permission_changed':'设备权限刚有变化，请重新查看后再生成。',
            'permission_unchanged':'已经是这个权限，无需更新。',
            'permission_device_busy':'先等设备操作完成、核对旧动作的结果，再调整权限。',
            'permission_expired':'变更文件已过期或已完成，请重新查看设备。',
            'permission_request_changed':'这次变更的选择有变化，请重新生成。',
            'permission_not_found':'当前身份没有这次权限变更。'})
        return HTTPException(error.status, copy.get(error.code, '设备接入暂未完成，请重新查看。'))

    @app.post('/api/devices/offer')
    async def inspect_device_offer(request: Request, body: DeviceOffer):
        relay = cloud_relay()
        paired = {r['resource_id'] for r in relay.inventory(request.state.identity_id)}
        # Other identities' names/scopes are never disclosed. Duplicate binding is
        # still rejected atomically at pairing time.
        return {'resources':[{**r.model_dump(mode='json'), 'already_paired':r.resource_id in paired}
                             for r in body.resources]}

    @app.post('/api/devices/pair')
    async def pair_devices(request: Request, body: PairDevices):
        relay = cloud_relay()
        try:
            bundle = create_pairing(relay, settings.data_dir.parent, request.state.identity_id, body)
            write_private_json(settings.data_dir / 'remote-devices.json', {'schema_version':1,'enabled':True})
            return {'bundle':bundle, 'expires_in':600}
        except RelayError as error:
            raise device_error(error) from error
        except (OSError, ValueError):
            raise HTTPException(409, '设备入口还未配置，请先完成云端设备入口设置。')

    @app.get('/api/devices/reviews')
    async def device_reviews(request: Request):
        return {'reviews':cloud_relay().reviews(request.state.identity_id)}

    @app.post('/api/devices/permissions')
    async def change_device_permission(request: Request, body: ChangePermission):
        try:
            bundle=create_permission(cloud_relay(),settings.data_dir.parent,request.state.identity_id,body)
            return {'request_id':bundle['request_id'],'expires_in':600,'policy_revision':bundle['policy_revision']}
        except RelayError as error:raise device_error(error) from error
        except (OSError,ValueError):raise HTTPException(409,'设备入口还未配置，暂时无法调整权限。')

    @app.get('/api/devices/permissions/{request_id}')
    async def permission_status(request: Request, request_id: str):
        try:return read_permission(cloud_relay(),request.state.identity_id,request_id)
        except RelayError as error:raise device_error(error) from error

    @app.get('/api/devices/permissions/{request_id}/download')
    async def permission_download(request: Request, request_id: str):
        try:
            bundle=read_permission(cloud_relay(),request.state.identity_id,request_id,download=True)
            return JSONResponse(bundle,headers={'Content-Disposition':'attachment; filename="wearing-permissions.json"'})
        except RelayError as error:raise device_error(error) from error

    @app.get('/api/devices/input-approvals')
    async def desktop_approvals(request: Request):
        relay=cloud_relay()
        return {'approvals':list_proposals(relay,request.state.identity_id),
                'computers':[r for r in relay.inventory(request.state.identity_id) if r['kind']=='computer']}

    @app.post('/api/devices/input-approvals')
    async def desktop_decision(request: Request, body: InputDecision):
        try:
            from .cloud.desktop_runs import pending_decision
            relay=cloud_relay()
            waiter=pending_decision(relay,request.state.identity_id,body)
            if waiter:
                await service.refresh(waiter['task'])
                await service.approve(waiter['task'],waiter['request'],body.choice)
                return {'approval_id':body.approval_id,'state':'decision_sent'}
            return decide(relay,request.state.identity_id,body)
        except RelayError as error:raise device_error(error) from error

    @app.get('/api/devices/pair/{request_id}/download')
    async def download_device_pairing(request: Request, request_id: str):
        try:
            bundle = download_pairing(cloud_relay(), request.state.identity_id, request_id)
            return JSONResponse(bundle, headers={'Content-Disposition':'attachment; filename="wearing-pair.json"'})
        except RelayError as error:
            raise device_error(error) from error

    @app.post('/api/devices/reviews')
    async def review_device(request: Request, body: DeviceReview):
        try:
            return cloud_relay().review(request.state.identity_id, body)
        except RelayError as error:
            raise device_error(error) from error

    @app.post('/api/devices/refresh-tools')
    async def refresh_device_tools(request: Request):
        cloud_relay()
        async with service.lock:
            require_idle()
            engine = runtime_for(request.state.identity_id)
            await engine.stop()
            if request.state.identity_id == DEFAULT_IDENTITY:
                await attach_local_engine()
            else:
                await identity_client(request.state.identity_id)
            return {'message':'设备能力已更新，可以继续对话。'}

    @app.post("/api/devices/control")
    async def control_remote_device(request: Request, body: ResourceControl):
        if local_devices:
            raise HTTPException(409, "本机设备请从电脑与手机连接器管理。")
        from .cloud.relay import instance_relay
        try:
            return instance_relay(settings.data_dir.parent).control(request.state.identity_id, body)
        except RelayError as error:
            copy = {"resource_not_paired": "当前身份没有接入这台设备。", "control_changed": "设备状态刚有变化，请刷新后重试。",
                    "human_session_requires_explicit_return": "设备仍处于私密接管后的暂停状态。请先查看画面并明确交还，不能直接恢复助手操作。"}
            raise HTTPException(error.status, copy.get(error.code, "设备设置暂未完成，请重新查看。")) from error

    @app.get("/api/identities")
    async def identities():
        return store.identities()

    @app.post("/api/identities", status_code=201)
    async def new_identity(body: IdentityProfile):
        return store.save_identity(**body.model_dump())

    @app.patch("/api/identities/{identity_id}")
    async def edit_identity(identity_id: str, body: IdentityProfile):
        return store.save_identity(**body.model_dump(), identity_id=identity_id)

    @app.get("/api/identity")
    async def identity_detail(request: Request):
        identity_id = request.state.identity_id
        devices = []
        if not local_devices and (settings.data_dir / "remote-devices.json").exists():
            from .cloud.relay import instance_relay
            devices = [{"id": r["resource_id"], "name": r["name"], "kind": "phone" if r["kind"] == "android" else "computer",
                        "online": r["online"], "connection": "remote"}
                       for r in instance_relay(settings.data_dir.parent).inventory(identity_id)]
        elif local_devices and identity_id == DEFAULT_IDENTITY:
            if computer.enrolled(settings.data_dir):
                devices.append({"id": "computer_local", "name": "这台电脑", "kind": "computer"})
            for rid, device in mobile.registry(settings.data_dir)["devices"].items():
                devices.append({"id": rid, "name": device.get("name", "Android 手机"), "kind": "phone"})
        return {**store.identity(identity_id), "devices": devices,
                "workspace": str(runtime_for(identity_id).workspace),
                "contacts": {"phone": "not_connected", "email": "not_connected"},
                "payments": "not_connected", "accounts": "not_connected",
                "isolation": "profile", "shared": ["model_credentials"],
                "device_assignment": "default_only"}

    @app.get("/api/status")
    async def status(request: Request):
        identity_id = request.state.identity_id
        client = service.hermes if identity_id == DEFAULT_IDENTITY else identity_clients.get(identity_id) if runtime_for(identity_id).status()["running"] else None
        probe = await client.probe() if client else {"state": "ready" if runtime.status()["installed"] else "not_configured", "message": "发送消息时会启动此身份的独立引擎。", "features": {}}
        other_active = [{"identity_id": t["identity_id"], "name": store.identity(t["identity_id"])["name"], "status": t["status"]}
                        for t in store.list() if t["status"] in ACTIVE and t["identity_id"] != identity_id]
        return {"hermes": probe, "identity_id": identity_id, "other_active": other_active, "target_order": ["computer", "phone", "sandbox"],
                "device_report": store.setting("device_report") if identity_id == DEFAULT_IDENTITY else None,
                "limits": {"device_control_validated": False, "cloud_enabled": not local_devices, "parallel_runs": False}}

    @app.get("/api/tasks")
    async def tasks(request: Request):
        owner = request_owner(request, local_devices=local_devices)
        with store.connection() as db:
            visible = visible_task_ids(db, request.state.identity_id, owner)
        return [task_view(t) for t in store.list(request.state.identity_id) if t['id'] in visible]

    @app.get("/api/goals")
    async def list_goals(request: Request):
        return goals.list(request.state.identity_id, owner_scope=request_owner(request, local_devices=local_devices))

    @app.get("/api/goal-updates")
    async def goal_updates(request: Request):
        return goals.updates(request.state.identity_id, owner_scope=request_owner(request, local_devices=local_devices))

    @app.post("/api/goal-updates/seen")
    async def seen_goal_updates(body: SeenGoalUpdates, request: Request):
        return goals.acknowledge_updates(request.state.identity_id, body.ids, owner_scope=request_owner(request, local_devices=local_devices))

    @app.get("/api/memory")
    async def memory(request: Request):
        identity_id = request.state.identity_id
        client = service.hermes if identity_id == DEFAULT_IDENTITY else identity_clients.get(identity_id) if runtime_for(identity_id).status()["running"] else None
        if client is None:
            return {"available": False, "message": "这个身份的执行引擎还未启动；发送消息后再来看看。", "identity_id": identity_id}
        try:
            return {**await client.memories(), "identity_id": identity_id}
        except HermesError:
            return {"available": False, "message": "暂时读不到这个身份的记忆。请检查连接，原记录仍保留。", "identity_id": identity_id}

    @app.patch("/api/memory")
    async def change_memory(request: Request):
        identity_id = request.state.identity_id
        client = service.hermes if identity_id == DEFAULT_IDENTITY else identity_clients.get(identity_id) if runtime_for(identity_id).status()["running"] else None
        if client is None:
            raise HTTPException(409, "当前身份的执行引擎尚未启动，请连接后重试。")
        try:
            body = await request.json()
        except (ValueError, UnicodeDecodeError) as error:
            raise HTTPException(422, "记忆修改格式无效。") from error
        if not isinstance(body, dict) or len(json.dumps(body)) > 100000:
            raise HTTPException(422, "记忆修改格式无效。")
        try:
            return {**await client.change_memory(body), "identity_id": identity_id}
        except HermesError as error:
            raise HTTPException(getattr(error, "status", 503), str(error)) from error

    @app.post("/api/goals", status_code=201)
    async def new_goal(body: NewGoal, request: Request):
        values = body.model_dump()
        for key in ("objective", "boundaries", "success_criteria"):
            values[key] = values[key].strip()
            if len(values[key]) < 2:
                raise HTTPException(422, "请写清目标、允许的范围和阶段结果。")
        return goals.create(request.state.identity_id, **values, owner_scope="local" if local_devices else request.scope.get("pajio.storage_scope"))

    @app.get("/api/goals/{goal_id}")
    async def goal_detail(goal_id: str, request: Request):
        return goals.detail(goal_id, request.state.identity_id, owner_scope=request_owner(request, local_devices=local_devices))

    @app.post("/api/goals/{goal_id}/control")
    async def goal_control(goal_id: str, body: GoalControl, request: Request):
        note = body.note.strip()
        if body.action in {"note", "complete"} and len(note) < 3:
            raise HTTPException(422, "请写下具体补充或核对结果。")
        if body.add_steps and body.action != "resume":
            raise HTTPException(422, "只有明确继续时才能增加轮次。")
        return await goal_coordinator.control(goal_id, request.state.identity_id, body.revision, body.action, note, body.add_steps,
                                              owner_scope="local" if local_devices else request.scope.get("pajio.storage_scope"))

    @app.get("/api/runtime")
    async def runtime_status(request: Request):
        engine = runtime_for(request.state.identity_id)
        if request.state.identity_id == DEFAULT_IDENTITY:
            await engine.inspect_model()
        return engine.status()

    @app.post("/api/runtime/install", status_code=202)
    async def runtime_install():
        if any(task and not task.done() for task in (app.state.files_task, app.state.phone_task, app.state.computer_task)):
            raise TaskError("连接器正在准备，请稍候。")
        return runtime.begin_install()

    def require_idle():
        if any(t["status"] in ACTIVE for t in store.list()):
            raise TaskError("请先结束当前对话中的操作，再更改设置。")
        if runtime.install_task and not runtime.install_task.done():
            raise TaskError("运行环境正在准备，请稍候。")

    async def attach_local_engine():
        connection = await runtime.start()
        candidate = HermesClient(Settings(settings.data_dir, connection["url"], connection["key"], settings.poll_seconds))
        try:
            write_private_json(settings.data_dir / "connection.json", connection)
        except OSError as error:
            await candidate.close()
            await runtime.stop()
            raise RuntimeError("连接配置无法保存，本次引擎已关闭。请检查数据目录的写入权限。") from error
        old, service.hermes = service.hermes, candidate
        await old.close()

    @app.get("/api/phone")
    async def phone_status():
        return await runtime.phone_status()

    @app.get("/api/computer")
    async def computer_status():
        return await runtime.computer_status()

    @app.post("/api/computer/refresh")
    async def refresh_computer():
        return await runtime.computer_status(force=True)

    @app.post("/api/computer/prepare", status_code=202)
    async def prepare_computer():
        if app.state.computer_task and not app.state.computer_task.done():
            return runtime.status()["computer"]
        async with service.lock:
            require_idle()
            if runtime.lock.locked():
                raise RuntimeError("运行环境正在准备，请稍候。")
            runtime.computer_phase, runtime.computer_error = "installing", None
            async def install():
                try:
                    await runtime.install_computer()
                except RuntimeError:
                    pass
            app.state.computer_task = asyncio.create_task(install())
            return runtime.status()["computer"]

    @app.post("/api/computer/permissions")
    async def computer_permissions():
        # Opens the OS prompt; cannot grant TCC permissions itself.
        await runtime.computer_command("permissions", timeout=35)
        return {"message": "请在系统设置中完成 CuaDriver 授权，然后重新检测。"}

    @app.post("/api/computer/bind")
    async def bind_computer():
        async with service.lock:
            require_idle()
            await runtime.bind_computer()
            if runtime.status()["running"] and not runtime.status()["computer"]["active"]:
                await runtime.stop()
                await attach_local_engine()
            return await runtime.computer_status()

    @app.post("/api/computer/pause")
    async def pause_computer():
        # Independent of the run lock. Upstream fences each input and capture.
        return await runtime.computer_command("takeover")

    @app.post("/api/computer/resume")
    async def resume_computer():
        return await runtime.computer_command("resume")

    @app.post("/api/phone/prepare", status_code=202)
    async def prepare_phone():
        if app.state.phone_task and not app.state.phone_task.done():
            return runtime.status()["phone"]
        async with service.lock:
            require_idle()
            if not runtime.status()["installed"]:
                raise RuntimeError("请先准备 Pajio，再准备手机连接器。")
            if runtime.lock.locked():
                raise RuntimeError("运行环境正在准备，请稍候。")
            runtime.phone_phase, runtime.phone_error = "installing", None

            async def install():
                try:
                    await runtime.install_phone()
                except RuntimeError:
                    pass  # The runtime's explicit failure state is shown in the UI.
            app.state.phone_task = asyncio.create_task(install())
            return runtime.status()["phone"]

    @app.post("/api/phone/bind")
    async def bind_phone(body: PhoneBinding):
        async with service.lock:
            require_idle()
            await runtime.bind_phone(body.serial)
            if runtime.status()["running"] and not runtime.status()["phone"]["active"]:
                await runtime.stop()
                try:
                    await attach_local_engine()
                except RuntimeError as error:
                    raise RuntimeError("手机绑定已保存，但执行引擎未恢复连接。请重新启动引擎。") from error
            return await runtime.phone_status()

    @app.post("/api/phone/pause")
    async def pause_phone(body: PhoneResource):
        # A pause must not wait behind a long model run or hold an action lock.
        runtime.pause_phone(body.resource_id)
        return {"message": "已暂停新的手机操作；已经发出的动作可能仍需片刻返回。"}

    @app.post("/api/phone/resume")
    async def resume_phone(body: PhoneResource):
        async with service.lock:
            require_idle()
            runtime.set_phone_enabled(body.resource_id, True)
            return await runtime.phone_status()

    @app.get("/api/model")
    async def model_settings():
        return await runtime.model_settings()

    @app.post("/api/model")
    async def save_model(body: ModelSettings):
        async with service.lock:
            require_idle()
            for engine in identity_runtimes.values():
                await engine.stop()
            result = await runtime.model_settings({"action": "configure", "provider": body.provider,
                                                   "model": body.model, "key": body.key.get_secret_value()})
            if runtime.status()["running"]:
                await runtime.stop()
                try:
                    await attach_local_engine()
                except RuntimeError as error:
                    raise RuntimeError("模型设置已保存，但引擎未重新连接。请点击启动并连接后再试。") from error
            return {**result, "message": "模型设置已保存。实际调用情况以接下来的对话为准。"}

    @app.post("/api/workspace/enable", status_code=202)
    async def enable_workspace():
        if app.state.files_task and not app.state.files_task.done():
            return runtime.status()["files"]
        async with service.lock:
            require_idle()
            if not runtime.status()["installed"]:
                raise RuntimeError("请先准备 Pajio，再启用文件空间。")
            runtime.files_phase, runtime.files_error = "installing", None

            async def prepare_files():
                async with service.lock:
                    # Keep new submissions queued while the engine environment changes.
                    was_running = runtime.status()["running"]
                    try:
                        require_idle()
                        await runtime.stop()
                        await runtime.install_filesystem()
                        if was_running:
                            await attach_local_engine()
                    except (RuntimeError, TaskError) as error:
                        runtime.files_phase, runtime.files_error = "failed", str(error)
                    except Exception:
                        runtime.files_phase, runtime.files_error = "failed", "文件能力准备未完成，可重试；详细信息保存在本机安装日志。"
            app.state.files_task = asyncio.create_task(prepare_files())
            return runtime.status()["files"]

    @app.get("/api/workspace")
    async def files(request: Request):
        engine = runtime_for(request.state.identity_id)
        try:
            return {**await asyncio.to_thread(list_files, engine.workspace), "capability": engine.status()["files"]}
        except WorkspaceError as error:
            raise HTTPException(409, str(error)) from error

    @app.get("/api/workspace/file")
    async def download_file(path: str, request: Request):
        try:
            file = workspace_file(runtime_for(request.state.identity_id).workspace, path)
            return FileResponse(file, filename=file.name, media_type="application/octet-stream")
        except WorkspaceError as error:
            raise HTTPException(404, str(error)) from error

    @app.post("/api/runtime/start")
    async def runtime_start():
        async with service.lock:
            if any(t["status"] in ACTIVE for t in store.list()):
                raise TaskError("请先处理当前运行，再切换到本地引擎。")
            await attach_local_engine()
            return runtime.status()

    @app.post("/api/runtime/stop")
    async def runtime_stop():
        async with service.lock:
            if any(t["status"] in ACTIVE for t in store.list()):
                raise TaskError("请先在对话里停止并核对当前操作，再关闭引擎。")
            return await runtime.stop()

    @app.get("/api/conversation")
    async def conversation(request: Request):
        owner = request_owner(request, local_devices=local_devices)
        with store.connection() as db:
            visible = visible_task_ids(db, request.state.identity_id, owner)
        messages = [{**message, "turn": task_view(service.require(message["task_id"]))}
                    for message in store.conversation(request.state.identity_id) if message['task_id'] in visible]
        from .task_presentation import present_messages
        messages = present_messages(store, messages)
        for message in messages:
            message.update(store.message_receipt(message["task_id"]))
            linked = goals.message_for(message["task_id"])
            if linked:
                message.update(goal_id=linked["goal_id"], goal_title=linked["objective"], goal_mode=linked["mode"])
        for goal in goals.list(request.state.identity_id, owner_scope=owner):
            for step in goals.detail(goal["id"], owner_scope=owner)["steps"]:
                if step['task_id'] not in visible:
                    continue
                task = task_view(service.require(step["task_id"]))
                report = step["report"] or (parse_report(task["output"]) if task["status"] in {"completed_unverified", "verified"} else None)
                if report:
                    task["output"] = report["summary"]
                    if report["unknowns"]:
                        task["output"] += "\n\n还未确定：" + "；".join(report["unknowns"])
                    if report["next_step"]:
                        task["output"] += "\n\n建议下一步：" + report["next_step"]
                elif task["status"] in ACTIVE:
                    task["output"] = ""  # Never flash partial report JSON in the conversation.
                messages.append({"id": "goal-" + step["task_id"], "task_id": step["task_id"], "kind": "goal_step",
                                 "goal_id": goal["id"], "content": goal["objective"], "created_at": step["created_at"], "turn": task})
        for message in schedules.conversation(request.state.identity_id):
            if message['task_id'] not in visible:
                continue
            message["turn"] = task_view(message["turn"])
            messages.append(message)
        results_by_task = artifacts.for_conversation(request.state.identity_id, owner_scope=owner)
        decisions_by_task = service.confirmations.for_identity(request.state.identity_id)
        for message in messages:
            message["turn"]["artifacts"] = results_by_task.get(message["task_id"], [])
            message["turn"]["confirmations"] = decisions_by_task.get(message["task_id"], [])
        return sorted(messages, key=lambda m: (m["created_at"], str(m["id"])))

    @app.post("/api/conversation", status_code=201)
    async def send_message(body: NewMessage, request: Request):
        content = body.content.strip()
        if not content:
            raise HTTPException(422, "写点什么，再发给 Pajio。")
        if bool(body.life_record_id) != (body.life_revision is not None) or (body.life_record_id and body.goal_id):
            raise HTTPException(422, "请先选定一条记录，再围绕它继续聊。")
        if body.request_id and (body.life_record_id or body.goal_id):
            raise HTTPException(422, "关联目标或记录的消息暂不支持这项提交标识，请使用原关联入口。")
        if not body.goal_id and not body.life_record_id:
            if body.goal_mode != "discuss" or body.goal_revision is not None:
                raise HTTPException(422, "请先选定要补充的目标。")
            owner_scope = "local" if local_devices else request.scope.get("pajio.storage_scope")
            if not local_devices and owner_scope is not None and (not isinstance(owner_scope, str) or not re.fullmatch(r"[a-f0-9]{64}", owner_scope)):
                raise HTTPException(401, "消息尚未关联当前账户，请重新登录后再试。")
            # A private service preview can still chat without an account.
            # Its unowned task cannot acquire cloud phone authority.
            response = await service.submit_message(content, request.state.identity_id, body.request_id, owner_scope=owner_scope)
            return {**response, "task": task_view(response["task"]), "goal": None}
        if body.life_record_id:
            life.get(request.state.identity_id, body.life_record_id)
        goal = None
        if body.goal_id:
            if body.goal_mode == "note" and (body.goal_revision is None or not 3 <= len(content) <= 2000):
                raise HTTPException(422, "补充请写 3–2000 个字，并先打开目标取得最新状态。")
            task, goal = await goal_coordinator.message(body.goal_id, request.state.identity_id, content, body.goal_mode, body.goal_revision,
                                                        owner_scope="local" if local_devices else request.scope.get("pajio.storage_scope"))
        else:
            if body.goal_mode != "discuss" or body.goal_revision is not None:
                raise HTTPException(422, "请先选定要补充的目标。")
            task = life.create_message(request.state.identity_id, content, body.life_record_id, body.life_revision, owner_scope=request_owner(request, local_devices=local_devices)) if body.life_record_id else store.create_message(content, request.state.identity_id)
        try:
            task = await service.start(task["id"])
            return {"task": task_view(task), "delivery": "submitted", "goal": goal}
        except TaskError as error:
            # A saved message remains explicit and user-recoverable; connection
            # recovery never silently turns old ideas into external actions.
            linked = goals.message_for(task["id"])
            return {"task": task_view(service.require(task["id"])), "delivery": "queued" if linked and linked["queued"] else "saved", "reason": str(error), "goal": goal}

    @app.post("/api/tasks", status_code=201)
    async def create_task(body: NewTask, request: Request):
        prompt = body.prompt.strip()
        if not prompt:
            raise HTTPException(422, "请写下要交代的事情。")
        return task_view(store.create(prompt, body.target, request.state.identity_id, owner_scope=request_owner(request, local_devices=local_devices)))

    @app.get("/api/tasks/{task_id}")
    async def get_task(task_id: str, request: Request):
        task = app.state.activity.detail_snapshot(request.state.identity_id, task_id,
                                                 request_owner(request, local_devices=local_devices))
        if task is None:
            raise HTTPException(404, '当前账户和身份没有这件事。')
        return task_view(task)

    @app.post("/api/tasks/{task_id}/start")
    async def start_task(task_id: str):
        return task_view(await service.start(task_id))

    @app.post("/api/tasks/{task_id}/cancel-message")
    async def cancel_message(task_id: str, request: Request):
        scope = {"owner_scope": request.scope.get("pajio.storage_scope")} if not local_devices else {}
        return task_view(await service.cancel_message(task_id, identity_id=request.state.identity_id, **scope))

    @app.post("/api/tasks/{task_id}/refresh")
    async def refresh_task(task_id: str):
        return task_view(await service.refresh(task_id))

    @app.post("/api/tasks/{task_id}/stop")
    async def stop_task(task_id: str):
        return task_view(await service.stop(task_id))

    @app.post("/api/tasks/{task_id}/approval")
    async def approval(task_id: str, body: Approval):
        return task_view(await service.approve(task_id, body.request_id, body.choice))

    @app.post("/api/tasks/{task_id}/verify")
    async def verify(task_id: str, body: Verification):
        note = body.note.strip()
        if len(note) < 3:
            raise HTTPException(422, "请说明核对了什么结果。")
        return task_view(await service.verify(task_id, note))

    @app.post("/api/tasks/{task_id}/resolve")
    async def resolve(task_id: str, body: Verification):
        if len(body.note.strip()) < 5:
            raise HTTPException(422, "请说明原任务在哪里结束、如何核对。")
        return task_view(await service.resolve(task_id, body.note.strip()))

    @app.post("/api/connection")
    async def connect(body: Connection):
        async with service.lock:
            if any(t["status"] in ACTIVE for t in store.list()):
                raise TaskError("请先核对并结束原服务上的运行，再更换连接。")
            try:
                updated = Settings(settings.data_dir, body.url.strip().rstrip("/"), body.key.strip(), settings.poll_seconds)
            except ValueError as error:
                raise HTTPException(422, str(error)) from error
            candidate = HermesClient(updated)
            probe = await candidate.probe()
            if probe["state"] != "reachable":
                await candidate.close()
                raise TaskError(probe["message"])
            write_private_json(settings.data_dir / "connection.json", {"url": updated.hermes_url, "key": updated.hermes_key})
            old = service.hermes
            service.hermes = candidate
            await old.close()
            return {"message": "已验证并保存 Hermes 连接。", "hermes": probe}

    @app.get("/api/doctor")
    async def doctor():
        return await asyncio.to_thread(inspect_host, True)

    @app.post("/api/device-report")
    async def import_report(request: Request):
        raw = await request.body()
        if len(raw) > 32000:
            raise HTTPException(413, "检测报告过大。")
        import json
        try:
            report = json.loads(raw)
        except ValueError as error:
            raise HTTPException(422, "报告不是有效的 JSON 文件。") from error
        if not isinstance(report, dict) or report.get("schema_version") != 1 or report.get("system") not in {"Darwin", "Windows", "Linux"}:
            raise HTTPException(422, "请使用 Pajio 提供的设备检测脚本生成报告。")
        # Reports are inventory snapshots, never live connection or control evidence.
        try:
            clean = DeviceReport.model_validate(report).model_dump()
        except ValidationError as error:
            raise HTTPException(422, "设备报告字段不完整或格式不正确，请重新运行检测脚本。") from error
        store.set_setting("device_report", clean)
        return {"message": "已保存设备检测报告；实时连接仍需单独验证。"}

    @app.get("/api/device-doctor.py")
    async def device_doctor():
        return FileResponse(Path(__file__).with_name("doctor.py"), filename="wearing-doctor.py", media_type="text/x-python")

    static = Path(__file__).with_name("web")
    app.mount("/assets", StaticFiles(directory=static), name="assets")

    @app.get("/")
    async def index():
        return FileResponse(static / "index.html")

    return app
