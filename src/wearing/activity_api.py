"""Identity-scoped progress snapshots and explicit result read receipts."""

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from .activity import ActivityError


class SeenActivityItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: str = Field(min_length=1, max_length=64, strict=True)
    version: str = Field(pattern=r"^[a-f0-9]{64}$", strict=True)


class SeenActivity(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[SeenActivityItem] = Field(min_length=1, max_length=100)


def install_activity_routes(app, book):
    app.state.activity = book

    @app.get("/api/activity")
    def activity(request: Request):
        return book.snapshot(request.state.identity_id)

    @app.post("/api/activity/seen")
    def seen_activity(body: SeenActivity, request: Request):
        try:
            return book.acknowledge(request.state.identity_id, [item.model_dump() for item in body.items])
        except ActivityError as error:
            raise HTTPException(409, str(error)) from error
