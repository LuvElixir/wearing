"""Authenticated owner decisions; never receives an owner from the request body."""
from typing import Literal
from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from .ai_consent import ConsentBook, ConsentError


class ConsentDecision(BaseModel):
    model_config = ConfigDict(extra='forbid')
    action: Literal['accept', 'revoke']
    policy_version: str = Field(min_length=1, max_length=80, strict=True)
    expected_revision: int = Field(ge=0, strict=True)
    request_id: str = Field(pattern=r'^[a-f0-9]{32}$', strict=True)


def install_consent_routes(app, data_dir, *, local_devices):
    def actor(request):
        value = request.scope.get('pajio.private_owner_scope')
        if (local_devices or request.scope.get('pajio.cloud_worker') is not True
                or value != request.scope.get('pajio.storage_scope')):
            raise ConsentError('ai_consent_private_owner_required', 403)
        return value

    @app.get('/api/ai-consent')
    async def snapshot(request: Request):
        try:
            owner = actor(request)
            return JSONResponse(ConsentBook(data_dir, create=True).snapshot(request.state.identity_id, owner), headers={'Cache-Control': 'no-store'})
        except ConsentError as error: return JSONResponse({'code': error.code, 'detail': str(error)}, status_code=error.status, headers={'Cache-Control': 'no-store'})

    @app.post('/api/ai-consent')
    async def change(request: Request, body: ConsentDecision):
        try:
            owner = actor(request)
            return JSONResponse(ConsentBook(data_dir, create=True).change(request.state.identity_id, owner, **body.model_dump()), headers={'Cache-Control': 'no-store'})
        except ConsentError as error: return JSONResponse({'code': error.code, 'detail': str(error)}, status_code=error.status, headers={'Cache-Control': 'no-store'})
