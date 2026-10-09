"""Read-only, identity-bound native file pages and exact metadata."""
import asyncio
from fastapi import HTTPException, Query, Request
from .workspace import WorkspacePager, WorkspacePageError, file_metadata


def install_workspace_page_routes(app, store, runtime_for):
    pager = WorkspacePager()
    app.state.workspace_pager = pager

    @app.get('/api/workspace/page')
    async def page(request: Request, directory: str = '', query: str = '', cursor: str | None = None,
                   limit: int = Query(200, ge=1, le=200)):
        identity = request.state.identity_id
        store.identity(identity)
        try:
            return await asyncio.to_thread(pager.page, runtime_for(identity).workspace, identity,
                                           directory=directory, query=query, cursor=cursor, limit=limit)
        except WorkspacePageError as error:
            raise HTTPException(error.status, str(error)) from error

    @app.get('/api/workspace/metadata')
    async def metadata(request: Request, path: str):
        identity = request.state.identity_id
        store.identity(identity)
        try: return await asyncio.to_thread(file_metadata, runtime_for(identity).workspace, path)
        except WorkspacePageError as error:
            raise HTTPException(error.status, str(error)) from error

    return pager
