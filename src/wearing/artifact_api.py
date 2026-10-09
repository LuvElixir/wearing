"""Preview HTML in an opaque browser sandbox, never in the application document."""
from fastapi import Request
from fastapi.responses import JSONResponse, Response

from .artifacts import ArtifactError
from .artifact_choices import ArtifactChoices, ChoiceRequest
from .task_visibility import request_owner

# Header sandbox also protects direct navigation to the preview URL. Keep this
# independent of the iframe attribute; never grant allow-same-origin.
PREVIEW_CSP = "sandbox allow-scripts; default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; font-src data:; media-src data:; connect-src 'none'; frame-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'self'"


def install_artifact_routes(app, book, *, local_devices=True):
    app.state.artifacts = book
    choices = ArtifactChoices(book)
    app.state.artifact_choices = choices

    def owner(request):
        return request_owner(request, local_devices=local_devices)

    @app.exception_handler(ArtifactError)
    async def error(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=exc.status)

    @app.get("/api/artifacts")
    async def listing(request: Request):
        return {"items": book.list(request.state.identity_id, owner_scope=owner(request))}

    @app.get("/api/artifacts/{artifact_id}")
    async def metadata(request: Request, artifact_id: str):
        item, _ = book.get(request.state.identity_id, artifact_id, content=True, owner_scope=owner(request))
        return item

    @app.get("/api/artifacts/{artifact_id}/choices")
    async def choice_state(request: Request, artifact_id: str):
        return choices.state(request.state.identity_id, artifact_id, owner(request))

    @app.post("/api/artifacts/{artifact_id}/choices", status_code=201)
    async def choose(request: Request, artifact_id: str, body: ChoiceRequest):
        return choices.select(request.state.identity_id, artifact_id, body, owner(request))

    @app.get("/api/artifacts/{artifact_id}/preview")
    async def preview(request: Request, artifact_id: str):
        _, raw = book.get(request.state.identity_id, artifact_id, content=True, owner_scope=owner(request))
        return Response(raw, media_type="text/html; charset=utf-8", headers={
            "Content-Security-Policy": PREVIEW_CSP,
            "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=(), clipboard-read=(), clipboard-write=()",
            "X-DNS-Prefetch-Control": "off",
        })

    @app.get("/api/artifacts/{artifact_id}/download")
    async def download(request: Request, artifact_id: str):
        item, raw = book.get(request.state.identity_id, artifact_id, content=True, owner_scope=owner(request))
        return Response(raw, media_type="application/octet-stream", headers={
            "Content-Disposition": f'attachment; filename="wearing-{item["id"]}-v{item["revision"]}.html"',
        })
