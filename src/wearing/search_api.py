"""Authenticated identity is supplied by the enclosing application boundary."""
from typing import Literal

from fastapi import HTTPException, Query, Request

from .search import SearchError
from .task_visibility import request_owner


def install_search_routes(app, book, *, local_devices=True):
    app.state.search = book

    @app.get('/api/search')
    def search(request: Request, q: str = Query(min_length=1, max_length=120),
               kind: Literal['all', 'task', 'record', 'message', 'chat_import'] = 'all',
               limit: int = Query(default=20, ge=1, le=50), cursor: str | None = Query(default=None, max_length=2048)):
        try:
            return book.page(request.state.identity_id, q, kind=kind, limit=limit, cursor=cursor,
                             owner_scope=request_owner(request, local_devices=local_devices))
        except SearchError as error:
            raise HTTPException(error.status, str(error)) from error

    @app.get('/api/search/messages/{message_id}')
    def message(message_id: int, request: Request):
        try:
            return book.message(request.state.identity_id, message_id, owner_scope=request_owner(request, local_devices=local_devices))
        except SearchError as error:
            raise HTTPException(error.status, str(error)) from error
