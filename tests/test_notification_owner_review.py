"""Independent regressions: isolated stores, clock and transport; no real push."""
import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import httpx
import pytest

from wearing.notifications import NotificationConfig, NotificationError, NotificationService
from wearing.store import Store

PROJECT = "12345678-abcd-1234-abcd-123456789abc"
PHONE = "review-phone-0012"
TOKEN = "ExpoPushToken[syntheticToken12345]"
A, B = "a" * 64, "b" * 64


def stamp(value):
    return datetime.fromisoformat(value).timestamp()


@pytest.fixture
async def env(tmp_path):
    now, calls = [stamp("2026-10-08T22:00:00+08:00")], []
    def request(req):
        calls.append(req)
        return httpx.Response(200, json={"data": {"status": "ok", "id": f"review-{len(calls)}"}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(request)) as client:
        store = Store(tmp_path / "owner.db")
        service = NotificationService(store, config=NotificationConfig(True, PROJECT), client=client, clock=lambda: now[0])
        yield service, store, now, calls


def register(service, owner=A, *, identity="daily", token=TOKEN):
    return service.register(identity, PHONE, token, PROJECT, "ios", service.clock() + 8 * 3600, owner_scope=owner)


def result(store, identity="daily"):
    task = store.create("synthetic notification review", "hermes", identity_id=identity)
    store.update(task["id"], status="completed_unverified", output="synthetic result")
    return task["id"]


def rows(store):
    with store.connection() as db:
        return [dict(r) for r in db.execute("SELECT * FROM notification_outbox ORDER BY rowid")]


async def test_two_accounts_same_identity_only_task_owner_gets_outbox_and_push(env):
    service, store, _, calls = env
    register(service, A)
    phone_b, token_b = "review-phone-B-0012", "ExpoPushToken[syntheticOther12345]"
    service.register("daily", phone_b, token_b, PROJECT, "ios", service.clock() + 3600, owner_scope=B)
    task = result(store)
    with store.connection() as db:
        store.bind_task_principal(db, task, A)
    service.collect()
    assert [(row["owner_scope"], row["installation_id"]) for row in rows(store)] == [(A, PHONE)]
    event = rows(store)[0]["event_key"]
    assert service.resolve("daily", event, owner_scope=A)["task_id"] == task
    with pytest.raises(NotificationError) as error:
        service.resolve("daily", event, owner_scope=B)
    assert error.value.status == 404
    await service.tick()
    assert [json.loads(call.content)["to"] for call in calls] == [TOKEN]
    assert service.status("daily", phone_b, owner_scope=B)["counts"] == {}


async def test_pre_upgrade_misrouted_pending_outbox_cannot_send_or_resolve(env):
    service, store, _, calls = env
    register(service, B)
    task = result(store)
    service.collect()  # Simulates a pre-upgrade fanout without owner filtering.
    event = rows(store)[0]["event_key"]
    with store.connection() as db:
        store.bind_task_principal(db, task, A)
    restarted = NotificationService(store, config=service.config, client=service.client, clock=service.clock)
    with pytest.raises(NotificationError) as error:
        restarted.resolve("daily", event, owner_scope=B)
    assert error.value.status == 404
    await restarted.tick()
    assert calls == []
    assert (rows(store)[0]["state"], rows(store)[0]["error_code"]) == ("cancelled", "TaskNotVisible")


async def test_owner_is_rechecked_at_final_handoff_after_claim(env):
    service, store, _, calls = env
    register(service, B)
    task = result(store)
    service.collect()
    claimed = service._claim()
    assert claimed and claimed["owner_scope"] == B
    with store.connection() as db:
        store.bind_task_principal(db, task, A)
    assert service._delivery_authorized(claimed) is False
    await service.tick()
    assert calls == [] and rows(store)[0]["state"] == "cancelled"


async def test_unowned_legacy_results_remain_shared_without_assigning_an_owner(env):
    service, store, _, calls = env
    register(service, A)
    service.register("daily", "review-phone-B-0012", "ExpoPushToken[syntheticOther12345]", PROJECT,
                     "ios", service.clock() + 3600, owner_scope=B)
    task = result(store)
    service.collect()
    assert {row["owner_scope"] for row in rows(store)} == {A, B}
    for owner in (A, B):
        assert service.resolve("daily", rows(store)[0]["event_key"], owner_scope=owner)["task_id"] == task
    with store.connection() as db:
        assert db.execute("SELECT count(*) FROM task_principals").fetchone()[0] == 0
    await service.tick()
    assert len(calls) == 2


async def test_overnight_expired_lease_waits_for_authorization_then_sends_once(env):
    service, store, now, calls = env
    register(service)
    service.update_preferences("daily", PHONE, 0, True, 1320, 480, "Asia/Shanghai", owner_scope=A)
    result(store)
    await service.tick()
    assert rows(store)[0]["error_code"] == "QuietHours" and calls == []
    now[0] = stamp("2026-10-09T08:00:00+08:00")
    await service.tick()
    assert rows(store)[0]["state"] == "awaiting_registration" and calls == []
    restarted = NotificationService(store, config=service.config, client=service.client, clock=service.clock)
    register(restarted)
    await asyncio.gather(service.tick(), restarted.tick())
    assert len(calls) == 1 and rows(store)[0]["state"] == "ticket"
    register(restarted)
    await restarted.tick()
    assert len(calls) == 1


@pytest.mark.parametrize("cancel", ["disable", "superseded"])
async def test_awaiting_explicit_disable_or_superseded_is_never_backfilled(env, cancel):
    service, store, now, calls = env
    register(service)
    service.update_preferences("daily", PHONE, 0, True, 1320, 480, "Asia/Shanghai", owner_scope=A)
    task = result(store)
    await service.tick()
    now[0] += 10 * 3600
    await service.tick()
    if cancel == "disable":
        service.disable("daily", PHONE, owner_scope=A)
    else:
        store.update(task, status="verified")
    register(service)
    await service.tick()
    assert calls == [] and rows(store)[0]["state"] == "cancelled"


async def test_results_while_registration_expired_are_held_until_same_owner_returns(env):
    service, store, now, calls = env
    register(service)
    now[0] += 9 * 3600
    result(store)
    await service.tick()
    assert rows(store)[0]["state"] == "awaiting_registration" and calls == []
    register(service)
    await service.tick()
    assert len(calls) == 1


async def test_same_installation_accounts_cannot_read_disable_or_inherit_each_other(env):
    service, store, _, calls = env
    register(service)
    service.update_preferences("daily", PHONE, 0, True, 1320, 480, "Asia/Shanghai", owner_scope=A)
    result(store)
    service.collect()
    event = rows(store)[0]["event_key"]
    assert service.preferences("daily", PHONE, owner_scope=B)["revision"] == 0
    assert service.status("daily", PHONE, owner_scope=B)["counts"] == {}
    assert not service.status("daily", PHONE, owner_scope=B)["enabled"]
    with pytest.raises(NotificationError) as error:
        service.resolve("daily", event, owner_scope=B)
    assert error.value.status == 404
    service.disable_installation("daily", PHONE, owner_scope=B)
    assert service.status("daily", PHONE, owner_scope=A)["enabled"]
    register(service, B)
    assert rows(store)[0]["state"] == "cancelled"
    assert service.preferences("daily", PHONE, owner_scope=B)["enabled"] is False
    await service.tick()
    assert calls == []
    result(store)
    await service.tick()
    assert len(calls) == 1
    assert service.preferences("daily", PHONE, owner_scope=A)["revision"] == 1
    assert A not in str(service.status("daily", PHONE, owner_scope=A))
    assert B not in str(service.status("daily", PHONE, owner_scope=B))


async def test_revoke_is_durable_idempotent_and_fences_claims_and_late_receipts(env):
    service, store, _, calls = env
    register(service)
    result(store)
    service.collect()
    claim = service._claim()
    assert claim
    assert service.revoke_owner_scope(A) == {"disabled": 1, "pending_cancelled": 1}
    assert not service._delivery_authorized(claim)
    service._finish(claim, "ticket", ticket="late-provider-reply")
    assert rows(store)[0]["state"] == "cancelled"
    assert service.revoke_owner_scope(A) == {"disabled": 0, "pending_cancelled": 0}
    restarted = NotificationService(store, config=service.config, client=service.client, clock=service.clock)
    with pytest.raises(NotificationError) as error:
        register(restarted)
    assert error.value.status == 403
    register(service, B)
    service.revoke_owner_scope(A)
    assert service.status("daily", PHONE, owner_scope=B)["enabled"]
    assert calls == []


async def test_old_owner_receipt_cannot_disable_new_owner_with_same_device_token(env):
    service, store, _, _ = env
    register(service)
    result(store)
    service.collect()
    claim = service._claim()
    service._finish(claim, "ticket", ticket="old-ticket")
    old = rows(store)[0]
    register(service, B)
    service._finish(old, "failed", code="DeviceNotRegistered")
    assert service.status("daily", PHONE, owner_scope=B)["enabled"]
    result(store)
    service.collect()
    claim_b = service._claim()
    assert claim_b["generation"] > claim["generation"]
    assert claim_b["owner_scope"] == B


async def test_claimed_old_registration_is_fenced_before_network_handoff(env):
    service, store, _, calls = env
    register(service)
    result(store)
    service.collect()
    claim = service._claim()
    register(service, token="ExpoPushToken[rotatedSynthetic12345]")
    assert not service._delivery_authorized(claim)
    assert rows(store)[0]["state"] == "pending"
    await service.send_one()
    assert len(calls) == 1 and "rotatedSynthetic" in calls[0].content.decode()


def test_preference_compare_and_swap_has_one_concurrent_winner(tmp_path):
    store = Store(tmp_path / "cas.db")
    service = NotificationService(store, client=object())
    def save(end):
        try:
            return service.update_preferences("daily", PHONE, 0, True, 1320, end, "UTC", owner_scope=A)
        except NotificationError as error:
            return error.status
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(save, [420, 480]))
    assert outcomes.count(409) == 1
    winner = next(value for value in outcomes if isinstance(value, dict))
    assert service.preferences("daily", PHONE, owner_scope=A) == winner
    assert service.preferences("daily", PHONE, owner_scope=B)["revision"] == 0


async def test_cloud_http_scope_is_internal_and_required_for_every_notification_route(tmp_path):
    from wearing.app import create_app
    from wearing.config import Settings
    from wearing.cloud.worker import TenantBoundary
    app = create_app(Settings(tmp_path), engine_autostart=False)
    app.add_middleware(TenantBoundary, tenant_id="test-tenant", gateway_key="synthetic-internal")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        client.headers.update({"Authorization": "Bearer synthetic-internal", "X-Wearing-Tenant": "test-tenant"})
        csrf = (await client.get("/api/bootstrap")).json()["token"]
        client.headers["X-Wearing-Token"] = csrf
        params = {"installation_id": PHONE}
        assert (await client.get("/api/notifications/status", params=params)).status_code == 401
        assert (await client.get("/api/notifications/preferences", params=params)).status_code == 401
        assert (await client.post("/api/notifications/disable", json=params)).status_code == 401
        client.headers["X-Pajio-Storage-Scope"] = A
        body = dict(**params, revision=0, enabled=True, start_minute=1320, end_minute=480, timezone="Asia/Shanghai")
        assert (await client.post("/api/notifications/preferences", json=body)).json()["revision"] == 1
        assert (await client.post("/api/notifications/preferences", json={**body, "owner_scope": B})).status_code == 422
        client.headers["X-Pajio-Storage-Scope"] = B
        response = await client.get("/api/notifications/preferences", params={**params, "owner_scope": A})
        assert response.json()["revision"] == 0
        assert A not in response.text and B not in response.text
    await app.state.service.hermes.close()


async def test_cloud_service_cannot_fall_back_to_local_lease(env):
    service, _, _, _ = env
    with pytest.raises(NotificationError) as error:
        service.register("daily", PHONE, TOKEN, PROJECT, "ios", owner_scope=A)
    assert error.value.status == 401
    assert not service.status("daily", PHONE, owner_scope=A)["enabled"]
    assert service.register("daily", PHONE, TOKEN, PROJECT, "ios")["enabled"]


async def test_expiry_between_claim_and_handoff_waits_without_provider_call(env):
    service, store, now, calls = env
    register(service)
    result(store)
    service.collect()
    claim = service._claim()
    now[0] += 8 * 3600
    assert not service._delivery_authorized(claim)
    assert rows(store)[0]["state"] == "awaiting_registration" and calls == []
    register(service)
    await service.tick()
    assert len(calls) == 1


@pytest.mark.parametrize("cancel", ["disable", "logout", "owner_change", "revoke"])
async def test_optout_or_owner_change_while_provider_awaits_never_resurrects(env, cancel):
    service, store, _, calls = env
    register(service)
    result(store)
    entered, release = asyncio.Event(), asyncio.Event()

    async def slow_provider(request):
        calls.append(request)
        entered.set()
        await release.wait()
        return httpx.Response(200, json={"data": {"status": "ok", "id": "late-ticket"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(slow_provider)) as wire:
        original = service.client
        service.client = wire
        sending = asyncio.create_task(service.tick())
        await entered.wait()
        if cancel == "disable":
            service.disable("daily", PHONE, owner_scope=A)
        elif cancel == "logout":
            service.disable_installation("daily", PHONE, owner_scope=A)
        elif cancel == "owner_change":
            register(service, B)
        else:
            service.revoke_owner_scope(A)
        release.set()
        await sending
        service.client = original
    assert rows(store)[0]["state"] == "cancelled"
    assert rows(store)[0]["ticket_id"] is None
    if cancel != "revoke":
        register(service, B if cancel == "owner_change" else A)
    await service.tick()
    assert len(calls) == 1  # The original handoff cannot be recalled or replayed.


async def test_late_receipt_with_same_owner_and_same_token_cannot_revoke_new_generation(env):
    service, store, _, _ = env
    register(service)
    result(store)
    await service.tick()
    old_ticket = rows(store)[0]
    register(service)
    result(store)
    service.collect()
    service._finish(old_ticket, "failed", code="DeviceNotRegistered")
    assert service.status("daily", PHONE, owner_scope=A)["enabled"]
    assert rows(store)[1]["state"] == "pending"
    assert service._claim()["generation"] > old_ticket["generation"]


def test_legacy_unattributed_registration_and_quiet_policy_are_not_given_to_next_account(tmp_path):
    store = Store(tmp_path / "legacy.db")
    with store.connection() as db:
        db.executescript("""
          CREATE TABLE notification_devices (
            identity_id TEXT NOT NULL, installation_id TEXT NOT NULL, token TEXT NOT NULL,
            project_id TEXT NOT NULL, platform TEXT NOT NULL, enabled INTEGER NOT NULL,
            generation INTEGER NOT NULL, updated_at REAL NOT NULL, reason TEXT,
            PRIMARY KEY(identity_id,installation_id));
          CREATE TABLE notification_preferences (
            identity_id TEXT NOT NULL, installation_id TEXT NOT NULL, enabled INTEGER NOT NULL,
            start_minute INTEGER NOT NULL,end_minute INTEGER NOT NULL,timezone TEXT NOT NULL,
            revision INTEGER NOT NULL,PRIMARY KEY(identity_id,installation_id));
          CREATE TABLE notification_outbox (
            event_key TEXT NOT NULL,identity_id TEXT NOT NULL,installation_id TEXT NOT NULL,
            state TEXT NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,next_at REAL NOT NULL,
            claimed_at REAL,ticket_id TEXT,token TEXT,generation INTEGER,error_code TEXT,
            updated_at REAL NOT NULL,PRIMARY KEY(event_key,identity_id,installation_id));
        """)
        db.execute("INSERT INTO notification_devices VALUES(?,?,?,?,?,1,1,0,NULL)",
                   ("daily", PHONE, TOKEN, PROJECT, "ios"))
        db.execute("INSERT INTO notification_preferences VALUES(?,?,1,60,120,'UTC',7)", ("daily", PHONE))
        db.execute("""INSERT INTO notification_outbox(event_key,identity_id,installation_id,state,next_at,updated_at)
          VALUES('old-event','daily',?,'pending',0,0)""", (PHONE,))
    config = NotificationConfig(True, PROJECT)
    service = NotificationService(store, config=config, client=object(), clock=lambda: 1000)
    assert not service.status("daily", PHONE, owner_scope=A)["enabled"]
    assert service.preferences("daily", PHONE, owner_scope=A)["revision"] == 0
    assert rows(store)[0]["state"] == "cancelled"
    assert rows(store)[0]["error_code"] == "OwnerUnknown"
    register(service)
    restarted = NotificationService(store, config=config, client=object(), clock=lambda: 1000)
    assert restarted.status("daily", PHONE, owner_scope=A)["enabled"]
    assert restarted.preferences("daily", PHONE, owner_scope=A)["revision"] == 0
    assert rows(store)[0]["state"] == "cancelled"


async def test_local_http_ignores_public_owner_header_and_rejects_owner_in_body(tmp_path):
    from wearing.app import create_app
    from wearing.config import Settings
    app = create_app(Settings(tmp_path), engine_autostart=False)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        csrf = (await client.get("/api/bootstrap")).json()["token"]
        client.headers.update({"X-Wearing-Token": csrf, "X-Pajio-Storage-Scope": A})
        body = dict(installation_id=PHONE, revision=0, enabled=True,
                    start_minute=1320, end_minute=480, timezone="Asia/Shanghai")
        assert (await client.post("/api/notifications/preferences", json=body)).status_code == 200
        client.headers["X-Pajio-Storage-Scope"] = B
        assert (await client.get("/api/notifications/preferences", params={"installation_id": PHONE})).json()["revision"] == 1
        assert (await client.post("/api/notifications/preferences", json={**body, "owner_scope": B})).status_code == 422
        with app.state.store.connection() as db:
            assert [row[0] for row in db.execute("SELECT owner_scope FROM notification_preferences")] == ["local"]
    await app.state.service.hermes.close()
