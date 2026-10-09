"""Native messaging setup routes, protected by the host identity/CSRF gate."""
from typing import Literal

from fastapi import Request
from pydantic import BaseModel, ConfigDict, Field, SecretStr


class ConfigureChannel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    secret: SecretStr = Field(min_length=12, max_length=180)
    allowed_users: list[str] = Field(min_length=1, max_length=20)
    app_id: str | None = Field(default=None, max_length=100)


class ChangeChannel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: str = Field(pattern=r"^[a-f0-9]{32}$")
    enabled: bool


class DisconnectChannel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: str = Field(pattern=r"^[a-f0-9]{32}$")


def install_messaging_routes(app, bridge):
    @app.get("/api/messaging")
    async def channels(request: Request):
        return bridge.list(request.state.identity_id)

    @app.put("/api/messaging/{provider}")
    async def configure(request: Request, provider: Literal["telegram", "feishu"], body: ConfigureChannel):
        return await bridge.configure(request.state.identity_id, provider, body.secret.get_secret_value(), body.allowed_users, body.app_id)

    @app.patch("/api/messaging/{provider}")
    async def enable(request: Request, provider: Literal["telegram", "feishu"], body: ChangeChannel):
        result = await bridge.enabled(request.state.identity_id, provider, body.enabled, body.revision)
        if body.enabled:
            bridge.start()
        return result

    @app.delete("/api/messaging/{provider}")
    async def disconnect(request: Request, provider: Literal["telegram", "feishu"], body: DisconnectChannel):
        return await bridge.disconnect(request.state.identity_id, provider, body.revision)
