"""Task lifecycle. HTTP/model completion and verified outcomes are distinct."""

import asyncio
import json
import re
import uuid
from datetime import datetime, timedelta, timezone

from .hermes import HermesClient, HermesError
from .store import Store, now
from .profile import identity_text
from .confirmations import ConfirmationBook


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
        self.desktop_relay = None
        self.confirmations = ConfirmationBook(store)

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
            return await self._start(task_id)

    async def submit_message(self, content, identity_id, request_id=None):
        async with self.lock:
            task, created = self.store.accept_message(content, identity_id, request_id, ACTIVE)
            if created and not self.store.message_receipt(task["id"])["queued"]:
                try:
                    task = await self._start(task["id"])
                except TaskError as error:
                    # A cross-worker admission can become busy while probing.
                    # Initial connection failures alone never acquire queue consent.
                    self.store.queue_if_busy(task["id"], ACTIVE)
                    task = self.require(task["id"])
                    return {"task": task, **self.delivery(task), "reason": str(error)}
            task = self.require(task["id"])
            return {"task": task, **self.delivery(task)}

    def delivery(self, task):
        receipt = self.store.message_receipt(task["id"])
        return {**receipt, "delivery": "queued" if receipt["queued"] else "saved"
                if task["status"] == "draft" or receipt["queue_state"] == "cancelled" else "submitted"}

    async def dispatch_message(self):
        """Dispatch at most one expressly accepted message; not a draft sweeper."""
        async with self.lock:
            if any(task["status"] in ACTIVE for task in self.store.list()):
                return False
            queued = self.store.next_queued_message()
            if not queued:
                return False
            try:
                task = await self._start(queued["task_id"])
                if task["status"] != "draft":
                    self.store.set_setting("last_autodispatch_kind", "message")
                    return True
            except TaskError as error:
                retry = (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat()
                self.store.defer_message(queued["task_id"], str(error), retry)
            return False

    async def cancel_message(self, task_id):
        async with self.lock:
            with self.store.connection() as db:
                db.execute("BEGIN IMMEDIATE")
                queued = any(row["task_id"] == task_id for row in self.store._queued_messages(db))
                changed = db.execute("UPDATE tasks SET status='stopped',updated_at=? WHERE id=? AND status='draft'", (now(), task_id)).rowcount if queued else 0
                if not changed:
                    raise TaskError("这条消息已经送出或没有排队，请查看原运行。")
                db.execute("UPDATE message_handoffs SET state='cancelled',blocked_reason=NULL,next_retry=NULL,updated_at=? WHERE task_id=?", (now(), task_id))
                if db.execute("SELECT 1 FROM sqlite_master WHERE name='goal_messages'").fetchone():
                    db.execute("UPDATE goal_messages SET queued=0,next_retry=NULL WHERE task_id=?", (task_id,))
                db.execute("INSERT INTO events(task_id,kind,message,created_at) VALUES(?,?,?,?)",
                           (task_id, "message_cancelled", "这条排队消息已撤回，原话仍保留。", now()))
            return self.require(task_id)

    async def _start(self, task_id):
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
        tools = probe.get("wearing", {})
        remote_phone = any(name.startswith("mcp__wearing_devices__mobile_") for name in tools.get("remote_device_tools", []))
        if task["target"] == "phone" and not (tools.get("phone_tools") or remote_phone):
            raise TaskError("请先在连接设置中绑定手机，并启动带手机连接器的执行引擎。")
        if task["target"] == "sandbox":
            raise TaskError("云端沙盒还未接通，可以先记下，接通后再执行。")
        if self.start_guard:
            self.start_guard(task)
        if self.store.is_conversation_task(task_id):
            messages = self.store.conversation(task["identity_id"])
            current_id = next(message["id"] for message in messages if message["task_id"] == task_id)
            queued = self.store.queued_messages()
            if any(message["identity_id"] == task["identity_id"] and message["id"] < current_id for message in queued):
                raise TaskError("前面还有已接收排队的消息，按顺序交接后再开始这一条。")
            with self.store.connection() as db:
                admitted = db.execute("SELECT 1 FROM message_handoffs WHERE task_id=?", (task_id,)).fetchone()
            if not admitted and not any(row["task_id"] == task_id for row in queued):
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
            # Hermes returns a partial summary at its iteration limit. Keep it
            # unfinished, but explain the real stop instead of a generic error.
            if status == "failed" and re.fullmatch(r"max_iterations_reached\(\d+/\d+\)", str(result.get("turn_exit_reason", ""))):
                descriptions["failed"] = "已达到本轮执行上限，现有结果和查看记录已保留；这件事尚未完成。"
            approval = result.get("approval")
            if self.desktop_relay and status=='waiting_for_approval' and isinstance(approval,dict):
                from .cloud.desktop_runs import bind, MARKER
                from .cloud.relay import RelayError
                if str(approval.get('command','')).startswith(MARKER):
                    try:approval=bind(self.desktop_relay(),task,approval)
                    except RelayError:
                        approval={**approval,'kind':'desktop_input','desktop_unavailable':True}
            approval = self.confirmations.observe(task, approval if status == "waiting_for_approval" and isinstance(approval, dict) else None)
            fields = {"status": status, "error": descriptions[status] if status in {"failed", "ambiguous"} else None,
                      "approval": approval if status == "waiting_for_approval" and isinstance(approval, dict) else None}
            if isinstance(result.get("output"), str):
                fields["output"] = result["output"]
            if isinstance(result.get("research"), dict) and isinstance(result["research"].get("items"), list):
                fields["research"] = result["research"]
            if isinstance(result.get("usage"), dict):
                fields["usage"] = result["usage"]
            if isinstance(result.get("session_id"), str):
                fields["session_id"] = result["session_id"]
                self.store.sync_conversation_session(task_id, result["session_id"])
            if status != task["status"]:
                self.store.event(task_id, status, descriptions[status])
            updated=self.store.update(task_id, **fields)
            if self.desktop_relay and status in TERMINAL:
                from .cloud.desktop_runs import cancel_task
                cancel_task(self.desktop_relay(),updated)
            return updated

    async def stop(self, task_id):
        async with self.lock:
            task = self.require(task_id)
            if task["status"] not in ACTIVE or not task["run_id"]:
                raise TaskError("当前没有可请求停止的运行；请先核对原运行状态。")
            if self.desktop_relay:
                from .cloud.desktop_runs import cancel_task
                cancel_task(self.desktop_relay(),task)
            try:
                client = await self.client(task)
                await client.stop(task["run_id"])
            except (HermesError, TaskError) as error:
                self.store.update(task_id, status="connection_lost", error=str(error))
                self.store.event(task_id, "stop_unconfirmed", "停止请求未确认；原运行可能仍在继续。")
                raise TaskError(str(error)) from error
            self.store.event(task_id, "stopping", "已请求停止；确认终止前请勿接管正在执行的操作。")
            self.confirmations.observe(task, None)
            return self.store.update(task_id, status="stopping", error=None)

    async def approve(self, task_id, request_id, choice):
        async with self.lock:
            task = self.require(task_id)
            if task["status"] != "waiting_for_approval" or not task["run_id"]:
                raise TaskError("该操作已不在等待确认，请刷新。")
            approval = task.get("approval") or {}
            if approval.get("request_id") != request_id:
                raise TaskError("确认请求已经变化，请刷新后阅读当前操作。")
            if choice not in {"once", "deny", "task"}:
                raise TaskError("请选择当前卡片上的操作。")
            if choice=='task' and (not self.desktop_relay or approval.get('kind')!='desktop_input'):
                raise TaskError('这项确认不能授权整件电脑任务，请查看当前操作。')
            if self.desktop_relay and approval.get('kind')=='desktop_input':
                from .cloud.desktop_runs import answer
                from .cloud.relay import RelayError
                try:answer(self.desktop_relay(),task,request_id,choice)
                except RelayError as error:raise TaskError('这一步已过期、暂停或运行发生变化，请重新查看。') from error
            managed = approval.get('kind') != 'desktop_input'
            if managed:
                self.confirmations.observe(task, approval)
                if not self.confirmations.claim(task, request_id):
                    raise TaskError("这张卡片已处理、过期或正在核对送达状态，请刷新查看原运行。")
            try:
                client = await self.client(task)
                await client.approve(task["run_id"], request_id, 'once' if choice=='task' else choice)
            except (HermesError, TaskError) as error:
                if managed:
                    decision_state = "unknown" if getattr(error, "uncertain", False) else "pending"
                    self.confirmations.finish(task_id, request_id, choice, decision_state)
                    self.store.update(task_id, approval={**approval, "card_state": decision_state})
                raise TaskError(str(error)) from error
            if managed:
                self.confirmations.finish(task_id, request_id, choice)
            self.store.event(task_id, "approval_answered", "已交给 Wearing 连续完成本轮任务。" if choice=='task' else "已允许这一次操作。" if choice == "once" else "已拒绝这一次操作。")
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
