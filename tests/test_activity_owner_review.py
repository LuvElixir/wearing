"""Real ASGI owner projection; temporary stores and no engine/provider calls."""
import httpx
import pytest

from wearing.activity import ActivityBook, ActivityError
from wearing.app import create_app
from wearing.cloud.worker import TenantBoundary
from wearing.config import Settings
from wearing.store import Store

A, B = "a" * 64, "b" * 64


def create_result(store, owner=None, identity="daily"):
    task = store.create("synthetic private result", "computer", identity)
    if owner:
        with store.connection() as db:
            store.bind_task_principal(db, task["id"], owner)
    store.update(task["id"], status="completed_unverified", output=f"result for {owner or 'legacy'}")
    return task["id"]


def seen(item):
    return {key: item[key] for key in ("task_id", "version")}


async def test_two_accounts_activity_details_and_seen_have_same_visibility(tmp_path):
    app = create_app(Settings(tmp_path), engine_autostart=False, local_devices=False)
    app.add_middleware(TenantBoundary, tenant_id="fixture", gateway_key="fixture-internal")
    store = app.state.activity.store
    own_a, own_b, legacy = create_result(store, A), create_result(store, B), create_result(store)
    other_identity = store.save_identity("other fixture")["id"]
    foreign_identity = create_result(store, A, other_identity)
    headers = {"Authorization": "Bearer fixture-internal", "X-Wearing-Tenant": "fixture"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver", headers=headers) as client:
        client.headers["X-Wearing-Token"] = (await client.get("/api/bootstrap")).json()["token"]
        client.headers["X-Pajio-Storage-Scope"] = A
        first = (await client.get("/api/activity")).json()
        assert {item["task_id"] for item in first["items"]} == {own_a, legacy}
        assert first["total"] == first["unread"] == 2
        private = next(item for item in first["items"] if item["task_id"] == own_a)
        assert (await client.get(f"/api/tasks/{own_a}")).status_code == 200
        assert (await client.get(f"/api/tasks/{own_b}")).status_code == 404
        assert (await client.get(f"/api/tasks/{foreign_identity}")).status_code == 404
        cursor = (await client.get("/api/activity", params={"limit": 1})).json()["next_cursor"]
        client.headers["X-Pajio-Storage-Scope"] = B
        second = (await client.get("/api/activity", params={"owner_scope": A})).json()
        assert {item["task_id"] for item in second["items"]} == {own_b, legacy}
        assert own_a not in str(second) and second["total"] == 2
        assert second["revision"] != first["revision"]
        assert (await client.get("/api/activity", params={"cursor": cursor})).status_code == 409
        assert (await client.get(f"/api/tasks/{own_a}")).status_code == 404
        assert (await client.get(f"/api/tasks/{legacy}")).status_code == 200
        own_item = next(item for item in second["items"] if item["task_id"] == own_b)
        response = await client.post("/api/activity/seen", json={"items": [seen(own_item), seen(private)]})
        assert response.status_code == 409  # All-or-none, never partial acknowledgement.
        with store.connection() as db:
            assert db.execute("SELECT count(*) FROM activity_reads").fetchone()[0] == 0
        assert (await client.post("/api/activity/seen", json={"items": [seen(own_item)]})).json()["unread"] == 1
        client.headers["X-Pajio-Storage-Scope"] = A
        assert (await client.get("/api/activity")).json()["unread"] == 2
        assert (await client.post("/api/activity/seen", json={"items": [seen(private)], "owner_scope": B})).status_code == 422
        assert (await client.post("/api/activity/seen", json={"items": [seen(private)]})).json()["unread"] == 1
    await app.state.service.hermes.close()


@pytest.mark.parametrize("boundary", [False, True])
async def test_cloud_requires_trusted_owner_not_raw_header_or_query(tmp_path, boundary):
    app = create_app(Settings(tmp_path), engine_autostart=False, local_devices=False)
    headers = {"X-Pajio-Storage-Scope": A}
    if boundary:
        app.add_middleware(TenantBoundary, tenant_id="fixture", gateway_key="fixture-internal")
        headers = {"Authorization": "Bearer fixture-internal", "X-Wearing-Tenant": "fixture"}
    legacy = create_result(app.state.activity.store)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver", headers=headers) as client:
        client.headers["X-Wearing-Token"] = (await client.get("/api/bootstrap")).json()["token"]
        assert (await client.get("/api/activity", params={"owner_scope": A})).status_code == 401
        assert (await client.post("/api/activity/seen", json={"items": [{"task_id": legacy, "version": "c" * 64}]})).status_code == 401
    await app.state.service.hermes.close()


def test_owner_bound_pagination_and_receipts_survive_restart_even_with_only_shared_tasks(tmp_path):
    store = Store(tmp_path / "fixture.sqlite3")
    create_result(store)
    create_result(store)
    book = ActivityBook(store, require_owner=True)
    page = book.snapshot(owner_scope=A, limit=1)
    reopened = ActivityBook(Store(store.path), require_owner=True)
    assert reopened.snapshot(owner_scope=A, cursor=page["next_cursor"])["total"] == 2
    with pytest.raises(ActivityError):
        reopened.snapshot(owner_scope=B, cursor=page["next_cursor"])
    with pytest.raises(PermissionError):
        reopened.snapshot()
    reopened.acknowledge("daily", [seen(page["items"][0])], owner_scope=A)
    # Explicitly unowned legacy tasks retain the identity's existing read semantics.
    assert reopened.snapshot(owner_scope=B)["unread"] == 1
    with store.connection() as db:
        assert len(book._items(db, "daily")) == 2


def test_detail_snapshot_and_read_receipt_survive_concurrent_result_update(tmp_path, monkeypatch):
    store = Store(tmp_path / 'fixture.sqlite3')
    task = create_result(store, A)
    book = ActivityBook(store, require_owner=True)
    with store.connection() as db:
        db.execute('PRAGMA journal_mode=WAL')
    original = book._items
    changed = False
    def concurrent(db, identity, **kwargs):
        nonlocal changed
        if not changed:
            changed = True
            store.update(task, output='new synthetic result after snapshot began')
        return original(db, identity, **kwargs)
    monkeypatch.setattr(book, '_items', concurrent)
    rendered = book.detail_snapshot('daily', task, A)
    assert rendered['output'] == 'result for ' + A
    assert rendered['delivery'] == 'submitted' and rendered['queue_state'] is None
    assert rendered['activity_receipt']['task_id'] == task
    assert book.detail_snapshot('daily', task, B) is None
    assert book.detail_snapshot('daily', 'does-not-exist', A) is None
    newer = book.snapshot(owner_scope=A)['items'][0]
    assert newer['version'] != rendered['activity_receipt']['version']
    # An old, genuinely rendered result is accepted as a no-op, not promoted to
    # the latest version. Only viewing the new detail can acknowledge it.
    assert book.acknowledge('daily', [rendered['activity_receipt']], owner_scope=A)['unread'] == 1
    current = book.detail_snapshot('daily', task, A)
    assert current['output'].startswith('new synthetic')
    assert book.acknowledge('daily', [current['activity_receipt']], owner_scope=A)['unread'] == 0
    store.update(task, status='running')
    assert book.detail_snapshot('daily', task, A)['activity_receipt'] is None
    with pytest.raises(PermissionError): book.detail_snapshot('daily', task)


async def test_http_task_detail_returns_exact_rendered_receipt(tmp_path):
    app = create_app(Settings(tmp_path), engine_autostart=False, local_devices=False)
    app.add_middleware(TenantBoundary, tenant_id='fixture', gateway_key='fixture-key')
    task = create_result(app.state.store, A)
    headers = {'Authorization': 'Bearer fixture-key', 'X-Wearing-Tenant': 'fixture', 'X-Pajio-Storage-Scope': A}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver', headers=headers) as client:
        client.headers['X-Wearing-Token'] = (await client.get('/api/bootstrap')).json()['token']
        response = await client.get('/api/tasks/' + task)
        assert response.status_code == 200
        value = response.json()
        assert set(value['activity_receipt']) == {'task_id', 'version'}
        assert value['output'] == 'result for ' + A
        assert 'payload' not in value and 'idempotency_key' not in value
        assert {'queue_state', 'queued', 'delivery', 'events', 'artifacts'} <= value.keys()
        app.state.store.update(task, output='later output')
        result = await client.post('/api/activity/seen', json={'items': [value['activity_receipt']]})
        assert result.status_code == 200 and result.json()['unread'] == 1
        client.headers['X-Pajio-Storage-Scope'] = B
        assert (await client.get('/api/tasks/' + task)).status_code == 404
        assert (await client.post('/api/activity/seen', json={'items': [value['activity_receipt']]})).status_code == 409
    await app.state.service.hermes.close()
