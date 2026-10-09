"""Register behind the application's existing credential, CSRF and identity gates."""
import asyncio
from fastapi import HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from .identity_export import ExportError
from .task_visibility import request_owner


class ExportRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_key: str = Field(min_length=16, max_length=80, pattern=r'^[A-Za-z0-9_-]+$')


def install_identity_export_routes(app, exports, *, local_devices=True):
    def owner(request):
        return request_owner(request, local_devices=local_devices)

    async def call(function, *args, **kwargs):
        try: return await asyncio.to_thread(function, *args, **kwargs)
        except ExportError as error: raise HTTPException(error.status, str(error)) from None

    @app.get('/api/data-exports')
    async def listing(request: Request):
        return {'exports': await call(exports.list, request.state.identity_id, owner_scope=owner(request))}

    @app.post('/api/data-exports', status_code=201)
    async def create(body: ExportRequest, request: Request):
        return await call(exports.create, request.state.identity_id, body.request_key, owner_scope=owner(request))

    @app.get('/api/data-exports/{export_id}')
    async def metadata(export_id: str, request: Request):
        return await call(exports.metadata, request.state.identity_id, export_id, owner_scope=owner(request))

    @app.get('/api/data-exports/{export_id}/file')
    async def download(export_id: str, request: Request):
        raw, value = await call(exports.download, request.state.identity_id, export_id, owner_scope=owner(request))
        return Response(raw, media_type='application/zip', headers={'Content-Disposition': f'attachment; filename="{value["filename"]}"', 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})
