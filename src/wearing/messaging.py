"""Personal messaging channels bridged through Pajio's canonical TaskService.

No channel starts until its owner explicitly enables it. Credentials are kept
in the private service database and never returned by the resource API.
"""
import asyncio
from contextlib import suppress
import hashlib
import json
import re
import time
import uuid
import importlib.util
import logging

import httpx
from fastapi import HTTPException

from .service import TERMINAL
from .store import now


class ChannelError(Exception):
    pass


class _RedactTelegramCredentials(logging.Filter):
    def filter(self, record):
        if "api.telegram.org/bot" in record.getMessage():
            record.msg = re.sub(r"https://api\.telegram\.org/bot[^\s/\"']+", "https://api.telegram.org/bot[redacted]", record.getMessage())
            record.args = ()
        return True


def _fail(message, status=422):
    raise HTTPException(status, message)


class ChannelNetwork:
    def __init__(self, client=None):
        self.http = client or httpx.AsyncClient(timeout=15, follow_redirects=False)
        self.owned = client is None
        self.feishu_tokens = {}
        # HTTPX includes the request URL in INFO logs; Telegram's official API
        # places credentials in that path. Preserve logging without token leaks.
        logger = logging.getLogger("httpx")
        if not any(isinstance(item, _RedactTelegramCredentials) for item in logger.filters):
            logger.addFilter(_RedactTelegramCredentials())

    async def telegram(self, secret, method, body=None):
        try:
            response = await self.http.post(f"https://api.telegram.org/bot{secret}/{method}", json=body or {})
            result = response.json()
            if response.status_code != 200 or result.get("ok") is not True:
                raise ChannelError("Telegram 暂未接受请求，请检查机器人配置和网络。")
            return result.get("result")
        except (httpx.HTTPError, ValueError, AttributeError):
            # A timeout may occur after Telegram accepted a message. Never echo
            # the exception: the request URL contains the bot credential.
            raise ChannelError("Telegram 暂时无法连接，请稍后重新检查。") from None

    async def verify_telegram(self, secret):
        info = await self.telegram(secret, "getMe")
        if not isinstance(info, dict) or not isinstance(info.get("id"), int) or not info.get("is_bot"):
            raise ChannelError("没有读到有效的 Telegram 机器人。")
        webhook = await self.telegram(secret, "getWebhookInfo")
        if not isinstance(webhook, dict) or webhook.get("url"):
            raise ChannelError("这个机器人正在使用其他 Webhook，请先使用一个专供 Pajio 的机器人。")
        return str(info["id"]), str(info.get("username") or info.get("first_name") or "Telegram")[:100]

    async def verify_feishu(self, app_id, secret):
        try:
            token = await self.feishu_token(app_id, secret)
            response = await self.http.get("https://open.feishu.cn/open-apis/bot/v3/info", headers={"Authorization": "Bearer " + token})
            data = response.json()
            bot = data.get("bot") or data.get("data", {}).get("bot")
            if response.status_code != 200 or data.get("code") != 0 or not isinstance(bot, dict):
                raise ChannelError("飞书应用还没有可用的机器人，请开启机器人能力并发布应用。")
            return app_id, str(bot.get("app_name") or "飞书机器人")[:100]
        except (httpx.HTTPError, ValueError, AttributeError):
            raise ChannelError("暂时无法验证飞书应用，请稍后重试。") from None

    async def feishu_token(self, app_id, secret):
        key = (app_id, hashlib.sha256(secret.encode()).hexdigest())
        cached = self.feishu_tokens.get(key)
        if cached and cached[1] > time.monotonic():
            return cached[0]
        try:
            response = await self.http.post("https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal", json={"app_id": app_id, "app_secret": secret})
            data = response.json()
            token = data.get("tenant_access_token")
            if response.status_code != 200 or data.get("code") != 0 or not isinstance(token, str):
                raise ChannelError("飞书应用凭据验证失败，请核对 App ID 和 App Secret。")
            self.feishu_tokens[key] = (token, time.monotonic() + max(0, min(int(data.get("expire", 300)), 7200) - 60))
            return token
        except (httpx.HTTPError, ValueError, AttributeError):
            raise ChannelError("暂时无法验证飞书应用，请稍后重试。") from None

    async def send_feishu(self, app_id, secret, user, text, request_id):
        token = await self.feishu_token(app_id, secret)
        try:
            response = await self.http.post("https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=open_id",
                headers={"Authorization": "Bearer " + token},
                json={"receive_id": user, "msg_type": "text", "content": json.dumps({"text": text}, ensure_ascii=False), "uuid": request_id})
            data = response.json()
            if response.status_code != 200 or data.get("code") != 0:
                raise ChannelError("飞书未确认这次回复，请在 App 中查看结果。")
        except (httpx.HTTPError, ValueError, AttributeError):
            raise ChannelError("暂时无法确认回复是否送达，请在 App 中查看结果。") from None

    async def close(self):
        if self.owned:
            await self.http.aclose()


class MessagingBridge:
    def __init__(self, store, service, network=None):
        self.store, self.service = store, service
        self.network = network or ChannelNetwork()
        self.lock = asyncio.Lock()
        self.worker = None
        from .feishu_receiver import FeishuReceiver
        self.feishu = FeishuReceiver(self.receive_feishu, self.feishu_status)
        with store.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS messaging_connections (
                    identity_id TEXT NOT NULL, provider TEXT NOT NULL, bot_id TEXT NOT NULL,
                    name TEXT NOT NULL, secret TEXT NOT NULL, allowed_users TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 0, enabled_since REAL NOT NULL DEFAULT 0,
                    cursor INTEGER NOT NULL DEFAULT 0, checked_at TEXT, error TEXT,
                    revision TEXT NOT NULL, PRIMARY KEY(identity_id,provider), UNIQUE(provider,bot_id)
                );
                CREATE TABLE IF NOT EXISTS messaging_receipts (
                    provider TEXT NOT NULL, bot_id TEXT NOT NULL, event_id TEXT NOT NULL,
                    identity_id TEXT NOT NULL, chat_id TEXT NOT NULL, task_id TEXT,
                    created_at TEXT NOT NULL, PRIMARY KEY(provider,bot_id,event_id)
                );
                CREATE TABLE IF NOT EXISTS messaging_deliveries (
                    provider TEXT NOT NULL, bot_id TEXT NOT NULL, event_id TEXT NOT NULL,
                    kind TEXT NOT NULL, state TEXT NOT NULL, created_at TEXT NOT NULL,
                    PRIMARY KEY(provider,bot_id,event_id,kind)
                );
            """)
            # A process may have died after sending but before recording success.
            db.execute("UPDATE messaging_deliveries SET state='uncertain' WHERE state='sending'")
            db.execute("UPDATE messaging_connections SET checked_at=NULL WHERE enabled=1")

    def _connection(self, identity, provider):
        self.store.identity(identity)
        with self.store.connection() as db:
            row = db.execute("SELECT * FROM messaging_connections WHERE identity_id=? AND provider=?", (identity, provider)).fetchone()
        return dict(row) if row else None

    def _public(self, row):
        with self.store.connection() as db:
            uncertain = db.execute("SELECT COUNT(*) FROM messaging_deliveries WHERE provider=? AND bot_id=? AND state='uncertain'", (row["provider"], row["bot_id"])).fetchone()[0]
        return {key: row[key] for key in ("provider", "bot_id", "name", "checked_at", "error", "revision")} | {
            "configured": True, "enabled": bool(row["enabled"]), "allowed_users": json.loads(row["allowed_users"]),
            "state": "error" if row["error"] else ("listening" if row["checked_at"] else "connecting") if row["enabled"] else "configured",
            "uncertain_replies": uncertain,
            "can_enable": row["provider"] == "telegram" or importlib.util.find_spec("lark_oapi") is not None,
        }

    def list(self, identity):
        self.store.identity(identity)
        rows = []
        for provider, name in (("telegram", "Telegram"), ("feishu", "飞书")):
            item = self._connection(identity, provider)
            rows.append(self._public(item) if item else {"provider": provider, "name": name, "configured": False, "enabled": False, "state": "not_configured", "allowed_users": [], "can_enable": provider == "telegram" or importlib.util.find_spec("lark_oapi") is not None, "uncertain_replies": 0, "revision": None, "error": None, "checked_at": None})
        return {"channels": rows}

    async def configure(self, identity, provider, secret, users, app_id=None):
        self.store.identity(identity)
        if provider not in {"telegram", "feishu"}:
            _fail("暂不支持这个聊天渠道。")
        if not users or len(users) > 20 or len(set(users)) != len(users):
            _fail("请填写 1–20 个不同的个人用户 ID。")
        if provider == "telegram":
            if not re.fullmatch(r"[0-9]{5,20}:[A-Za-z0-9_-]{20,120}", secret) or any(not re.fullmatch(r"[1-9][0-9]{0,19}", user) for user in users):
                _fail("请核对 Bot Token 和 Telegram 数字用户 ID。")
        elif not re.fullmatch(r"cli_[A-Za-z0-9]{6,80}", app_id or "") or not re.fullmatch(r"[A-Za-z0-9_-]{12,160}", secret) or any(not re.fullmatch(r"ou_[A-Za-z0-9_-]{6,100}", user) for user in users):
            _fail("请核对飞书 App ID、App Secret 和个人 Open ID。")
        async with self.lock:
            current = self._connection(identity, provider)
            if current and current["enabled"]:
                _fail("请先停用此渠道，再更换凭据或允许的用户。", 409)
            try:
                bot_id, name = await (self.network.verify_telegram(secret) if provider == "telegram" else self.network.verify_feishu(app_id, secret))
            except ChannelError as error:
                _fail(str(error), 409)
            with self.store.connection() as db:
                db.execute("BEGIN IMMEDIATE")
                used = db.execute("SELECT identity_id FROM messaging_connections WHERE provider=? AND bot_id=?", (provider, bot_id)).fetchone()
                if used and used["identity_id"] != identity:
                    _fail("这个机器人已绑定另一个身份，请使用不同的机器人。", 409)
                cursor = current["cursor"] if current and current["bot_id"] == bot_id else 0
                db.execute("""INSERT INTO messaging_connections(identity_id,provider,bot_id,name,secret,allowed_users,cursor,checked_at,revision)
                    VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(identity_id,provider) DO UPDATE SET bot_id=excluded.bot_id,
                    name=excluded.name,secret=excluded.secret,allowed_users=excluded.allowed_users,enabled=0,
                    enabled_since=0,cursor=excluded.cursor,checked_at=excluded.checked_at,error=NULL,revision=excluded.revision""",
                           (identity, provider, bot_id, name, secret, json.dumps(users), cursor, now(), uuid.uuid4().hex))
            return self.list(identity)

    async def enabled(self, identity, provider, enabled, revision):
        async with self.lock:
            row = self._connection(identity, provider)
            if not row:
                _fail("请先配置这个渠道。", 409)
            if row["revision"] != revision:
                _fail("渠道设置已变化，请刷新后重试。", 409)
            if enabled:
                if provider == "feishu" and importlib.util.find_spec("lark_oapi") is None:
                    _fail("服务尚未安装飞书连接组件，请更新服务后启用。", 409)
                try:
                    await (self.network.verify_telegram(row["secret"]) if provider == "telegram" else self.network.verify_feishu(row["bot_id"], row["secret"]))
                except ChannelError as error:
                    _fail(str(error), 409)
            with self.store.connection() as db:
                db.execute("UPDATE messaging_connections SET enabled=?,enabled_since=?,error=NULL,checked_at=NULL,revision=? WHERE identity_id=? AND provider=?",
                           (int(enabled), time.time() if enabled else 0, uuid.uuid4().hex, identity, provider))
            if not enabled and provider == "feishu":
                await self.feishu.stop(identity)
            return self.list(identity)

    async def disconnect(self, identity, provider, revision):
        async with self.lock:
            row = self._connection(identity, provider)
            if not row or row["revision"] != revision:
                _fail("渠道设置已变化，请刷新后重试。", 409)
            with self.store.connection() as db:
                # Remove credentials only. Canonical conversations/receipts stay.
                db.execute("DELETE FROM messaging_connections WHERE identity_id=? AND provider=?", (identity, provider))
            if provider == "feishu":
                await self.feishu.stop(identity)
            return self.list(identity)

    def _current(self, row):
        current = self._connection(row["identity_id"], row["provider"])
        return bool(current and current["enabled"] and current["revision"] == row["revision"])

    async def _receive_telegram(self, row, update):
        event = update.get("update_id")
        message = update.get("message") or {}
        sender, chat = message.get("from") or {}, message.get("chat") or {}
        content, stamp = message.get("text"), message.get("date")
        if not isinstance(event, int) or not isinstance(content, str) or not content.strip() or len(content) > 12000:
            return
        if sender.get("is_bot") or chat.get("type") != "private" or str(sender.get("id")) != str(chat.get("id")) or str(sender.get("id")) not in json.loads(row["allowed_users"]):
            return
        # Enabling never grants permission to execute a backlog from before now.
        if not isinstance(stamp, (int, float)) or stamp < int(row["enabled_since"]):
            return
        await self._accept(row, str(event), str(chat["id"]), content.strip())

    async def _accept(self, row, event_id, user, content):
        if not self._current(row):
            return
        with self.store.connection() as db:
            db.execute("INSERT OR IGNORE INTO messaging_receipts VALUES(?,?,?,?,?,NULL,?)", (row["provider"], row["bot_id"], event_id, row["identity_id"], user, now()))
            receipt = db.execute("SELECT * FROM messaging_receipts WHERE provider=? AND bot_id=? AND event_id=?", (row["provider"], row["bot_id"], event_id)).fetchone()
        if receipt["identity_id"] != row["identity_id"]:
            return
        if not receipt["task_id"]:
            key = "channel-" + hashlib.sha256(f"{row['provider']}:{row['bot_id']}:{event_id}".encode()).hexdigest()
            result = await self.service.submit_message(content, row["identity_id"], key)
            with self.store.connection() as db:
                db.execute("UPDATE messaging_receipts SET task_id=? WHERE provider=? AND bot_id=? AND event_id=? AND identity_id=?",
                           (result["task"]["id"], row["provider"], row["bot_id"], event_id, row["identity_id"]))

    async def receive_feishu(self, row, event):
        header, data = event.get("header") or {}, event.get("event") or {}
        sender, message = data.get("sender") or {}, data.get("message") or {}
        user = (sender.get("sender_id") or {}).get("open_id")
        if header.get("app_id") != row["bot_id"] or sender.get("sender_type") != "user" or message.get("chat_type") != "p2p" or message.get("message_type") != "text" or user not in json.loads(row["allowed_users"]):
            return
        event_id = header.get("event_id")
        try:
            content = json.loads(message.get("content") or "{}").get("text")
            stamp = int(message.get("create_time") or 0) / 1000
        except (ValueError, TypeError, AttributeError):
            return
        if not isinstance(event_id, str) or not 1 <= len(event_id) <= 100 or not isinstance(content, str) or not 1 <= len(content.strip()) <= 12000 or stamp < row["enabled_since"]:
            return
        async with self.lock:
            await self._accept(row, event_id, user, content.strip())

    async def feishu_status(self, row, state):
        if not self._current(row):
            return
        with self.store.connection() as db:
            db.execute("UPDATE messaging_connections SET checked_at=?,error=? WHERE identity_id=? AND provider='feishu' AND revision=?",
                (now() if state == "connected" else None, None if state == "connected" else "飞书连接正在恢复，请检查应用已发布并采用长连接订阅消息事件。", row["identity_id"], row["revision"]))

    async def _send(self, row, receipt, kind, text):
        if not self._current(row) or receipt["chat_id"] not in json.loads(row["allowed_users"]):
            return
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            claimed = db.execute("INSERT OR IGNORE INTO messaging_deliveries VALUES(?,?,?,?,?,?)", (row["provider"], row["bot_id"], receipt["event_id"], kind, "sending", now())).rowcount
        if not claimed:
            return
        # Telegram limits text length. Truncate at a UTF-16 boundary to also
        # handle emoji without generating an over-limit retry loop.
        encoded = text.encode("utf-16-le")
        if len(encoded) > 7000:
            text = encoded[:6800].decode("utf-16-le", errors="ignore") + "\n\n完整结果已保留在 Pajio。"
        state = "delivered"
        try:
            if row["provider"] == "telegram":
                await self.network.telegram(row["secret"], "sendMessage", {"chat_id": receipt["chat_id"], "text": text, "link_preview_options": {"is_disabled": True}})
            else:
                request_id = hashlib.sha256(f"{row['bot_id']}:{receipt['event_id']}:{kind}".encode()).hexdigest()[:32]
                await self.network.send_feishu(row["bot_id"], row["secret"], receipt["chat_id"], text, request_id)
        except ChannelError:
            state = "uncertain"
        with self.store.connection() as db:
            db.execute("UPDATE messaging_deliveries SET state=? WHERE provider=? AND bot_id=? AND event_id=? AND kind=?", (state, row["provider"], row["bot_id"], receipt["event_id"], kind))

    async def _replies(self, row):
        with self.store.connection() as db:
            receipts = [dict(item) for item in db.execute("""SELECT r.* FROM messaging_receipts r
                WHERE identity_id=? AND provider=? AND bot_id=? AND task_id IS NOT NULL
                AND NOT EXISTS (SELECT 1 FROM messaging_deliveries d WHERE d.provider=r.provider
                    AND d.bot_id=r.bot_id AND d.event_id=r.event_id AND d.kind='result')
                ORDER BY created_at ASC LIMIT 100""", (row["identity_id"], row["provider"], row["bot_id"]))]
        for receipt in receipts:
            task = self.store.get(receipt["task_id"])
            if not task or task["identity_id"] != row["identity_id"]:
                continue
            status = task["status"]
            if status == "waiting_for_approval":
                approval = task.get("approval") or {}
                key = "approval-" + hashlib.sha256(json.dumps(approval, sort_keys=True).encode()).hexdigest()[:16]
                await self._send(row, receipt, key, "这一步需要你确认。请打开 Pajio，查看这件事里的操作详情后再决定。")
            elif status in TERMINAL:
                text = task.get("output") or ("这次任务没有完成，请到 Pajio 查看详情。" if status == "failed" else "这次任务已结束，详情保留在 Pajio。")
                await self._send(row, receipt, "result", text)
            elif status == "draft":
                delivery = self.service.delivery(task)
                text = "已收到，正在等前面的任务结束。进展也会出现在 Pajio。" if delivery["delivery"] == "queued" else "已保存在 Pajio，但执行引擎尚未接下。请在 App 中查看并继续。"
                await self._send(row, receipt, "received", text)

    async def tick(self):
        # Shared with configure/disable: once disabling returns, no in-flight
        # operation from this worker can still initiate an external reply.
        async with self.lock:
            with self.store.connection() as db:
                rows = [dict(row) for row in db.execute("SELECT * FROM messaging_connections WHERE enabled=1 AND provider='telegram'")]
                feishu_rows = [dict(row) for row in db.execute("SELECT * FROM messaging_connections WHERE enabled=1 AND provider='feishu'")]
            await self.feishu.synchronize(feishu_rows)
            for row in feishu_rows:
                await self._replies(row)
            for row in rows:
                try:
                    updates = await self.network.telegram(row["secret"], "getUpdates", {"offset": row["cursor"], "limit": 100, "timeout": 0, "allowed_updates": ["message"]})
                    if not isinstance(updates, list):
                        raise ChannelError("Telegram 返回的消息列表暂时无法读取。")
                    for update in updates:
                        if not isinstance(update, dict) or not isinstance(update.get("update_id"), int):
                            continue
                        await self._receive_telegram(row, update)
                        with self.store.connection() as db:
                            db.execute("UPDATE messaging_connections SET cursor=MAX(cursor,?) WHERE identity_id=? AND provider='telegram'", (update["update_id"] + 1, row["identity_id"]))
                    await self._replies(row)
                    with self.store.connection() as db:
                        db.execute("UPDATE messaging_connections SET checked_at=?,error=NULL WHERE identity_id=? AND provider='telegram'", (now(), row["identity_id"]))
                except Exception:
                    with self.store.connection() as db:
                        db.execute("UPDATE messaging_connections SET error=? WHERE identity_id=? AND provider='telegram'", ("接收暂时中断，正在重连；已收消息仍保留在 Pajio。", row["identity_id"]))

    def start(self):
        if not self.worker or self.worker.done():
            self.worker = asyncio.create_task(self._loop())

    async def _loop(self):
        while True:
            try:
                await self.tick()
            except Exception:
                with self.store.connection() as db:
                    db.execute("UPDATE messaging_connections SET error=? WHERE enabled=1", ("渠道服务正在恢复，请稍后查看连接状态。",))
            await asyncio.sleep(2)

    async def close(self):
        if self.worker:
            self.worker.cancel()
            with suppress(asyncio.CancelledError):
                await self.worker
        await self.feishu.close()
        await self.network.close()
