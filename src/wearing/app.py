from .mobile import RegistryError
"""Loopback-only control surface. No credentials are returned to the browser."""

import asyncio
import logging
import secrets
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Literal
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
from .store import DEFAULT_IDENTITY, IdentityError, Store, now
from . import computer, mobile
from .workspace import WorkspaceError, list_files, workspace_file
from .goals import GoalBook, GoalCoordinator, GoalError, parse_report


class NewTask(BaseModel):
    prompt: str = Field(min_length=1, max_length=12000)
    target: Literal["computer", "phone", "sandbox"] = "computer"


class NewMessage(BaseModel):
    content: str = Field(min_length=1, max_length=12000)
    goal_id: str | None = Field(default=None, min_length=1, max_length=64)
    goal_mode: Literal["discuss", "note"] = "discuss"
    goal_revision: int | None = Field(default=None, ge=1, strict=True)


class NewGoal(BaseModel):
    objective: str = Field(min_length=2, max_length=2000)
    boundaries: str = Field(min_length=2, max_length=2000)
    success_criteria: str = Field(min_length=2, max_length=2000)
    max_steps: int = Field(default=3, ge=1, le=10, strict=True)
    source_task_id: str | None = Field(default=None, max_length=64)


class GoalControl(BaseModel):
    revision: int = Field(ge=1, strict=True)
    action: Literal["resume", "pause", "cancel", "complete", "note"]
    note: str = Field(default="", max_length=2000)
    add_steps: int = Field(default=0, ge=0, le=10, strict=True)


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
    choice: Literal["once", "deny"]


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


def public_task(task):
    return {key: value for key, value in task.items() if key not in {"payload", "idempotency_key"}}


def create_app(settings: Settings | None = None, hermes: HermesClient | None = None, *,
               allowed_hosts=None, browser_origin=None, engine_autostart=False, local_devices=True):
    settings = settings or Settings.from_env()
    store = Store(settings.data_dir / "wearing.sqlite3")
    service = TaskService(store, hermes or HermesClient(settings))
    goals = GoalBook(store)
    goal_coordinator = GoalCoordinator(goals, service)
    service.context_provider = goals.context
    service.start_guard = goals.guard
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
    token = secrets.token_urlsafe(32)

    async def poll():
        while True:
            await asyncio.sleep(settings.poll_seconds)
            try:
                await service.tick()
                await goal_coordinator.tick()
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
        worker = asyncio.create_task(poll())
        try:
            yield
        finally:
            worker.cancel()
            with suppress(asyncio.CancelledError):
                await worker
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

    app = FastAPI(title="Wearing", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.service = service
    app.state.store = store
    app.state.goals = goals
    app.state.goal_coordinator = goal_coordinator
    app.state.runtime = runtime
    app.state.identity_runtimes = identity_runtimes
    app.state.files_task = None
    app.state.phone_task = None
    app.state.computer_task = None
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts if allowed_hosts is not None else ["localhost", "127.0.0.1", "[::1]", "testserver"])

    @app.middleware("http")
    async def local_access(request: Request, call_next):
        origin = request.headers.get("origin")
        if origin and (origin != browser_origin if browser_origin is not None else urlparse(origin).netloc != request.headers.get("host")):
            return JSONResponse({"detail": "只接受本地 Wearing 页面发起的请求。"}, status_code=403)
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
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(TaskError)
    async def task_error(request, error):
        return JSONResponse({"detail": str(error)}, status_code=409)

    @app.exception_handler(IdentityError)
    async def identity_error(request, error):
        return JSONResponse({"detail": str(error)}, status_code=422)

    @app.exception_handler(GoalError)
    async def goal_error(request, error):
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
    async def bootstrap():
        return {"token": token, "version": "0.2.0", "default_identity_id": DEFAULT_IDENTITY, "identities": store.identities(), "hermes_url": service.hermes.http.base_url.__str__().rstrip("/"),
                "configured": service.hermes.configured}

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
        if identity_id == DEFAULT_IDENTITY:
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
                "limits": {"device_control_validated": False, "cloud_enabled": False, "parallel_runs": False}}

    @app.get("/api/tasks")
    async def tasks(request: Request):
        return [public_task(t) for t in store.list(request.state.identity_id)]

    @app.get("/api/goals")
    async def list_goals(request: Request):
        return goals.list(request.state.identity_id)

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

    @app.post("/api/goals", status_code=201)
    async def new_goal(body: NewGoal, request: Request):
        values = body.model_dump()
        for key in ("objective", "boundaries", "success_criteria"):
            values[key] = values[key].strip()
            if len(values[key]) < 2:
                raise HTTPException(422, "请写清目标、允许的范围和阶段结果。")
        return goals.create(request.state.identity_id, **values)

    @app.get("/api/goals/{goal_id}")
    async def goal_detail(goal_id: str, request: Request):
        return goals.detail(goal_id, request.state.identity_id)

    @app.post("/api/goals/{goal_id}/control")
    async def goal_control(goal_id: str, body: GoalControl, request: Request):
        note = body.note.strip()
        if body.action in {"note", "complete"} and len(note) < 3:
            raise HTTPException(422, "请写下具体补充或核对结果。")
        if body.add_steps and body.action != "resume":
            raise HTTPException(422, "只有明确继续时才能增加轮次。")
        return await goal_coordinator.control(goal_id, request.state.identity_id, body.revision, body.action, note, body.add_steps)

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
                raise RuntimeError("请先准备 Wearing，再准备手机连接器。")
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
                raise RuntimeError("请先准备 Wearing，再启用文件空间。")
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
        messages = [{**message, "turn": public_task(service.require(message["task_id"]))}
                    for message in store.conversation(request.state.identity_id)]
        for message in messages:
            linked = goals.message_for(message["task_id"])
            if linked:
                message.update(goal_id=linked["goal_id"], goal_title=linked["objective"], goal_mode=linked["mode"], queued=bool(linked["queued"]))
        for goal in goals.list(request.state.identity_id):
            for step in goals.detail(goal["id"])["steps"]:
                task = public_task(service.require(step["task_id"]))
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
        return sorted(messages, key=lambda m: (m["created_at"], str(m["id"])))

    @app.post("/api/conversation", status_code=201)
    async def send_message(body: NewMessage, request: Request):
        content = body.content.strip()
        if not content:
            raise HTTPException(422, "写点什么，再发给 Wearing。")
        goal = None
        if body.goal_id:
            if body.goal_mode == "note" and (body.goal_revision is None or not 3 <= len(content) <= 2000):
                raise HTTPException(422, "补充请写 3–2000 个字，并先打开目标取得最新状态。")
            task, goal = await goal_coordinator.message(body.goal_id, request.state.identity_id, content, body.goal_mode, body.goal_revision)
        else:
            if body.goal_mode != "discuss" or body.goal_revision is not None:
                raise HTTPException(422, "请先选定要补充的目标。")
            task = store.create_message(content, request.state.identity_id)
        try:
            task = await service.start(task["id"])
            return {"task": public_task(task), "delivery": "submitted", "goal": goal}
        except TaskError as error:
            # A saved message remains explicit and user-recoverable; connection
            # recovery never silently turns old ideas into external actions.
            linked = goals.message_for(task["id"])
            return {"task": public_task(service.require(task["id"])), "delivery": "queued" if linked and linked["queued"] else "saved", "reason": str(error), "goal": goal}

    @app.post("/api/tasks", status_code=201)
    async def create_task(body: NewTask, request: Request):
        prompt = body.prompt.strip()
        if not prompt:
            raise HTTPException(422, "请写下要交代的事情。")
        return public_task(store.create(prompt, body.target, request.state.identity_id))

    @app.get("/api/tasks/{task_id}")
    async def get_task(task_id: str):
        task = public_task(service.require(task_id))
        task["events"] = store.events(task_id)
        return task

    @app.post("/api/tasks/{task_id}/start")
    async def start_task(task_id: str):
        return public_task(await service.start(task_id))

    @app.post("/api/tasks/{task_id}/cancel-message")
    async def cancel_message(task_id: str):
        async with service.lock:
            with store.connection() as db:
                db.execute("BEGIN IMMEDIATE")
                linked = db.execute("SELECT queued FROM goal_messages WHERE task_id=?", (task_id,)).fetchone()
                changed = db.execute("UPDATE tasks SET status='stopped',updated_at=? WHERE id=? AND status='draft'", (now(), task_id)).rowcount if linked and linked[0] else 0
                if not changed:
                    raise TaskError("这条消息已经送出或没有排队，请查看原运行。")
                db.execute("UPDATE goal_messages SET queued=0,next_retry=NULL WHERE task_id=?", (task_id,))
            store.event(task_id, "message_cancelled", "这条排队消息暂不发送，原话仍保留。")
            return public_task(service.require(task_id))

    @app.post("/api/tasks/{task_id}/refresh")
    async def refresh_task(task_id: str):
        return public_task(await service.refresh(task_id))

    @app.post("/api/tasks/{task_id}/stop")
    async def stop_task(task_id: str):
        return public_task(await service.stop(task_id))

    @app.post("/api/tasks/{task_id}/approval")
    async def approval(task_id: str, body: Approval):
        return public_task(await service.approve(task_id, body.request_id, body.choice))

    @app.post("/api/tasks/{task_id}/verify")
    async def verify(task_id: str, body: Verification):
        note = body.note.strip()
        if len(note) < 3:
            raise HTTPException(422, "请说明核对了什么结果。")
        return public_task(await service.verify(task_id, note))

    @app.post("/api/tasks/{task_id}/resolve")
    async def resolve(task_id: str, body: Verification):
        if len(body.note.strip()) < 5:
            raise HTTPException(422, "请说明原任务在哪里结束、如何核对。")
        return public_task(await service.resolve(task_id, body.note.strip()))

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
            raise HTTPException(422, "请使用 Wearing 提供的设备检测脚本生成报告。")
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
