"""Authenticated, identity-scoped personal-record routes."""
from typing import Literal
from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from .life import LifeBook, LifeDraft, LifeError


class CreateRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    record: LifeDraft
    request_key: str = Field(min_length=1, max_length=120)


class ChangeRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1)
    action: Literal["edit", "archive", "restore"] = "edit"
    patch: dict = Field(default_factory=dict)
    request_key: str | None = Field(default=None, min_length=1, max_length=120)


def install_life_routes(app, book: LifeBook):
    app.state.life = book

    @app.exception_handler(LifeError)
    async def life_error(request, error):
        return JSONResponse({"detail": str(error)}, status_code=error.status)

    @app.get("/api/life")
    async def snapshot(request: Request, after: int | None = None, include_deleted: bool = False):
        return book.snapshot(request.state.identity_id, after, include_deleted)

    @app.get("/api/life/{record_id}")
    async def get_record(request: Request, record_id: str):
        return book.get(request.state.identity_id, record_id)

    @app.post("/api/life", status_code=201)
    async def create_record(request: Request, body: CreateRecord):
        return book.create(request.state.identity_id, body.record, body.request_key)

    @app.patch("/api/life/{record_id}")
    async def change_record(request: Request, record_id: str, body: ChangeRecord):
        # Validate a merged draft before writing; validation errors use the app's safe handler.
        from pydantic import ValidationError
        from fastapi import HTTPException
        try:
            return book.update(request.state.identity_id, record_id, body.revision, body.patch, action=body.action, request_key=body.request_key)
        except ValidationError as error:
            raise HTTPException(422, "请检查标题、时间及记录类型；原记录没有修改。") from error
