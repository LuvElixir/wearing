"""Bookmark read view; all writes use the existing life/capture APIs."""
from fastapi import Request
from .bookmarks import BookmarkBook


def install_bookmark_routes(app, life):
    book = BookmarkBook(life)

    @app.get('/api/bookmarks')
    async def bookmarks(request: Request, query: str = '', archived: bool = False, limit: int = 30, cursor: str | None = None):
        return book.page(request.state.identity_id, query=query, archived=archived, limit=limit, cursor=cursor)

    return book
