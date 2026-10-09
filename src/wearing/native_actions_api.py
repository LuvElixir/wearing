"""Product-authenticated routes. Phone secrets never enter Agent tools/results."""
from fastapi import HTTPException, Request
from pydantic import Field, SecretStr, ValidationError
import re
from .native_actions import NativeActionError
from .native_actions_contract import Strict, NativePolicy, NativeOutcome


class Phone(Strict):
    installation_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    secret: SecretStr


class Configure(Phone):
    revision: int = Field(ge=0)
    enabled: bool
    policy: NativePolicy
    name: str = Field(default="我的 iPhone", min_length=1, max_length=60)


class Session(Phone):
    connection_id: str = Field(pattern=r"^[a-f0-9]{32}$")


class Connect(Session):
    revision: int = Field(ge=1)
    capabilities: list[str] = Field(max_length=9)


class Action(Session):
    command_id: str = Field(pattern=r"^native_[a-f0-9]{32}$")
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")


class Claim(Action):
    approve: bool


class Finish(Action):
    outcome: NativeOutcome


class Review(Phone):
    command_id: str = Field(pattern=r"^native_[a-f0-9]{32}$")


def install_native_action_routes(app, service):
    def call(method, request, body=None, **extra):
        owner_scope = "local"
        if request.scope.get("pajio.cloud_worker"):
            owner_scope = request.scope.get("pajio.storage_scope")
            if not isinstance(owner_scope, str) or not re.fullmatch(r"[a-f0-9]{64}", owner_scope):
                raise HTTPException(401, "手机能力尚未关联当前账户，请重新登录。")
        values = body.model_dump() if body else {}
        if body:
            values["secret"] = body.secret.get_secret_value()
            values["installation"] = values.pop("installation_id")
            if "connection_id" in values:
                values["connection"] = values.pop("connection_id")
        try:
            return getattr(service, method)(request.state.identity_id, owner_scope=owner_scope, **values, **extra)
        except NativeActionError as error:
            raise HTTPException(error.status, str(error)) from error
        except (ValidationError, ValueError) as error:
            raise HTTPException(422, "手机请求不完整或超过允许范围。") from error

    @app.get("/api/native-actions/devices")
    def devices(request: Request):
        return {"items": call("devices", request)}

    @app.post("/api/native-actions/configure")
    def configure(request: Request, body: Configure):
        return call("configure", request, body)

    @app.post("/api/native-actions/connect")
    def connect(request: Request, body: Connect):
        return call("connect", request, body)

    @app.post("/api/native-actions/poll")
    def poll(request: Request, body: Session):
        return call("poll", request, body)

    @app.post("/api/native-actions/disconnect")
    def disconnect(request: Request, body: Session):
        return call("disconnect", request, body)

    @app.post("/api/native-actions/claim")
    def claim(request: Request, body: Claim):
        return call("claim", request, body)

    @app.post("/api/native-actions/result")
    def finish(request: Request, body: Finish):
        return call("finish", request, body)

    @app.post("/api/native-actions/history")
    def history(request: Request, body: Phone):
        return call("history", request, body)

    @app.post("/api/native-actions/review")
    def review(request: Request, body: Review):
        return call("review", request, body)
