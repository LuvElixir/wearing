"""Hermes HTTP integration using its public runs API, not a second agent loop."""

from urllib.parse import quote

import httpx

from .config import Settings


class HermesError(Exception):
    def __init__(self, message: str, *, uncertain: bool = False):
        super().__init__(message)
        self.uncertain = uncertain


class HermesClient:
    def __init__(self, settings: Settings, transport=None):
        self.configured = bool(settings.hermes_key)
        self.http = httpx.AsyncClient(
            base_url=settings.hermes_url,
            headers={"Authorization": f"Bearer {settings.hermes_key}"},
            timeout=httpx.Timeout(15, connect=4),
            follow_redirects=False,
            transport=transport,
            trust_env=False,
        )

    async def close(self):
        await self.http.aclose()

    async def request(self, method, path, *, body=None, headers=None):
        if not self.configured:
            raise HermesError("尚未配置 Hermes 连接密钥。请先完成连接设置。")
        try:
            response = await self.http.request(method, path, json=body, headers=headers)
        except httpx.HTTPError as error:
            # A timeout after POST may follow an accepted request. Never blindly resubmit.
            raise HermesError("Hermes 连接中断，请检查运行状态后再继续。", uncertain=method == "POST") from error
        if response.status_code >= 300:
            explanations = {
                401: "Hermes 密钥未通过验证，请检查服务端连接配置。",
                403: "Hermes 当前凭据没有所需权限。",
                404: "Hermes 没有找到该接口或运行记录，请检查版本及原运行状态。",
                409: "Hermes 状态已变化，请刷新后再操作。",
                429: "Hermes 当前繁忙或达到额度，请稍后检查。",
            }
            raise HermesError(explanations.get(response.status_code, f"Hermes 返回 HTTP {response.status_code}，请检查服务状态。"),
                              uncertain=method == "POST" and response.status_code >= 500)
        try:
            data = response.json()
        except ValueError as error:
            raise HermesError("Hermes 返回了无法识别的数据。", uncertain=method == "POST") from error
        if not isinstance(data, dict):
            raise HermesError("Hermes 返回结构与当前连接协议不一致。", uncertain=method == "POST")
        return data

    async def probe(self):
        if not self.configured:
            return {"state": "not_configured", "message": "先连接运行在执行电脑上的 Hermes。", "features": {}}
        try:
            capabilities = await self.request("GET", "/v1/capabilities")
            return {"state": "reachable", "message": "执行引擎可达；设备操作能力仍按任务验证。", "features": capabilities.get("features", {}), "wearing": capabilities.get("wearing", {})}
        except HermesError as error:
            return {"state": "unavailable", "message": str(error), "features": {}}

    async def start(self, payload: dict, idempotency_key: str):
        result = await self.request("POST", "/v1/runs", body=payload, headers={"Idempotency-Key": idempotency_key})
        if not isinstance(result.get("run_id"), str) or not result["run_id"]:
            raise HermesError("Hermes 已响应，但缺少运行编号；请核对原运行。", uncertain=True)
        return result

    async def status(self, run_id: str):
        return await self.request("GET", f"/v1/runs/{quote(run_id, safe='')}")

    async def memories(self):
        result = await self.request("GET", "/v1/wearing/memory")
        targets = result.get("targets")
        if result.get("available") is not True or not isinstance(targets, dict):
            raise HermesError("当前执行引擎没有返回可读取的个人记忆。")
        for name in ("user", "memory"):
            target = targets.get(name)
            if (not isinstance(target, dict) or not isinstance(target.get("entries"), list)
                    or not all(isinstance(e, str) for e in target["entries"])
                    or not isinstance(target.get("enabled"), bool)):
                raise HermesError("记忆记录格式无法识别；原记录未改动。")
        return result

    async def change_memory(self, body):
        # Preserve mutation conflicts and user-actionable errors without exposing
        # generic upstream diagnostics or any connection credentials.
        if not self.configured:
            raise HermesError("当前身份的执行引擎尚未连接。")
        try:
            response = await self.http.patch("/v1/wearing/memory", json=body)
            data = response.json()
        except (httpx.HTTPError, ValueError) as cause:
            raise HermesError("尚未确认记忆保存结果，请刷新后核对。", uncertain=True) from cause
        if response.status_code >= 300:
            error = HermesError(data.get("error", "记忆未修改，请刷新后重试。") if isinstance(data, dict) else "记忆未修改，请刷新后重试。")
            error.status = response.status_code if response.status_code in {409,422} else 503
            raise error
        if not isinstance(data, dict) or not data.get("available"):
            raise HermesError("记忆回执无法识别，请刷新核对。", uncertain=True)
        return data

    async def stop(self, run_id: str):
        return await self.request("POST", f"/v1/runs/{quote(run_id, safe='')}/stop", body={})

    async def approve(self, run_id: str, request_id: str, choice: str):
        return await self.request("POST", f"/v1/runs/{quote(run_id, safe='')}/approval", body={"request_id": request_id, "choice": choice})
