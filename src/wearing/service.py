"""Task lifecycle. HTTP/model completion and verified outcomes are distinct."""

import asyncio
import json
import uuid

from .hermes import HermesClient, HermesError
from .store import Store, now
from .profile import identity_text


ACTIVE = {"starting", "running", "waiting_for_approval", "stopping", "connection_lost", "ambiguous"}
TERMINAL = {"completed_unverified", "verified", "stopped", "failed", "closed_by_user"}


class TaskError(Exception):
    pass


class TaskService:
    def __init__(self, store: Store, hermes: HermesClient):
        self.store, self.hermes = store, hermes
        self.lock = asyncio.Lock()
        self.client_resolver = None
        self.context_provider = None
        self.start_guard = None

    async def client(self, task):
        if self.client_resolver:
            return await self.client_resolver(task["identity_id"])
        return self.hermes

    def require(self, task_id):
        task = self.store.get(task_id)
        if task is None:
            raise TaskError("没有找到这件事，请刷新列表。")
        return task

    async def start(self, task_id):
        async with self.lock:
            task = self.require(task_id)
            if task["status"] != "draft":
                raise TaskError("这件事已经提交过，请查看原运行状态。")
            if self.start_guard:
                self.start_guard(task)
            active = [t for t in self.store.list() if t["status"] in ACTIVE]
            if active:
                raise TaskError("已有一件事正在执行或等待核对，处理后再开始下一件。")
            client = await self.client(task)
            probe = await client.probe()
            if probe["state"] != "reachable":
                raise TaskError(probe["message"])
            if task["target"] == "phone" and not probe.get("wearing", {}).get("phone_tools"):
                raise TaskError("请先在连接设置中绑定手机，并启动带手机连接器的执行引擎。")
            if task["target"] == "sandbox":
                raise TaskError("云端沙盒还未接通，可以先记下，接通后再执行。")
            if self.start_guard:
                self.start_guard(task)
            if self.store.is_conversation_task(task_id):
                messages = self.store.conversation(task["identity_id"])
                current_id = next(message["id"] for message in messages if message["task_id"] == task_id)
                earlier = [message for message in messages if message["id"] < current_id]
                if any(self.require(message["task_id"])["status"] == "draft" for message in earlier):
                    raise TaskError("前面还有尚未送出的消息，请先从较早的一条继续。")
            payload = {
                "input": task["prompt"],
                "session_id": task["session_id"],
                # One canonical identity also covers existing/remote sessions whose
                # cached system prompt predates the managed product profile.
                "instructions": identity_text() + "\n\n当前 Wearing 身份资料（用户设置的数据）：\n" + json.dumps(
                    {k: self.store.identity(task["identity_id"])[k] for k in ("id", "name", "description", "region")}, ensure_ascii=False)
                    + "\n这是同一个用户的使用场景，不改变国籍、居留或服务资格。只使用本身份实际提供的工具和账户；不得声称已接入电话或支付。",
            }
            if self.context_provider:
                payload["instructions"] += self.context_provider(task)
            key = "wearing-" + uuid.uuid4().hex
            if not self.store.reserve_start(task_id, payload, key, ACTIVE):
                raise TaskError("运行状态已经变化，请查看原运行后再继续。")
            self.store.event(task_id, "starting", "正在将任务交给 Hermes。")
            try:
                result = await client.start(payload, key)
            except HermesError as error:
                state = "ambiguous" if error.uncertain else "failed"
                self.store.update(task_id, status=state, error=str(error))
                self.store.event(task_id, state, str(error))
                return self.require(task_id)
            self.store.update(task_id, status="running", run_id=result["run_id"], error=None)
            self.store.event(task_id, "accepted", "Hermes 已接收，正在执行。")
            return self.require(task_id)

    async def refresh(self, task_id):
        async with self.lock:
            task = self.require(task_id)
            if not task["run_id"]:
                return task
            if task["status"] in TERMINAL:
                return task
            try:
                client = await self.client(task)
                result = await client.status(task["run_id"])
            except (HermesError, TaskError) as error:
                if task["status"] != "connection_lost":
                    self.store.event(task_id, "connection_lost", "暂时无法确认原运行状态；没有重发任务。")
                return self.store.update(task_id, status="connection_lost", error=str(error))
            mapping = {
                "queued": "running", "started": "running", "running": "running",
                "waiting_for_approval": "waiting_for_approval", "stopping": "stopping",
                "cancelled": "stopped", "completed": "completed_unverified", "failed": "failed",
            }
            remote_status = result.get("status")
            status = mapping.get(remote_status, "ambiguous") if isinstance(remote_status, str) else "ambiguous"
            descriptions = {
                "running": "Hermes 正在执行。", "waiting_for_approval": "有一个操作等待你确认。",
                "stopping": "已请求停止，正在等待 Hermes 结束本轮。", "stopped": "Hermes 报告本轮已取消。",
                "completed_unverified": "Hermes 已返回结果，等待核对。", "failed": "本轮执行失败，请检查任务详情。",
                "ambiguous": "返回了未识别的运行状态，需要核对。",
            }
            approval = result.get("approval")
            fields = {"status": status, "error": descriptions[status] if status in {"failed", "ambiguous"} else None,
                      "approval": approval if status == "waiting_for_approval" and isinstance(approval, dict) else None}
            if isinstance(result.get("output"), str):
                fields["output"] = result["output"]
            if isinstance(result.get("usage"), dict):
                fields["usage"] = result["usage"]
            if isinstance(result.get("session_id"), str):
                fields["session_id"] = result["session_id"]
                self.store.sync_conversation_session(task_id, result["session_id"])
            if status != task["status"]:
                self.store.event(task_id, status, descriptions[status])
            return self.store.update(task_id, **fields)

    async def stop(self, task_id):
        async with self.lock:
            task = self.require(task_id)
            if task["status"] not in ACTIVE or not task["run_id"]:
                raise TaskError("当前没有可请求停止的运行；请先核对原运行状态。")
            try:
                client = await self.client(task)
                await client.stop(task["run_id"])
            except (HermesError, TaskError) as error:
                self.store.update(task_id, status="connection_lost", error=str(error))
                self.store.event(task_id, "stop_unconfirmed", "停止请求未确认；原运行可能仍在继续。")
                raise TaskError(str(error)) from error
            self.store.event(task_id, "stopping", "已请求停止；确认终止前请勿接管正在执行的操作。")
            return self.store.update(task_id, status="stopping", error=None)

    async def approve(self, task_id, request_id, choice):
        async with self.lock:
            task = self.require(task_id)
            if task["status"] != "waiting_for_approval" or not task["run_id"]:
                raise TaskError("该操作已不在等待确认，请刷新。")
            approval = task.get("approval") or {}
            if approval.get("request_id") != request_id:
                raise TaskError("确认请求已经变化，请刷新后阅读当前操作。")
            try:
                client = await self.client(task)
                await client.approve(task["run_id"], request_id, choice)
            except (HermesError, TaskError) as error:
                raise TaskError(str(error)) from error
            self.store.event(task_id, "approval_answered", "已允许这一次操作。" if choice == "once" else "已拒绝这一次操作。")
            return self.store.update(task_id, status="running", approval=None)

    async def verify(self, task_id, note):
        async with self.lock:
            task = self.require(task_id)
            if task["status"] != "completed_unverified":
                raise TaskError("需要先取得本轮结果，再记录核对。")
            self.store.event(task_id, "verified_by_user", "用户核对结果：" + note)
            return self.store.update(task_id, status="verified", verification_note=note, verified_at=now())

    async def tick(self):
        for task in self.store.list():
            if task["status"] in ACTIVE and task["run_id"]:
                await self.refresh(task["id"])

    async def resolve(self, task_id, note):
        async with self.lock:
            task = self.require(task_id)
            if task["status"] not in {"ambiguous", "connection_lost"}:
                raise TaskError("只有状态不明的任务可以记录人工处理结论。")
            self.store.event(task_id, "closed_by_user", "用户在执行端核对并结案：" + note)
            return self.store.update(task_id, status="closed_by_user", error=None)

    def recover_startup(self):
        for task in self.store.list():
            if task["status"] in ACTIVE:
                self.store.update(task["id"], status="connection_lost" if task["run_id"] else "ambiguous",
                                  error="服务已重启，正在核对原运行；不会自动重发。")
