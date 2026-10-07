"""Identity-scoped schedule routes, behind the same auth/CSRF boundary as chat."""
from typing import Literal
from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from .schedules import ScheduleDraft, ScheduleError
from .store import now


class CreateSchedule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schedule: ScheduleDraft
    request_key: str = Field(min_length=1, max_length=120)


class ChangeSchedule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1, strict=True)
    action: Literal["pause", "resume", "edit", "cancel"]
    schedule: ScheduleDraft | None = None


def install_schedule_routes(app, book):
    @app.exception_handler(ScheduleError)
    async def schedule_error(request, error):
        return JSONResponse({"detail": str(error)}, status_code=error.status)

    @app.get("/api/schedules")
    async def list_schedules(request: Request):
        return {"items": book.list(request.state.identity_id), "execution": "service_required", "delivery": "conversation", "server_time": now()}

    @app.post("/api/schedules", status_code=201)
    async def create_schedule(body: CreateSchedule, request: Request):
        return book.create(request.state.identity_id, body.schedule, body.request_key)

    @app.get("/api/schedules/{schedule_id}")
    async def get_schedule(schedule_id: str, request: Request):
        return book.get(request.state.identity_id, schedule_id)

    @app.patch("/api/schedules/{schedule_id}")
    async def change_schedule(schedule_id: str, body: ChangeSchedule, request: Request):
        return book.change(request.state.identity_id, schedule_id, body.revision, body.action, body.schedule)
