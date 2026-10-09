"""Identity-scoped progress snapshots and explicit result read receipts."""

from typing import Literal

from fastapi import HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from .activity import ActivityError, ActivityQueryError


class SeenActivityItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: str = Field(min_length=1, max_length=64, strict=True)
    version: str = Field(pattern=r"^[a-f0-9]{64}$", strict=True)


class SeenActivity(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[SeenActivityItem] = Field(min_length=1, max_length=100)


def install_activity_routes(app, book):
    app.state.activity = book

    def owner(request):
        # Only TenantBoundary may turn a gateway-authenticated header into
        # this ASGI field. A public header/query/body is never authority.
        return book.owner(request.scope.get("pajio.storage_scope"),
                          require_owner=bool(request.scope.get("pajio.cloud_worker")))

    @app.get("/api/activity")
    def activity(request: Request, limit: int = Query(default=20, ge=1, le=100),
                 cursor: str | None = Query(default=None, min_length=1, max_length=2048),
                 bucket: Literal["attention", "active", "waiting", "results"] | None = None,
                 since: str | None = Query(default=None, pattern=r"^[a-f0-9]{64}$")):
        try:
            return book.snapshot(request.state.identity_id, limit=limit, cursor=cursor, bucket=bucket, since=since,
                                 owner_scope=owner(request))
        except PermissionError as error:
            raise HTTPException(401, str(error)) from error
        except ActivityQueryError as error:
            raise HTTPException(422, str(error)) from error
        except ActivityError as error:
            raise HTTPException(409, str(error)) from error

    @app.post("/api/activity/seen")
    def seen_activity(body: SeenActivity, request: Request):
        try:
            return book.acknowledge(request.state.identity_id, [item.model_dump() for item in body.items],
                                    owner_scope=owner(request))
        except PermissionError as error:
            raise HTTPException(401, str(error)) from error
        except ActivityError as error:
            raise HTTPException(409, str(error)) from error
