"""Bounded JSON intake after the client's preview; raw archives are not accepted."""
from fastapi import HTTPException, Query, Request
from pydantic import ValidationError

from .chat_imports import ChatImportError, CreateChatImport, MAX_BODY_BYTES
from .task_visibility import request_owner


def install_chat_import_routes(app, book, *, local_devices=True):
    app.state.chat_imports = book

    def call(fn, request, *args, **kwargs):
        try:
            return fn(request.state.identity_id, *args,
                      owner_scope=request_owner(request, local_devices=local_devices), **kwargs)
        except ChatImportError as error:
            raise HTTPException(error.status, str(error)) from None

    @app.post('/api/chat-imports')
    async def create(request: Request):
        # Authenticate before reading an untrusted body and bound chunked input too.
        request_owner(request, local_devices=local_devices)
        if request.headers.get('content-type', '').split(';')[0].strip().lower() != 'application/json':
            raise HTTPException(415, '请先在设备上预览聊天资料，再提交确认后的文本。')
        raw = bytearray()
        async for chunk in request.stream():
            if len(raw) + len(chunk) > MAX_BODY_BYTES:
                raise HTTPException(413, '这批内容超过导入上限，请减少选择的消息。')
            raw.extend(chunk)
        try:
            body = CreateChatImport.model_validate_json(bytes(raw))
        except (ValidationError, ValueError):
            # Validation errors can contain excerpts: never echo them to clients/logs.
            raise HTTPException(422, '聊天资料字段或大小不符合要求，请重新预览后确认。') from None
        return call(book.create, request, body)

    @app.get('/api/chat-imports')
    def page(request: Request, limit: int = Query(default=20, ge=1, le=50),
             cursor: str | None = Query(default=None, max_length=1024)):
        return call(book.page, request, limit=limit, cursor=cursor)

    @app.get('/api/chat-imports/receipts/{request_key}')
    def receipt(request: Request, request_key: str):
        return call(book.receipt, request, request_key)

    @app.get('/api/chat-imports/{import_id}')
    def detail(request: Request, import_id: str):
        return call(book.detail, request, import_id)

    @app.delete('/api/chat-imports/{import_id}')
    async def delete(request: Request, import_id: str):
        async with app.state.service.lock:
            return call(book.delete, request, import_id)
