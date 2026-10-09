"""Conversation-source routes, with exact owner from trusted request scope."""
from fastapi import HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from .conversation_sources import SourceError
from .task_visibility import request_owner


class ExcludeSource(BaseModel):
    model_config = ConfigDict(extra='forbid')
    source_id: str = Field(pattern=r'^source_[a-f0-9]{64}$')
    source_revision: str = Field(pattern=r'^[a-f0-9]{64}$')
    revision: int = Field(ge=0, strict=True)
    request_key: str = Field(min_length=16, max_length=120, pattern=r'^[A-Za-z0-9_-]+$')


def install_conversation_source_routes(app, book, *, local_devices=True):
    def call(fn, request, **kwargs):
        try:
            return fn(request.state.identity_id, owner_scope=request_owner(request, local_devices=local_devices), **kwargs)
        except SourceError as error:
            raise HTTPException(error.status, str(error)) from error

    @app.get('/api/conversation-sources')
    def page(request: Request, offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=50), snapshot: str | None = Query(None, max_length=64)):
        return call(book.page, request, offset=offset, limit=limit, snapshot=snapshot)

    @app.post('/api/conversation-sources/exclude')
    def exclude(request: Request, body: ExcludeSource):
        return call(book.exclude, request, **body.model_dump())
