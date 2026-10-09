"""Native cloud-application setup; protected by the existing identity/CSRF gate."""
from fastapi import Request
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from typing import Literal

from .cloud_apps_tools import read_resource


class CloudConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    app_id: str = Field(pattern=r"^cli_[A-Za-z0-9]{6,80}$")
    secret: SecretStr = Field(min_length=12, max_length=160)
    features: list[Literal["documents", "calendar"]] = Field(min_length=1, max_length=2)


class CloudRevision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: str = Field(pattern=r"^[a-f0-9]{32}$")


class CloudPoll(BaseModel):
    model_config = ConfigDict(extra="forbid")
    authorization_id: str = Field(pattern=r"^[a-f0-9]{32}$")


def install_cloud_app_routes(app, service):
    @app.get("/api/cloud-apps/feishu")
    async def state(request: Request):
        return service.snapshot(request.state.identity_id)

    @app.put("/api/cloud-apps/feishu")
    async def configure(request: Request, body: CloudConfiguration):
        return await service.configure(request.state.identity_id, body.app_id, body.secret.get_secret_value(), body.features)

    @app.post("/api/cloud-apps/feishu/authorize")
    async def authorize(request: Request, body: CloudRevision):
        return await service.authorize(request.state.identity_id, body.revision)

    @app.post("/api/cloud-apps/feishu/poll")
    async def poll(request: Request, body: CloudPoll):
        return await service.poll(request.state.identity_id, body.authorization_id)

    @app.post("/api/cloud-apps/feishu/check")
    async def check(request: Request):
        return await service.check(request.state.identity_id)

    @app.delete("/api/cloud-apps/feishu")
    async def disconnect(request: Request, body: CloudRevision):
        return await service.disconnect(request.state.identity_id, body.revision)

    @app.get("/api/cloud-apps/feishu/files")
    async def files(request: Request, folder_token: str | None = None, page_token: str | None = None):
        return await read_resource(service, request.state.identity_id, "cloud_feishu_files", {"folder_token": folder_token, "page_token": page_token})

    @app.get("/api/cloud-apps/feishu/document")
    async def document(request: Request, document: str, kind: Literal["docx", "wiki"] = "docx", offset: int = 0):
        return await read_resource(service, request.state.identity_id, "cloud_feishu_document", {"document": document, "kind": kind, "offset": offset})

    @app.get("/api/cloud-apps/feishu/calendars")
    async def calendars(request: Request, page_token: str | None = None):
        return await read_resource(service, request.state.identity_id, "cloud_feishu_calendars", {"page_token": page_token})

    @app.get("/api/cloud-apps/feishu/events")
    async def events(request: Request, calendar_id: str, start_time: int, end_time: int, page_token: str | None = None):
        return await read_resource(service, request.state.identity_id, "cloud_feishu_events", {"calendar_id": calendar_id, "start_time": start_time, "end_time": end_time, "page_token": page_token})
