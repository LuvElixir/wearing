"""Platform metadata only; never store tenant messages, model keys or OIDC tokens."""

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import secrets
import time
import uuid

from sqlalchemy import (Boolean, Column, ForeignKey, ForeignKeyConstraint, Integer, MetaData, String, Table,
                        Text, UniqueConstraint, create_engine, delete, event, insert, select, update)


class ControlError(ValueError):
    pass


metadata = MetaData()
users = Table("wearing_users", metadata,
              Column("id", String(128), primary_key=True),
              Column("issuer", Text, nullable=False), Column("subject", String(512), nullable=False),
              UniqueConstraint("issuer", "subject"))
tenants = Table("wearing_tenants", metadata, Column("id", String(128), primary_key=True))
members = Table("wearing_memberships", metadata,
                Column("user_id", ForeignKey("wearing_users.id"), primary_key=True),
                Column("tenant_id", ForeignKey("wearing_tenants.id"), primary_key=True),
                Column("active", Boolean, nullable=False))
routes = Table("wearing_routes", metadata,
               Column("tenant_id", ForeignKey("wearing_tenants.id"), primary_key=True),
               Column("instance_id", String(128), nullable=False, unique=True),
               Column("upstream", Text, nullable=False), Column("credential_ref", String(128), nullable=False))
sessions = Table("wearing_sessions", metadata,
                 Column("id_hash", String(64), primary_key=True),
                 Column("user_id", String(128), nullable=False),
                 Column("tenant_id", String(128), nullable=False),
                 Column("csrf", String(64), nullable=False), Column("expires", Integer, nullable=False),
                 ForeignKeyConstraint(["user_id", "tenant_id"], ["wearing_memberships.user_id", "wearing_memberships.tenant_id"]))
states = Table("wearing_oidc_states", metadata,
               Column("id_hash", String(64), primary_key=True),
               Column("value", Text, nullable=False), Column("expires", Integer, nullable=False))


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SessionView:
    user_id: str
    tenant_id: str
    csrf: str


class ControlStore:
    def __init__(self, url: str, *, initialize=False, operator=False):
        self.engine = create_engine(url, hide_parameters=True)
        self.postgres = self.engine.dialect.name == "postgresql"
        if self.postgres:
            from .postgres import SCHEMA, assert_database_boundary
            if initialize:
                self.engine.dispose()
                raise ControlError("PostgreSQL 需要版本化迁移，不能用 create_all 初始化。")
            self.engine = self.engine.execution_options(schema_translate_map={None: SCHEMA})
            try:
                assert_database_boundary(self.engine, operator=operator)
            except Exception:
                self.engine.dispose()
                raise
        if self.engine.dialect.name == "sqlite":
            @event.listens_for(self.engine, "connect")
            def enable_foreign_keys(connection, record):
                connection.execute("PRAGMA foreign_keys=ON")
        if initialize:
            metadata.create_all(self.engine)

    def close(self):
        self.engine.dispose()

    @contextmanager
    def transaction(self, **scope):
        with self.engine.begin() as db:
            if self.postgres:
                from .postgres import scoped
                scoped(db, **scope)
            yield db

    def set_user(self, db, user_id):
        if self.postgres:
            from .postgres import set_user
            set_user(db, user_id)

    def set_session(self, db, session_hash):
        if self.postgres:
            from .postgres import set_session
            set_session(db, session_hash)

    def grant(self, issuer, subject, tenant_id, *, active=True):
        """Operator enrollment; not callable by the public application."""
        if not subject or len(subject) > 512:
            raise ControlError("登录主体格式不正确。")
        with self.transaction() as db:
            user_id = db.scalar(select(users.c.id).where(users.c.issuer == issuer, users.c.subject == subject))
            if user_id is None:
                user_id = "user_" + uuid.uuid4().hex
                db.execute(insert(users).values(id=user_id, issuer=issuer, subject=subject))
            if db.scalar(select(tenants.c.id).where(tenants.c.id == tenant_id)) is None:
                db.execute(insert(tenants).values(id=tenant_id))
            current = db.execute(select(members).where(members.c.user_id == user_id, members.c.tenant_id == tenant_id)).first()
            if current is None:
                db.execute(insert(members).values(user_id=user_id, tenant_id=tenant_id, active=active))
            else:
                db.execute(update(members).where(members.c.user_id == user_id, members.c.tenant_id == tenant_id).values(active=active))

    def bind(self, tenant_id, instance_id, upstream, credential_ref):
        with self.transaction() as db:
            if db.scalar(select(tenants.c.id).where(tenants.c.id == tenant_id)) is None:
                raise ControlError("请先登记该租户的会员关系。")
            desired = dict(tenant_id=tenant_id, instance_id=instance_id, upstream=upstream, credential_ref=credential_ref)
            current = db.execute(select(routes).where(routes.c.tenant_id == tenant_id)).mappings().first()
            if current:
                if dict(current) != desired:
                    raise ControlError("已有实例路由不能重新绑定；迁移需要独立核对。")
            else:
                db.execute(insert(routes).values(**desired))

    def login(self, issuer, subject, *, lifetime=28800):
        with self.transaction(issuer=issuer, subject=subject) as db:
            user_id = db.scalar(select(users.c.id).where(users.c.issuer == issuer, users.c.subject == subject))
            if user_id:
                self.set_user(db, user_id)
            tenant_id = db.scalar(select(members.c.tenant_id).where(members.c.user_id == user_id, members.c.active.is_(True)).order_by(members.c.tenant_id))
            if not user_id or not tenant_id:
                raise ControlError("此账号尚未加入 Wearing 试用。")
            sid, csrf = secrets.token_urlsafe(48), secrets.token_urlsafe(32)
            self.set_session(db, digest(sid))
            if not self.postgres:
                db.execute(delete(sessions).where(sessions.c.expires <= int(time.time())))
            db.execute(insert(sessions).values(id_hash=digest(sid), user_id=user_id, tenant_id=tenant_id,
                                               csrf=csrf, expires=int(time.time()) + lifetime))
        return sid

    def session(self, sid):
        if not isinstance(sid, str) or len(sid) != 64:
            return None
        with self.transaction(session_hash=digest(sid)) as db:
            row = db.execute(select(sessions).where(sessions.c.id_hash == digest(sid), sessions.c.expires > int(time.time()))).mappings().first()
            if row:
                self.set_user(db, row["user_id"])
                active = db.scalar(select(members.c.active).where(members.c.user_id == row["user_id"], members.c.tenant_id == row["tenant_id"]))
                if not active:
                    row = None
        return SessionView(row["user_id"], row["tenant_id"], row["csrf"]) if row else None

    def memberships(self, session):
        with self.transaction(user_id=session.user_id) as db:
            return list(db.scalars(select(members.c.tenant_id).where(members.c.user_id == session.user_id, members.c.active.is_(True)).order_by(members.c.tenant_id)))

    def switch(self, sid, tenant_id):
        current = self.session(sid)
        if current is None:
            raise ControlError("登录已失效。")
        with self.transaction(user_id=current.user_id, tenant_id=tenant_id, session_hash=digest(sid)) as db:
            allowed = db.scalar(select(members.c.tenant_id).where(members.c.user_id == current.user_id, members.c.tenant_id == tenant_id, members.c.active.is_(True)))
            if not allowed:
                raise ControlError("此账号不能进入该 Wearing。")
            db.execute(update(sessions).where(sessions.c.id_hash == digest(sid)).values(tenant_id=tenant_id))

    def logout(self, sid):
        if isinstance(sid, str):
            with self.transaction(session_hash=digest(sid)) as db:
                db.execute(delete(sessions).where(sessions.c.id_hash == digest(sid)))

    def route(self, session):
        # Recheck current membership at dispatch; no browser-supplied route or tenant.
        with self.transaction(user_id=session.user_id, tenant_id=session.tenant_id) as db:
            row = db.execute(select(routes).join(members, routes.c.tenant_id == members.c.tenant_id)
                             .where(members.c.user_id == session.user_id, members.c.active.is_(True),
                                    routes.c.tenant_id == session.tenant_id)).mappings().first()
        return dict(row) if row else None


class OIDCStateCache:
    """Authlib async cache: private, expiring, one-use state across gateway restarts."""
    def __init__(self, store):
        self.store = store

    async def set(self, key, value, expires):
        with self.store.transaction(state_hash=digest(key)) as db:
            if not self.store.postgres:
                db.execute(delete(states).where(states.c.expires <= int(time.time())))
            db.execute(insert(states).values(id_hash=digest(key), value=value, expires=int(time.time()) + min(expires, 600)))

    async def get(self, key):
        with self.store.transaction(state_hash=digest(key)) as db:
            row = db.execute(delete(states).where(states.c.id_hash == digest(key), states.c.expires > int(time.time())).returning(states.c.value)).first()
        return row[0] if row else None

    async def delete(self, key):
        with self.store.transaction(state_hash=digest(key)) as db:
            db.execute(delete(states).where(states.c.id_hash == digest(key)))

    def nonce(self, key):
        with self.store.transaction(state_hash=digest(key)) as db:
            value = db.scalar(select(states.c.value).where(states.c.id_hash == digest(key), states.c.expires > int(time.time())))
        return json.loads(value)["data"].get("nonce") if value else None
