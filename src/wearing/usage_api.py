"""Read-only native trial usage, behind the host identity/auth middleware."""
import asyncio
from fastapi import Request


def install_usage_routes(app, usage):
    @app.get("/api/usage")
    async def snapshot(request: Request):
        return await asyncio.to_thread(usage.snapshot, request.state.identity_id)
