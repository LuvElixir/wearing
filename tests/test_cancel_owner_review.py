"""Cancellation authorization is checked before any queue mutation."""
import asyncio

import httpx
import pytest

from wearing.app import create_app
from wearing.cloud.worker import TenantBoundary
from wearing.config import Settings
from wearing.service import TaskError

A, B = "a" * 64, "b" * 64


def queued(app, owner=A):
    store = app.state.store
    active = store.create('synthetic blocker', 'computer')
    store.update(active['id'], status='running')
    task, _ = store.accept_message('synthetic queued', 'daily', 'fixture-request-0001', {'running'}, owner_scope=owner)
    return task['id']


def snapshot(store, task):
    return store.get(task), store.message_receipt(task), store.events(task)


async def test_denied_service_require_cannot_commit_cancellation(tmp_path):
    app = create_app(Settings(tmp_path), engine_autostart=False, local_devices=False)
    task = queued(app)
    before = snapshot(app.state.store, task)
    def denied(_):
        raise TaskError('synthetic guard denial')
    app.state.service.require = denied
    with pytest.raises(TaskError, match='guard denial'):
        await app.state.service.cancel_message(task)
    assert snapshot(app.state.store, task) == before
    await app.state.service.hermes.close()


async def test_foreign_owner_cannot_cancel_queued_task_through_http_or_service(tmp_path):
    app = create_app(Settings(tmp_path), engine_autostart=False, local_devices=False)
    app.add_middleware(TenantBoundary, tenant_id='fixture', gateway_key='fixture-key')
    task = queued(app)
    before = snapshot(app.state.store, task)
    with pytest.raises(TaskError):
        await app.state.service.cancel_message(task, identity_id='daily', owner_scope=B)
    assert snapshot(app.state.store, task) == before
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver', headers={
        'Authorization':'Bearer fixture-key','X-Wearing-Tenant':'fixture','X-Pajio-Storage-Scope':B}) as client:
        client.headers['X-Wearing-Token'] = (await client.get('/api/bootstrap')).json()['token']
        assert (await client.post(f'/api/tasks/{task}/cancel-message')).status_code == 404
        assert snapshot(app.state.store, task) == before
        client.headers['X-Pajio-Storage-Scope'] = A
        assert (await client.post(f'/api/tasks/{task}/cancel-message')).json()['status'] == 'stopped'
        assert app.state.store.message_receipt(task)['queue_state'] == 'cancelled'
    await app.state.service.hermes.close()


async def test_owner_added_while_waiting_for_service_lock_is_rechecked_before_mutation(tmp_path):
    app = create_app(Settings(tmp_path), engine_autostart=False, local_devices=False)
    app.add_middleware(TenantBoundary, tenant_id='fixture', gateway_key='fixture-key')
    task = queued(app, owner=None)
    before = snapshot(app.state.store, task)
    service = app.state.service
    entered = asyncio.Event()
    cancel = service.cancel_message
    async def observe(*args, **kwargs):
        entered.set()
        return await cancel(*args, **kwargs)
    service.cancel_message = observe
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver', headers={
        'Authorization':'Bearer fixture-key','X-Wearing-Tenant':'fixture','X-Pajio-Storage-Scope':B}) as client:
        client.headers['X-Wearing-Token'] = (await client.get('/api/bootstrap')).json()['token']
        async with service.lock:
            pending = asyncio.create_task(client.post(f'/api/tasks/{task}/cancel-message'))
            await asyncio.wait_for(entered.wait(), 2)
            with app.state.store.connection() as db:
                app.state.store.bind_task_principal(db, task, A)
            before = snapshot(app.state.store, task)  # Binding intentionally creates an isolated owner session.
        response = await pending
        assert response.status_code == 409
        assert snapshot(app.state.store, task) == before
    await service.hermes.close()
