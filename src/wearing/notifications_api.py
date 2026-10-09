"""Routes rely on the application's existing tenant, identity and CSRF middleware."""
from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal
from .notifications import NotificationError, OWNER


class NotificationDevice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    installation_id: str = Field(min_length=16, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")


class NotificationRegistration(NotificationDevice):
    expo_push_token: str = Field(min_length=20, max_length=230)
    project_id: str = Field(min_length=36, max_length=36)
    platform: Literal["ios", "android"]


class NotificationPreferences(NotificationDevice):
    revision: int = Field(ge=0, strict=True)
    enabled: bool = Field(strict=True)
    start_minute: int = Field(ge=0, lt=1440, strict=True)
    end_minute: int = Field(ge=0, lt=1440, strict=True)
    timezone: str = Field(min_length=1, max_length=80)


def install_notification_routes(app, service):
    def owner(request):
        if not request.scope.get("pajio.cloud_worker"):
            return "local"
        value = request.scope.get("pajio.storage_scope")
        if not isinstance(value, str) or not OWNER.fullmatch(value):
            raise HTTPException(401, "账户通知关联尚未通过验证，请重新登录。")
        return value

    def call(fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except NotificationError as error:
            raise HTTPException(error.status, str(error)) from error

    @app.get("/api/notifications/status")
    def status(request: Request, installation_id: str):
        return call(service.status, request.state.identity_id, installation_id, owner_scope=owner(request))

    @app.post("/api/notifications/register")
    def register(request: Request, body: NotificationRegistration):
        if request.scope.get("pajio.cloud_worker") and request.scope.get("pajio.session_expires") is None:
            raise HTTPException(401, "登录关联尚未通过验证，请重新登录后开启通知。")
        return call(service.register, request.state.identity_id, body.installation_id, body.expo_push_token, body.project_id, body.platform,
                    request.scope.get("pajio.session_expires"), owner_scope=owner(request))

    @app.post("/api/notifications/disable")
    def disable(request: Request, body: NotificationDevice):
        return call(service.disable, request.state.identity_id, body.installation_id, owner_scope=owner(request))

    @app.get("/api/notifications/resolve")
    def resolve(request: Request, event_key: str):
        return call(service.resolve, request.state.identity_id, event_key, owner_scope=owner(request))

    @app.post("/api/notifications/disable-installation")
    def disable_installation(request: Request, body: NotificationDevice):
        return call(service.disable_installation, request.state.identity_id, body.installation_id, owner_scope=owner(request))

    @app.get("/api/notifications/preferences")
    def preferences(request: Request, installation_id: str):
        return call(service.preferences, request.state.identity_id, installation_id, owner_scope=owner(request))

    @app.post("/api/notifications/preferences")
    def update_preferences(request: Request, body: NotificationPreferences):
        return call(service.update_preferences, request.state.identity_id, body.installation_id,
                    body.revision, body.enabled, body.start_minute, body.end_minute, body.timezone, owner_scope=owner(request))
