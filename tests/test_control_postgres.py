"""Opt-in acceptance on a disposable real PostgreSQL cluster, never a user DB."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import secrets
import uuid

import httpx
import pytest
from sqlalchemy import create_engine, insert, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.engine import make_url

from wearing.cloud.control import (ControlError, ControlStore, OIDCStateCache, digest, members,
                                   routes, sessions, states, tenants, users)
from wearing.cloud.gateway import (GatewayConfig, GatewayError, create_gateway_app,
                                   initialize_gateway, operator_store, register_route)
from wearing.cloud.instance import initialize_instance
from wearing.cloud.postgres import DatabaseBoundaryError, REVISION, TABLES, migrate_database, validate_database_url
from wearing.cloud.worker import create_tenant_app


@pytest.fixture
def pg():
    path = os.environ.get("WEARING_POSTGRES_TEST_CONFIG")
    if not path:
        pytest.skip("requires an explicitly provisioned disposable PostgreSQL QA cluster")
    config = json.loads(Path(path).read_text())
    if not config.get("qa_only"):
        raise ValueError("PostgreSQL test configuration must mark its disposable cluster qa_only")
    suffix = uuid.uuid4().hex
    config.update(issuer=f"https://pg-{suffix}.example", a=f"tenant_{suffix}_A", b=f"tenant_{suffix}_B")
    operator = ControlStore(config["operator"], operator=True)
    web = ControlStore(config["app"])
    admin = create_engine(config["admin"], hide_parameters=True)
    operator.grant(config["issuer"], "alice", config["a"])
    operator.grant(config["issuer"], "bob", config["b"])
    for tenant in (config["a"], config["b"]):
        operator.bind(tenant, "instance_" + tenant, "https://worker.example", tenant + ".json")
    config.update(operator_store=operator, web=web, admin_engine=admin)
    try:
        yield config
    finally:
        operator.close()
        web.close()
        admin.dispose()


def test_migrations_are_repeatable_and_web_cannot_initialize(pg):
    migrate_database(pg["migration"])
    migrate_database(pg["migration"])
    with pytest.raises(ControlError):
        ControlStore(pg["app"], initialize=True)
    another = ControlStore(pg["app"])
    another.close()
    for key in ("app", "operator", "admin"):
        with pytest.raises(DatabaseBoundaryError):
            migrate_database(pg[key])


def test_initial_migration_is_transactional_and_refuses_unversioned_tables(pg):
    admin = pg["admin_engine"]
    for adopted in (False, True):
        name = "wearing_migrationtest_" + uuid.uuid4().hex
        owner = make_url(pg["migration"]).username
        quote = admin.dialect.identifier_preparer.quote
        with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as db:
            db.execute(text(f"CREATE DATABASE {quote(name)} OWNER {quote(owner)}"))
        url = make_url(pg["migration"]).set(database=name)
        target = create_engine(url, hide_parameters=True)
        try:
            if adopted:
                with target.begin() as db:
                    db.execute(text("CREATE SCHEMA wearing_control"))
                    db.execute(text("CREATE TABLE wearing_control.wearing_users (original text)"))
                    db.execute(text("INSERT INTO wearing_control.wearing_users VALUES ('preserve')"))
                with pytest.raises(RuntimeError, match="unversioned"):
                    migrate_database(url)
                with target.connect() as db:
                    assert db.scalar(text("SELECT original FROM wearing_control.wearing_users")) == "preserve"
                    assert db.scalar(text("SELECT to_regclass('wearing_control.alembic_version')")) is None
            else:
                migrate_database(url)
                web = ControlStore(make_url(pg["app"]).set(database=name))
                web.close()
        finally:
            target.dispose()
            with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as db:
                db.execute(text(f"DROP DATABASE {quote(name)}"))


def test_sql_without_filters_and_without_scope_cannot_read_other_rows(pg):
    web = pg["web"]
    sid = web.login(pg["issuer"], "alice")
    alice = web.session(sid)
    with web.transaction() as db:
        for table in (users, tenants, members, routes, sessions, states):
            assert db.execute(select(table)).all() == []
    with web.transaction(user_id=alice.user_id, tenant_id=pg["a"], session_hash=digest(sid)) as db:
        assert db.scalars(select(users.c.id)).all() == [alice.user_id]
        assert db.scalars(select(members.c.tenant_id)).all() == [pg["a"]]
        assert db.scalars(select(tenants.c.id)).all() == [pg["a"]]
        assert db.scalars(select(routes.c.tenant_id)).all() == [pg["a"]]
        assert db.scalars(select(sessions.c.id_hash)).all() == [digest(sid)]
    with web.transaction(user_id=alice.user_id, tenant_id=pg["b"]) as db:
        assert db.execute(select(routes)).all() == []
        assert db.execute(select(tenants)).all() == []


def test_session_restart_switch_revocation_and_expiry(pg):
    web, ops = pg["web"], pg["operator_store"]
    sid = web.login(pg["issuer"], "alice")
    with pytest.raises(ControlError):
        web.switch(sid, pg["b"])
    ops.grant(pg["issuer"], "alice", pg["b"])
    web.switch(sid, pg["b"])
    restarted = ControlStore(pg["app"])
    try:
        assert restarted.session(sid).tenant_id == pg["b"]
        ops.grant(pg["issuer"], "alice", pg["b"], active=False)
        assert restarted.session(sid) is None
        assert restarted.route(web.session(web.login(pg["issuer"], "bob")))["tenant_id"] == pg["b"]
        assert web.session(web.login(pg["issuer"], "alice", lifetime=-1)) is None
        web.logout(sid)
        assert restarted.session(sid) is None
    finally:
        restarted.close()


def test_pool_reuse_resets_all_context_even_after_session_set_and_rollback(pg):
    web = pg["web"]
    a = web.login(pg["issuer"], "alice")
    b = web.login(pg["issuer"], "bob")
    with web.engine.begin() as db:
        db.execute(text("SELECT set_config('wearing.user_id', :v, false)"), {"v": web.session(a).user_id})
        db.execute(text("SELECT set_config('wearing.session_hash', :v, false)"), {"v": digest(a)})
    for _ in range(4):
        assert web.session(b).tenant_id == pg["b"]
        assert web.session(secrets.token_urlsafe(48)) is None
        with web.transaction() as db:
            assert db.execute(select(users)).all() == []
        with pytest.raises(RuntimeError):
            with web.transaction(user_id=web.session(a).user_id) as db:
                assert len(db.execute(select(users)).all()) == 1
                raise RuntimeError("rollback")
        assert web.session(b).tenant_id == pg["b"]


@pytest.mark.parametrize("statement", [
    "UPDATE wearing_control.wearing_memberships SET active = false",
    "UPDATE wearing_control.wearing_routes SET upstream = 'https://foreign.example'",
    "UPDATE wearing_control.wearing_sessions SET expires = 2147483647",
    "UPDATE wearing_control.wearing_sessions SET user_id = 'foreign'",
    "UPDATE wearing_control.wearing_oidc_states SET value = 'foreign'",
    "TRUNCATE wearing_control.wearing_sessions",
    "CREATE TABLE wearing_control.forbidden (id text)",
])
def test_runtime_cannot_administer_members_routes_sessions_or_schema(pg, statement):
    with pytest.raises(DBAPIError):
        with pg["web"].transaction() as db:
            db.execute(text(statement))


def test_session_insert_is_bound_to_authorized_membership_and_hash(pg):
    web = pg["web"]
    alice = web.session(web.login(pg["issuer"], "alice"))
    sid = secrets.token_urlsafe(48)
    with pytest.raises(DBAPIError):
        with web.transaction(user_id=alice.user_id, session_hash=digest(sid)) as db:
            db.execute(insert(sessions).values(id_hash=digest(sid), user_id=alice.user_id,
                                               tenant_id=pg["b"], csrf="bad", expires=2147483647))
    with pytest.raises(DBAPIError):
        with web.transaction(user_id=alice.user_id, session_hash="wrong") as db:
            db.execute(insert(sessions).values(id_hash=digest(sid), user_id=alice.user_id,
                                               tenant_id=pg["a"], csrf="bad", expires=2147483647))
    with pytest.raises(DBAPIError):
        web.grant(pg["issuer"], "stranger", pg["a"])


def test_startup_rejects_super_owner_operator_and_extra_column_privilege(pg):
    for role in ("admin", "migration", "operator"):
        with pytest.raises(DatabaseBoundaryError):
            ControlStore(pg[role])
    admin = pg["admin_engine"]
    try:
        with admin.begin() as db:
            db.execute(text("GRANT UPDATE(expires) ON wearing_control.wearing_sessions TO wearing_web"))
        with pytest.raises(DatabaseBoundaryError):
            ControlStore(pg["app"])
    finally:
        with admin.begin() as db:
            db.execute(text("REVOKE UPDATE(expires) ON wearing_control.wearing_sessions FROM wearing_web"))
    good = ControlStore(pg["app"])
    good.close()


def test_startup_rejects_missing_force_rls_policy_and_revision(pg):
    mutations = [
        ("ALTER TABLE wearing_control.wearing_routes NO FORCE ROW LEVEL SECURITY", "ALTER TABLE wearing_control.wearing_routes FORCE ROW LEVEL SECURITY"),
        ("CREATE POLICY unsafe_extra ON wearing_control.wearing_routes TO wearing_web USING (true)", "DROP POLICY unsafe_extra ON wearing_control.wearing_routes"),
        ("UPDATE wearing_control.alembic_version SET version_num = 'wrong'", f"UPDATE wearing_control.alembic_version SET version_num = '{REVISION}'"),
    ]
    for change, repair in mutations:
        try:
            with pg["admin_engine"].begin() as db:
                db.execute(text(change))
            with pytest.raises(DatabaseBoundaryError):
                ControlStore(pg["app"])
        finally:
            with pg["admin_engine"].begin() as db:
                db.execute(text(repair))


def test_oidc_state_is_atomic_one_use_scoped_and_survives_new_store(pg):
    key = secrets.token_urlsafe(32)
    cache = OIDCStateCache(pg["web"])
    asyncio.run(cache.set(key, json.dumps({"data": {"nonce": "nonce"}}), 600))
    another = ControlStore(pg["app"])
    try:
        assert OIDCStateCache(another).nonce(key) == "nonce"
        with another.transaction(state_hash="foreign") as db:
            assert db.execute(select(states)).all() == []
        def consume(_):
            return asyncio.run(OIDCStateCache(another).get(key))
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(consume, range(4)))
        assert sum(result is not None for result in results) == 1
        assert cache.nonce(key) is None
    finally:
        another.close()


def test_operator_credential_is_separate_and_target_bound(pg, tmp_path, monkeypatch):
    config = initialize_gateway(tmp_path / "entry", "https://wearing.example", pg["issuer"], "test",
                                database_url=pg["app"], development=True)
    monkeypatch.delenv("WEARING_CONTROL_OPERATOR_DATABASE_URL", raising=False)
    with pytest.raises(GatewayError):
        operator_store(config)
    with pytest.raises(DatabaseBoundaryError):
        operator_store(config, database_url=pg["app"])
    with pytest.raises(DatabaseBoundaryError):
        operator_store(config, database_url=pg["admin"])
    with pytest.raises(GatewayError):
        operator_store(config, database_url=pg["operator"].replace("wearing_control_qa", "foreign"))
    ops = operator_store(config, database_url=pg["operator"])
    ops.close()
    content = (tmp_path / "entry/gateway.json").read_text()
    assert pg["operator"] not in content and pg["migration"] not in content


async def test_gateway_uses_real_pg_through_oidc_and_private_workers(pg, tmp_path, monkeypatch):
    monkeypatch.setenv("PAJIO_TRIAL_LIMITS", "1")
    from test_gateway import ORIGIN, ISSUER, Provider, Workers, login
    root, a, b = tmp_path / "entry", tmp_path / "A", tmp_path / "B"
    initialize_gateway(root, ORIGIN, ISSUER, "wearing-test", development=True, database_url=pg["app"])
    initialize_instance(a, pg["a"] + "_gateway", ORIGIN)
    initialize_instance(b, pg["b"] + "_gateway", ORIGIN)
    # Different OIDC subjects are local to this fixture, with provider signing checks reused.
    suffix = uuid.uuid4().hex
    alice_subject, bob_subject = "alice_" + suffix, "bob_" + suffix
    ops = pg["operator_store"]
    ops.grant(ISSUER, alice_subject, pg["a"] + "_gateway")
    ops.grant(ISSUER, bob_subject, pg["b"] + "_gateway")
    monkeypatch.setenv("WEARING_CONTROL_OPERATOR_DATABASE_URL", pg["operator"])
    register_route(root, a, "http://127.0.0.1:39001")
    register_route(root, b, "http://127.0.0.1:39002")
    wa, wb = create_tenant_app(a, engine_autostart=False), create_tenant_app(b, engine_autostart=False)
    workers, provider = Workers({39001: wa, 39002: wb}), Provider()
    app = create_gateway_app(root, oidc_transport=httpx.MockTransport(provider.handle), worker_transport=workers)
    async with wa.router.lifespan_context(wa), wb.router.lifespan_context(wb), app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as alice, httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as bob:
            assert (await login(alice, provider, alice_subject)).status_code == 303
            assert (await login(bob, provider, bob_subject)).status_code == 303
            token = (await alice.get("/api/bootstrap")).json()["token"]
            assert (await alice.post("/api/conversation", headers={"Origin": ORIGIN, "X-Wearing-Token": token}, json={"content": "PG Alice private idea"})).status_code == 201
            assert "PG Alice private idea" not in (await bob.get("/api/conversation")).text
            restarted = create_gateway_app(root, oidc_transport=httpx.MockTransport(provider.handle), worker_transport=workers)
            async with restarted.router.lifespan_context(restarted):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=restarted), base_url=ORIGIN, cookies=alice.cookies) as client:
                    assert "PG Alice private idea" in (await client.get("/api/conversation")).text
                    ops.grant(ISSUER, alice_subject, pg["a"] + "_gateway", active=False)
                    assert (await client.get("/api/conversation")).status_code == 401
            assert (await bob.get("/api/bootstrap")).status_code == 200


@pytest.mark.parametrize("value,development", [
    ("postgresql+psycopg://app@remote.example/db", False),
    ("postgresql+psycopg://app@remote.example/db?sslmode=require", False),
    ("postgresql+psycopg://app@remote.example/db?sslmode=verify-full", True),
    ("sqlite:///foreign.sqlite3", False),
    ("postgresql+psycopg://app@127.0.0.1/db?host=remote.example", True),
    ("postgresql+psycopg://app/db?host=/private/socket&hostaddr=1.2.3.4", False),
    ("postgresql+psycopg://app/db?host=/private/socket,remote.example", False),
    ("postgresql+psycopg://app@127.0.0.1/db?service=remote", True),
])
def test_pg_connection_boundary_requires_local_lab_or_verified_tls(value, development):
    with pytest.raises(DatabaseBoundaryError):
        validate_database_url(value, development=development)


def test_production_config_requires_https_and_verified_postgres():
    with pytest.raises(ValueError):
        GatewayConfig(public_origin="https://wearing.example", issuer="https://id.example", client_id="test",
                      session_key="x" * 32, database_url="postgresql+psycopg://app@db.example/db")
    GatewayConfig(public_origin="https://wearing.example", issuer="https://id.example", client_id="test",
                  session_key="x" * 32, database_url="postgresql+psycopg://app@db.example/db?sslmode=verify-full")
