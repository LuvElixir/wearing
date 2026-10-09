"""Mount behind existing tenant/auth/identity/CSRF boundaries; no support upload."""
from fastapi import HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .health_history import HealthError
from .store import IdentityError

NO_STORE = {'Cache-Control': 'no-store', 'Pragma': 'no-cache', 'X-Content-Type-Options': 'nosniff'}


class HealthExportRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    request_key: str = Field(min_length=16, max_length=80, pattern=r'^[a-zA-Z0-9_-]+$')
    category: str = Field(pattern=r'^(chat|voice|sync|files|notifications|devices|performance|other)$')


def install_health_history_routes(app, history, monitor):
    def owner(request):
        return history.owner(request.scope.get('pajio.storage_scope'))

    def call(function, *args, **kwargs):
        try:
            return function(*args, **kwargs)
        except HealthError as error:
            raise HTTPException(error.status, {'code': error.code}) from None
        except IdentityError:
            raise HTTPException(404, {'code': 'identity_unavailable'}) from None

    @app.get('/api/diagnostics/history')
    async def listing(request: Request, sample_limit: int = Query(48, ge=1, le=288), event_limit: int = Query(100, ge=1, le=500),
                      before_sample: int | None = Query(None, ge=1, le=2**63-1), before_event: int | None = Query(None, ge=1, le=2**63-1)):
        value = call(history.history, request.state.identity_id, call(owner, request), sample_limit=sample_limit, event_limit=event_limit,
                     before_sample=before_sample, before_event=before_event)
        value['sampler_running'] = monitor.running
        return JSONResponse(value, headers=NO_STORE)

    @app.post('/api/diagnostics/sample')
    async def sample(request: Request):
        call(owner, request)
        try:
            observed = await monitor.collect(request.state.identity_id, source='manual')
        except IdentityError:
            raise HTTPException(404, {'code': 'identity_unavailable'}) from None
        except Exception:
            raise HTTPException(503, {'code': 'observation_unavailable'}) from None
        return JSONResponse({'schema': 1, 'sampled': observed}, headers=NO_STORE)

    @app.post('/api/diagnostics/exports', status_code=201)
    async def export(body: HealthExportRequest, request: Request):
        value = call(history.create_export, request.state.identity_id, call(owner, request), body.request_key, body.category)
        return JSONResponse(value, status_code=201, headers=NO_STORE)

    @app.get('/api/diagnostics/exports/{export_id}/file')
    async def download(export_id: str, request: Request):
        raw, metadata = call(history.download, request.state.identity_id, call(owner, request), export_id)
        return Response(raw, media_type='application/json', headers={**NO_STORE,
            'Content-Disposition': f'attachment; filename="{metadata["filename"]}"',
            'X-Content-SHA256': metadata['sha256']})
