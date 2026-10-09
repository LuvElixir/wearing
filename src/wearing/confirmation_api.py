"""Identity-bound durable decisions; resuming rechecks, never approves."""
from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from .durable_confirmations import ConfirmationError
from .task_visibility import request_owner


class ResumeDecision(BaseModel):
    model_config = ConfigDict(extra='forbid')
    revision: int = Field(ge=1, strict=True)
    request_key: str = Field(pattern=r"^[A-Za-z0-9_-]{16,120}$", strict=True)


def install_confirmation_routes(app, service, public_task, *, local_devices=True):
    @app.get('/api/confirmations')
    async def list_decisions(request: Request):
        return {'items': service.confirmations.durable.list(request.state.identity_id, owner_scope=request_owner(request, local_devices=local_devices))}

    @app.post('/api/confirmations/{action_id}/resume')
    async def resume_decision(action_id: str, body: ResumeDecision, request: Request):
        identity = request.state.identity_id
        try:
            service.confirmations.durable.get(identity, action_id, owner_scope=request_owner(request, local_devices=local_devices))
        except ConfirmationError as error:
            raise HTTPException(404, '当前身份没有这项确认。') from error
        try:
            result = await service.resume_confirmation(identity, action_id, body.revision, body.request_key, owner_scope=request_owner(request, local_devices=local_devices))
            return {**result, 'task': public_task(result['task'])}
        except ConfirmationError as error:
            raise HTTPException(409, str(error)) from error
