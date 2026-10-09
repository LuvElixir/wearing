"""Identity-scoped cloud applications; OAuth credentials never enter Agent output.

Feishu Device Flow follows the installed official lark-oapi 1.7.3 client.
Revocation follows larksuite/cli internal/auth/revoke.go (RFC 7009).
"""
import asyncio
from contextlib import asynccontextmanager
import hashlib
import json
import re
import time
import uuid
from urllib.parse import quote, urlparse

import httpx
from fastapi import HTTPException
from filelock import FileLock, Timeout

from .config import private_directory


FEATURES = {
    "documents": {"label": "云文档与知识库", "scopes": ["drive:drive:readonly", "docx:document:readonly", "wiki:wiki:readonly"]},
    "calendar": {"label": "日历与日程", "scopes": ["calendar:calendar:read", "calendar:calendar.event:read"]},
}
API = "https://open.feishu.cn"
TOKEN_PATH = "/open-apis/authen/v2/oauth/token"


class CloudAppError(HTTPException):
    def __init__(self, message, status=422, kind="request"):
        super().__init__(status, message)
        self.kind = kind


def official_url(value):
    try:
        parsed = urlparse(value)
        return (parsed.scheme == "https" and not parsed.username and not parsed.password
                and parsed.port in (None, 443) and parsed.hostname
                and (parsed.hostname == "feishu.cn" or parsed.hostname.endswith(".feishu.cn")))
    except (ValueError, TypeError):
        return False


class FeishuCloudNetwork:
    def __init__(self, client=None):
        self.http = client or httpx.AsyncClient(timeout=12, follow_redirects=False, trust_env=False)
        self.owned = client is None

    async def request(self, method, path, *, token=None, body=None, params=None, revoke=False):
        headers = {"Authorization": "Bearer " + token} if token else {}
        url = "https://accounts.feishu.cn/oauth/v1/revoke" if revoke else API + path
        try:
            async with self.http.stream(method, url, headers=headers, params=params,
                                        **({"data": body} if revoke else {"json": body} if body is not None else {})) as response:
                chunks, size = [], 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > 2 * 1024 * 1024:
                        raise CloudAppError("飞书返回内容过大，请缩小范围后重试。", 413)
                    chunks.append(chunk)
                raw = b"".join(chunks)
                if revoke and response.is_success and not raw.strip():
                    return {}
                data = json.loads(raw)
                if not isinstance(data, dict):
                    raise ValueError()
                # Device authorization pending/slow-down is an expected response.
                if path == TOKEN_PATH and data.get("error") in {"authorization_pending", "slow_down", "access_denied", "expired_token"}:
                    return data
                if not response.is_success or data.get("code", 0) != 0 or data.get("error"):
                    code = data.get("code")
                    if response.status_code == 401 or code in {99991663, 99991668, 99991671, 99991677} or data.get("error") in {"invalid_grant", "invalid_token"}:
                        raise CloudAppError("飞书授权已失效，请重新授权。", 401, "authorization")
                    if response.status_code == 403 or code in {99991672, 99991679} or data.get("error") in {"invalid_scope", "insufficient_scope"}:
                        raise CloudAppError("飞书权限不足，请检查应用权限、发布状态和文件共享范围，再重新授权。", 403, "permission")
                    raise CloudAppError("飞书未接受请求，请检查应用配置、权限和发布状态后重试。", 502)
                return data
        except (httpx.HTTPError, ValueError, TypeError):
            # Exceptions and provider error bodies can contain credentials.
            raise CloudAppError("暂时连不上飞书，请稍后重试。", 503, "network") from None

    async def start(self, app_id, secret, scopes):
        # Verify the App Secret as well as App ID before saving a pending grant.
        await self.request("POST", "/open-apis/auth/v3/tenant_access_token/internal", body={"app_id": app_id, "app_secret": secret})
        return await self.request("POST", "/open-apis/authen/v2/oauth/device_authorization", body={"client_id": app_id, "scope": " ".join(scopes)})

    async def exchange(self, app_id, secret, **grant):
        return await self.request("POST", TOKEN_PATH, body={"client_id": app_id, "client_secret": secret, **grant})

    async def revoke(self, app_id, secret, token, hint):
        return await self.request("POST", "", revoke=True, body={"client_id": app_id, "client_secret": secret, "token": token, "token_type_hint": hint})

    async def close(self):
        if self.owned:
            await self.http.aclose()


def _payload(data):
    return data.get("data") if isinstance(data.get("data"), dict) else data


class CloudApps:
    def __init__(self, store, network=None):
        self.store, self.network = store, network or FeishuCloudNetwork()
        self.lock_dir = store.path.parent / "cloud-app-locks"
        private_directory(self.lock_dir)
        with store.connection() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS cloud_app_connections (
                identity_id TEXT PRIMARY KEY REFERENCES identities(id), payload TEXT NOT NULL)""")

    @asynccontextmanager
    async def _lock(self, identity):
        self.store.identity(identity)
        lock = FileLock(self.lock_dir / (hashlib.sha256(identity.encode()).hexdigest() + ".lock"))
        until = time.monotonic() + 20
        while True:
            try:
                lock.acquire(timeout=0)
                break
            except Timeout:
                if time.monotonic() >= until:
                    raise CloudAppError("连接正在更新，请稍后重试。", 409)
                await asyncio.sleep(.05)
        try:
            yield
        finally:
            lock.release()

    def _read(self, identity):
        self.store.identity(identity)
        with self.store.connection() as db:
            row = db.execute("SELECT payload FROM cloud_app_connections WHERE identity_id=?", (identity,)).fetchone()
        return json.loads(row[0]) if row else None

    def _write(self, identity, row):
        with self.store.connection() as db:
            db.execute("INSERT INTO cloud_app_connections(identity_id,payload) VALUES(?,?) ON CONFLICT(identity_id) DO UPDATE SET payload=excluded.payload", (identity, json.dumps(row)))

    def snapshot(self, identity):
        row = self._read(identity)
        oauth = row.get("oauth", {}) if row else {}
        pending = row.get("pending", {}) if row else {}
        stamp = time.time()
        state = "not_configured" if not row else "configured"
        if oauth.get("access_token") and oauth.get("verified"):
            state = "connected" if oauth.get("expires_at", 0) > stamp or (oauth.get("refresh_token") and oauth.get("refresh_expires_at", 0) > stamp) else "expired"
        if pending:
            state = "authorizing" if pending.get("expires_at", 0) > stamp else "authorization_expired"
        if row and row.get("needs_authorization"):
            state = "expired"
        granted = oauth.get("scopes", [])
        requested = row.get("features", []) if row else []
        capabilities = [{"id": key, "label": value["label"], "requested": key in requested,
                         "authorized": bool(oauth.get("access_token")) and state == "connected" and all(scope in granted for scope in value["scopes"]),
                         "scopes": value["scopes"]} for key, value in FEATURES.items()]
        return {"provider": "feishu", "state": state, "configured": bool(row), "revision": row.get("revision") if row else None,
                "app_id": row.get("app_id") if row else None, "account_name": oauth.get("name"), "account_id": oauth.get("open_id"),
                "capabilities": capabilities, "checked_at": row.get("checked_at") if row else None, "error": row.get("error") if row else None,
                "authorization": {key: pending[key] for key in ("id", "url", "user_code", "expires_at", "interval") if key in pending} if pending and state == "authorizing" else None,
                "revocation_pending": bool(row and row.get("revocation_pending"))}

    async def configure(self, identity, app_id, secret, features):
        if not re.fullmatch(r"cli_[A-Za-z0-9]{6,80}", app_id) or not re.fullmatch(r"[A-Za-z0-9_-]{12,160}", secret):
            raise CloudAppError("请核对飞书 App ID 与 App Secret。")
        if not features or len(features) > 2 or any(key not in FEATURES for key in features):
            raise CloudAppError("请选择要连接的文档或日历权限。")
        async with self._lock(identity):
            old = self._read(identity)
            if old and (old.get("oauth") or old.get("pending") or old.get("revocation_pending")):
                raise CloudAppError("请先断开已有授权，再更换应用配置。", 409)
            self._write(identity, {"app_id": app_id, "secret": secret, "features": sorted(set(features)), "revision": uuid.uuid4().hex})
        return self.snapshot(identity)

    def _require(self, identity, revision=None):
        row = self._read(identity)
        if not row:
            raise CloudAppError("请先配置飞书应用。", 409)
        if revision is not None and row["revision"] != revision:
            raise CloudAppError("连接已更新，请刷新后重试。", 409)
        return row

    async def authorize(self, identity, revision):
        async with self._lock(identity):
            row = self._require(identity, revision)
            if row.get("revocation_pending"):
                raise CloudAppError("请先完成撤销授权，再连接。", 409)
            if row.get("pending", {}).get("expires_at", 0) > time.time():
                return self.snapshot(identity)
            scopes = ["offline_access"] + [scope for key in row["features"] for scope in FEATURES[key]["scopes"]]
            payload = _payload(await self.network.start(row["app_id"], row["secret"], scopes))
            url = payload.get("verification_uri_complete") or payload.get("verification_uri")
            code = payload.get("device_code")
            if not official_url(url) or not isinstance(code, str) or not code or not isinstance(payload.get("user_code"), str):
                raise CloudAppError("没有获得有效的飞书授权入口，请稍后重试。", 502)
            try:
                ttl, interval = int(payload["expires_in"]), int(payload.get("interval", 5))
                if not 1 <= ttl <= 3600 or not 1 <= interval <= 120:
                    raise ValueError()
            except (TypeError, ValueError, KeyError):
                raise CloudAppError("飞书授权状态不完整，请重新开始。", 502) from None
            row["pending"] = {"id": uuid.uuid4().hex, "device_code": code, "url": url, "user_code": payload["user_code"][:40], "expires_at": time.time() + ttl, "interval": max(5, interval), "next_poll": time.time() + max(5, interval)}
            row.pop("error", None)
            row.pop("needs_authorization", None)
            self._write(identity, row)
        return self.snapshot(identity)

    def _tokens(self, payload, old=None):
        old = old or {}
        token = payload.get("access_token")
        if not isinstance(token, str) or not token or len(token) > 16384 or str(payload.get("token_type", "Bearer")).lower() != "bearer":
            raise CloudAppError("没有获得有效的飞书用户授权，请重新授权。", 502)
        try:
            ttl = int(payload["expires_in"])
            refresh_ttl = int(payload.get("refresh_token_expires_in", 0))
            if not 1 <= ttl <= 86400 * 30 or not 0 <= refresh_ttl <= 86400 * 365:
                raise ValueError()
        except (TypeError, KeyError, ValueError):
            raise CloudAppError("飞书授权有效期不完整，请重新授权。", 502) from None
        scopes = payload.get("scope")
        if scopes is not None and not isinstance(scopes, str):
            raise CloudAppError("飞书授权权限不完整，请重新授权。", 502)
        refresh = payload.get("refresh_token") or old.get("refresh_token")
        return {**old, "access_token": token, "expires_at": time.time() + ttl, "refresh_token": refresh,
                "refresh_expires_at": time.time() + refresh_ttl if refresh_ttl else old.get("refresh_expires_at", 0),
                "scopes": scopes.split() if scopes is not None else old.get("scopes", [])}

    async def poll(self, identity, authorization_id):
        async with self._lock(identity):
            row = self._require(identity)
            pending = row.get("pending", {})
            if pending.get("id") != authorization_id:
                raise CloudAppError("授权已更新，请刷新连接状态。", 409)
            stamp = time.time()
            if pending["expires_at"] <= stamp:
                row.pop("pending", None)
                row["error"] = "这次授权已到期，请重新授权。"
            elif pending["next_poll"] <= stamp:
                pending["next_poll"] = stamp + pending["interval"]
                # Persist rate limit before network so retries cannot poll faster.
                self._write(identity, row)
                result = ({"access_token_issued": True} if pending.get("issued") else
                          await self.network.exchange(row["app_id"], row["secret"], grant_type="urn:ietf:params:oauth:grant-type:device_code", device_code=pending["device_code"]))
                error = result.get("error") or result.get("msg")
                if error == "slow_down":
                    pending["interval"] = min(120, pending["interval"] + 5)
                    pending["next_poll"] = time.time() + pending["interval"]
                elif error in {"access_denied", "expired_token"}:
                    row.pop("pending", None)
                    row["error"] = "你没有完成这次授权，可随时重新连接。"
                elif error != "authorization_pending":
                    oauth = row["oauth"] if pending.get("issued") else self._tokens(_payload(result))
                    # A grant code is single-use. Persist issued tokens before
                    # user-info verification so a temporary failure can retry.
                    if not pending.get("issued"):
                        old = row.get("oauth")
                        if old:
                            row.setdefault("superseded", []).append(old)
                        row["oauth"] = oauth
                        pending["issued"] = True
                        self._write(identity, row)
                    info = _payload(await self.network.request("GET", "/open-apis/authen/v1/user_info", token=oauth["access_token"]))
                    if not isinstance(info.get("open_id"), str) or not info["open_id"].startswith("ou_"):
                        raise CloudAppError("无法核实授权账号，请重新授权。", 502)
                    oauth.update(open_id=info["open_id"][:120], name=str(info.get("name") or "飞书用户")[:120], verified=True)
                    row.update(oauth=oauth, checked_at=time.time())
                    row.pop("pending", None)
                    row.pop("error", None)
                    row.pop("needs_authorization", None)
            self._write(identity, row)
        return self.snapshot(identity)

    async def _access(self, identity, row):
        oauth = row.get("oauth", {})
        if row.get("revocation_pending") or row.get("needs_authorization") or not oauth.get("access_token") or not oauth.get("verified"):
            raise CloudAppError("请在 App 的云端应用中连接飞书账号。", 409, "authorization")
        if oauth.get("expires_at", 0) > time.time() + 90:
            return oauth["access_token"]
        if not oauth.get("refresh_token") or oauth.get("refresh_expires_at", 0) <= time.time():
            row["needs_authorization"] = True
            self._write(identity, row)
            raise CloudAppError("飞书授权已到期，请在 App 中重新授权。", 401, "authorization")
        try:
            data = await self.network.exchange(row["app_id"], row["secret"], grant_type="refresh_token", refresh_token=oauth["refresh_token"])
            row["oauth"] = self._tokens(_payload(data), oauth)
            self._write(identity, row)
            return row["oauth"]["access_token"]
        except CloudAppError as error:
            if error.kind == "authorization":
                row["needs_authorization"], row["error"] = True, error.detail
                self._write(identity, row)
            raise

    async def read(self, identity, path, *, params=None, feature=None):
        async with self._lock(identity):
            row = self._require(identity)
            token = await self._access(identity, row)
            if feature and any(scope not in row["oauth"]["scopes"] for scope in FEATURES[feature]["scopes"]):
                raise CloudAppError("尚未授权" + FEATURES[feature]["label"] + "，请在 App 中重新授权，并检查飞书应用是否已发布这些权限。", 403, "permission")
            try:
                data = await self.network.request("GET", path, token=token, params=params)
                row["checked_at"] = time.time()
                row.pop("error", None)
                self._write(identity, row)
                return _payload(data)
            except CloudAppError as error:
                row["error"] = error.detail
                if error.kind == "authorization":
                    row["needs_authorization"] = True
                self._write(identity, row)
                raise

    async def check(self, identity):
        await self.read(identity, "/open-apis/authen/v1/user_info")
        return self.snapshot(identity)

    async def disconnect(self, identity, revision):
        async with self._lock(identity):
            row = self._require(identity, revision)
            oauth = row.get("oauth", {})
            row.pop("pending", None)
            # Stop access durably even if the provider cannot complete revocation.
            row["revocation_pending"] = bool(oauth)
            row["needs_authorization"] = True
            self._write(identity, row)
            try:
                for grant in [oauth, *row.get("superseded", [])]:
                    for key in ("refresh_token", "access_token"):
                        if grant.get(key):
                            await self.network.revoke(row["app_id"], row["secret"], grant[key], key)
                with self.store.connection() as db:
                    db.execute("DELETE FROM cloud_app_connections WHERE identity_id=?", (identity,))
            except CloudAppError:
                row["error"] = "Pajio 已停止使用此连接。飞书暂未完成撤销，请点重试撤销。"
                self._write(identity, row)
        return self.snapshot(identity)

    async def close(self):
        await self.network.close()


def resource_id(value, *, calendar=False):
    pattern = r"[A-Za-z0-9_.@-]{1,240}" if calendar else r"[A-Za-z0-9_-]{1,160}"
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        raise CloudAppError("资源标识无效，请使用实际文档或日历返回的标识。")
    return quote(value, safe="")
