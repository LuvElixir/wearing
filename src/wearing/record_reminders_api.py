"""Private record reminder settings; caller ownership comes only from trusted ASGI."""
from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from .record_reminders import ReminderError
from .task_visibility import request_owner


class ReminderSettings(BaseModel):
    model_config = ConfigDict(extra='forbid')
    revision: int = Field(ge=0, strict=True)
    record_revision: int = Field(ge=1, strict=True)
    enabled: bool = Field(strict=True)
    advance_minutes: int = Field(ge=0, le=1440, strict=True)
    request_key: str = Field(min_length=16, max_length=120, pattern=r'^[A-Za-z0-9_-]+$')


def install_record_reminder_routes(app, book, *, local_devices=True):
    def call(fn, request, target, **kwargs):
        try:
            return fn(request.state.identity_id, target, owner_scope=request_owner(request, local_devices=local_devices), **kwargs)
        except ReminderError as error:
            raise HTTPException(error.status, str(error)) from error

    @app.get('/api/record-reminders/{target}')
    def get(request: Request, target: str):
        return call(book.get, request, target)

    @app.post('/api/record-reminders/{target}')
    def save(request: Request, target: str, body: ReminderSettings):
        return call(book.save, request, target, **body.model_dump())
