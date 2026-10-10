"""Capture/upload routes inherit Wearing's origin, token and tenant gates."""
from fastapi import Request
from fastapi.responses import FileResponse

from .capture import CaptureDraft, MAX_ASSET_BYTES
from .life import LifeError
from .ai_consent import ConsentBook, ConsentError


def install_capture_routes(app,book,worker):
    def organization_owner(request):
        if worker.local_devices: return None
        from .task_visibility import request_owner
        actor = request_owner(request, local_devices=False)
        if request.scope.get('pajio.private_owner_scope') != actor:
            raise LifeError('AI 整理需要经过验证的个人空间。', 403)
        try: ConsentBook(book.store.path.parent).require(request.state.identity_id, actor=actor)
        except ConsentError as error: raise LifeError(str(error), error.status) from error
        return actor
    @app.get("/api/capture/capabilities")
    async def capabilities():return worker.capabilities()

    @app.post("/api/life/assets",status_code=201)
    async def upload(request:Request,name:str="原件",request_key:str=""):
        data=bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data)>MAX_ASSET_BYTES:raise LifeError("文件超过 15 MB，请选一份较小的原件。",413)
        return book.upload(request.state.identity_id,bytes(data),name,request.headers.get("content-type",""),request_key)

    @app.get("/api/life/assets/{asset_id}")
    async def original(request:Request,asset_id:str):
        path,asset=book.file(request.state.identity_id,asset_id)
        response=FileResponse(path,media_type=asset["mime"],filename=asset["name"],content_disposition_type="inline")
        response.headers.update({"Cache-Control":"private, no-store","X-Content-Type-Options":"nosniff"})
        return response

    @app.post("/api/captures",status_code=201)
    async def create(request:Request,body:CaptureDraft):
        actor = organization_owner(request) if body.organize else None
        job=book.create(request.state.identity_id,body,owner_scope=actor)
        return {"record":book.life.get(request.state.identity_id,job["record_id"])}

    @app.post("/api/life/assets/{asset_id}/transcribe")
    async def transcribe(request:Request,asset_id:str):
        # Transcription is input preparation, never an inferred note or an action.
        return await worker.transcribe_voice(request.state.identity_id, asset_id)

    @app.post("/api/captures/{capture_id}/retry")
    async def retry(request:Request,capture_id:str):
        actor = organization_owner(request)
        if actor is not None and book.get(request.state.identity_id, capture_id).get('owner_scope') != actor:
            raise LifeError('旧记录的 AI 整理归属无法核对，原件仍保留。', 403)
        job=book.retry(request.state.identity_id,capture_id)
        return {"record":book.life.get(request.state.identity_id,job["record_id"])}
