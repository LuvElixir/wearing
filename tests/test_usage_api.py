from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from wearing.usage import UsageBook
from wearing.usage_api import install_usage_routes


def test_existing_usage_route_is_read_only_noncacheable_and_uses_host_identity(tmp_path):
    app, book = FastAPI(), UsageBook(tmp_path, enabled=True)
    call = book.reserve("server-resolved-identity", "model", "fixture")
    book.settle(call, input_tokens=10, output_tokens=2)
    @app.middleware("http")
    async def resolved_identity(request: Request, call_next):
        request.state.identity_id = "server-resolved-identity"
        return await call_next(request)
    install_usage_routes(app, book)
    with TestClient(app) as client:
        response = client.get("/api/usage?identity=other", headers={"X-Wearing-Identity": "other"})
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert response.json()["identity_usage"]["calls"] == 1
        assert client.post("/api/usage", json={"budget": "0"}).status_code == 405
