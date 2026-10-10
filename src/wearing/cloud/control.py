"""Platform metadata only; never store tenant messages, model keys or OIDC tokens."""

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import secrets
import time
import uuid

from sqlalchemy import (Boolean, CheckConstraint, Column, ForeignKey, ForeignKeyConstraint, Integer, MetaData, String, Table,
                        Text, UniqueConstraint, create_engine, delete, event, insert, select, text, update)


class ControlError(ValueError):
    pass


metadata = MetaData()
users = Table("wearing_users", metadata,
              Column("id", String(128), primary_key=True),
              Column("issuer", Text, nullable=False), Column("subject", String(512), nullable=False),
              Column("deletion_state", String(16), nullable=False, server_default="active"),
              CheckConstraint("deletion_state IN ('active','frozen')"),
              UniqueConstraint("issuer", "subject"))
tenants = Table("wearing_tenants", metadata, Column("id", String(128), primary_key=True),
                Column("deletion_state", String(16), nullable=False, server_default="active"),
                CheckConstraint("deletion_state IN ('active','frozen')"))
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
                 Column("auth_time", Integer),
                 ForeignKeyConstraint(["user_id", "tenant_id"], ["wearing_memberships.user_id", "wearing_memberships.tenant_id"]))
states = Table("wearing_oidc_states", metadata,
               Column("id_hash", String(64), primary_key=True),
               Column("value", Text, nullable=False), Column("expires", Integer, nullable=False))
ownership = Table("wearing_tenant_ownership", metadata,
                  Column("tenant_id", ForeignKey("wearing_tenants.id"), primary_key=True),
                  Column("classification", String(16), nullable=False),
                  Column("owner_user_id", ForeignKey("wearing_users.id")),
                  Column("member_count", Integer, nullable=False), Column("member_digest", String(64), nullable=False),
                  Column("instance_id", String(128)), Column("revision", Integer, nullable=False),
                  CheckConstraint("classification IN ('private','shared','unknown')"),
                  CheckConstraint("member_count > 0 AND revision > 0"))
deletion_requests = Table("wearing_deletion_requests", metadata,
                  Column("id", String(32), primary_key=True), Column("user_id", ForeignKey("wearing_users.id"), nullable=False, unique=True),
                  Column("request_key", String(120), nullable=False), Column("plan_revision", String(64), nullable=False),
                  Column("plan_json", Text, nullable=False), Column("created_at", Integer, nullable=False),
                  Column("state", String(32), nullable=False, server_default="awaiting_operator"),
                  Column("code", String(64), nullable=False, server_default="adapter_unconfigured"),
                  Column("updated_at", Integer),
                  CheckConstraint("state IN ('awaiting_operator','frozen','waiting','completed')"),
                  UniqueConstraint("user_id", "request_key"))
bundles = Table("wearing_bundles", metadata,
                Column("id", String(32), primary_key=True),
                Column("tenant_id", ForeignKey("wearing_tenants.id"), nullable=False, unique=True),
                Column("instance_id", String(128), nullable=False), Column("host", String(128), nullable=False),
                Column("reservation_sha256", String(64), nullable=False),
                Column("worker_plan_sha256", String(64), nullable=False), Column("members_json", Text, nullable=False),
                Column("reservation_expires_at", Integer, nullable=False), Column("created_at", Integer, nullable=False),
                CheckConstraint("reservation_expires_at > created_at"))
invitations = Table("wearing_invitations", metadata,
                  Column("id", String(32), primary_key=True), Column("code_hash", String(64), nullable=False, unique=True),
                  Column("issuer", Text, nullable=False), Column("tenant_id", ForeignKey("wearing_tenants.id"), nullable=False, unique=True),
                  Column("instance_id", String(128), nullable=False), Column("created_at", Integer, nullable=False),
                  Column("expires_at", Integer, nullable=False), Column("revoked_at", Integer),
                  Column("redeemed_user_id", ForeignKey("wearing_users.id")), Column("redeemed_at", Integer),
                  Column("registration_id", String(32), unique=True), Column("username_hash", String(64)),
                  Column("registration_subject", String(512)),
                  Column("bundle_id", ForeignKey("wearing_bundles.id"), unique=True),
                  CheckConstraint("expires_at > created_at"),
                  CheckConstraint("(redeemed_user_id IS NULL) = (redeemed_at IS NULL)"),
                  CheckConstraint("(registration_id IS NULL) = (username_hash IS NULL)"),
                  CheckConstraint("registration_subject IS NULL OR registration_id IS NOT NULL"))


bundle_activations = Table("wearing_bundle_activations", metadata,
                Column("id", String(32), primary_key=True),
                Column("invitation_id", ForeignKey("wearing_invitations.id"), nullable=False, unique=True),
                Column("bundle_id", ForeignKey("wearing_bundles.id"), nullable=False, unique=True),
                Column("user_id", ForeignKey("wearing_users.id"), nullable=False),
                Column("tenant_id", ForeignKey("wearing_tenants.id"), nullable=False),
                Column("instance_id", String(128), nullable=False),
                Column("ownership_revision", Integer, nullable=False), Column("member_digest", String(64), nullable=False),
                Column("state", String(32), nullable=False, server_default="reserved"),
                Column("members_json", Text, nullable=False), Column("step", String(80), nullable=False, server_default="planned"),
                Column("receipt_sha256", String(64)), Column("reason", String(80)),
                Column("generation", Integer, nullable=False, server_default="0"), Column("lease_owner", String(32)),
                Column("lease_until", Integer), Column("created_at", Integer, nullable=False), Column("updated_at", Integer, nullable=False),
                CheckConstraint("ownership_revision > 0 AND generation >= 0"),
                CheckConstraint("state IN ('reserved','preparing','installing','pairing','ready','needs_review')"),
                CheckConstraint("(lease_owner IS NULL) = (lease_until IS NULL)"))


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SessionView:
    user_id: str
    tenant_id: str
    csrf: str
    expires: int
    auth_time: int | None = None


class ControlStore:
    def __init__(self, url: str, *, initialize=False, operator=False, registration=False, activation=False):
        if sum(bool(v) for v in (operator, registration, activation)) > 1:
            raise ControlError("数据库角色不能同时用于运营、注册或分配。")
        self.operator = operator
        self.registration = registration
        self.activation = activation
        self.engine = create_engine(url, hide_parameters=True)
        self.postgres = self.engine.dialect.name == "postgresql"
        if self.postgres:
            from .postgres import SCHEMA, assert_database_boundary
            if initialize:
                self.engine.dispose()
                raise ControlError("PostgreSQL 需要版本化迁移，不能用 create_all 初始化。")
            self.engine = self.engine.execution_options(schema_translate_map={None: SCHEMA})
            try:
                assert_database_boundary(self.engine, operator=operator, registration=registration, activation=activation)
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
    def transaction(self, *, mutating=False, **scope):
        with self.engine.begin() as db:
            if self.postgres:
                from .postgres import scoped
                scoped(db, **scope)
                if mutating:
                    # Shared by enrollment, auth mutation and deletion admission.
                    # One short metadata lock gives deterministic freeze ordering.
                    db.execute(text("SELECT pg_catalog.pg_advisory_xact_lock(8247991102)"))
            elif mutating:
                db.exec_driver_sql("BEGIN IMMEDIATE")
            yield db

    def user_available(self, db, user_id):
        return bool(db.scalar(select(users.c.id).where(users.c.id == user_id, users.c.deletion_state == "active"))) and not db.scalar(select(deletion_requests.c.id).where(deletion_requests.c.user_id == user_id))

    def tenant_available(self, db, tenant_id):
        if not db.scalar(select(tenants.c.id).where(tenants.c.id == tenant_id, tenants.c.deletion_state == "active")):
            return False
        # Operator sees all pending plans. A private-space request fences enrollment
        # before the operator has reached its freeze step; shared spaces stay usable.
        return not any(any(t["tenant_id"] == tenant_id and t["action"] == "erase_private" for t in json.loads(raw)["tenants"])
                       for raw in db.scalars(select(deletion_requests.c.plan_json)))

    def tenant_editable(self, db, tenant_id):
        if not self.tenant_available(db, tenant_id):
            return False
        # Keep accepted shared-space ownership snapshots stable until freeze has
        # removed only this member. Ordinary shared-space work remains available.
        return not any(any(t["tenant_id"] == tenant_id for t in json.loads(raw)["tenants"])
                       for raw in db.scalars(select(deletion_requests.c.plan_json).where(deletion_requests.c.state == "awaiting_operator")))

    def refresh_ownership(self, db, tenant_id):
        row = db.execute(select(ownership).where(ownership.c.tenant_id == tenant_id)).mappings().first()
        if row:
            people = sorted((r.user_id, r.active) for r in db.execute(select(members).where(members.c.tenant_id == tenant_id)))
            fingerprint = digest(json.dumps(people, separators=(",", ":")))
            instance = db.scalar(select(routes.c.instance_id).where(routes.c.tenant_id == tenant_id))
            if fingerprint != row["member_digest"] or instance != row["instance_id"]:
                db.execute(update(ownership).where(ownership.c.tenant_id == tenant_id).values(member_count=len(people), member_digest=fingerprint, instance_id=instance, revision=row["revision"]+1))

    def set_user(self, db, user_id):
        if self.postgres:
            from .postgres import set_user
            set_user(db, user_id)

    def set_session(self, db, session_hash):
        if self.postgres:
            from .postgres import set_session
            set_session(db, session_hash)

    def set_tenant(self, db, tenant_id):
        if self.postgres:
            db.execute(text("SELECT pg_catalog.set_config('wearing.tenant_id', :value, true)"), {"value": tenant_id})

    def grant(self, issuer, subject, tenant_id, *, active=True):
        """Operator enrollment; not callable by the public application."""
        if not subject or len(subject) > 512:
            raise ControlError("登录主体格式不正确。")
        with self.transaction(mutating=True) as db:
            user_id = db.scalar(select(users.c.id).where(users.c.issuer == issuer, users.c.subject == subject))
            if user_id is None:
                user_id = "user_" + uuid.uuid4().hex
                db.execute(insert(users).values(id=user_id, issuer=issuer, subject=subject))
            elif not self.user_available(db, user_id):
                raise ControlError("账户注销处理中，不能修改成员关系。")
            if db.scalar(select(tenants.c.id).where(tenants.c.id == tenant_id)) is None:
                db.execute(insert(tenants).values(id=tenant_id))
            elif not self.tenant_editable(db, tenant_id):
                raise ControlError("空间注销处理中，不能修改成员关系。")
            current = db.execute(select(members).where(members.c.user_id == user_id, members.c.tenant_id == tenant_id)).first()
            if current is None:
                db.execute(insert(members).values(user_id=user_id, tenant_id=tenant_id, active=active))
            else:
                db.execute(update(members).where(members.c.user_id == user_id, members.c.tenant_id == tenant_id).values(active=active))
            self.refresh_ownership(db, tenant_id)

    def bind(self, tenant_id, instance_id, upstream, credential_ref):
        with self.transaction(mutating=True) as db:
            if db.scalar(select(tenants.c.id).where(tenants.c.id == tenant_id)) is None:
                raise ControlError("请先登记该租户的会员关系。")
            if not self.tenant_editable(db, tenant_id):
                raise ControlError("空间注销处理中，不能绑定路由。")
            desired = dict(tenant_id=tenant_id, instance_id=instance_id, upstream=upstream, credential_ref=credential_ref)
            current = db.execute(select(routes).where(routes.c.tenant_id == tenant_id)).mappings().first()
            if current:
                if dict(current) != desired:
                    raise ControlError("已有实例路由不能重新绑定；迁移需要独立核对。")
            else:
                db.execute(insert(routes).values(**desired))
            self.refresh_ownership(db, tenant_id)

    def login(self, issuer, subject, *, lifetime=28800, auth_time=None):
        if auth_time is not None and (type(auth_time) is not int or auth_time < 0 or auth_time > int(time.time()) + 30):
            raise ControlError("登录验证时间无效。")
        with self.transaction(mutating=True, issuer=issuer, subject=subject) as db:
            user_id = db.scalar(select(users.c.id).where(users.c.issuer == issuer, users.c.subject == subject))
            if user_id:
                self.set_user(db, user_id)
            if not user_id or not self.user_available(db, user_id):
                raise ControlError("此账号尚未加入 Pajio 试用。")
            tenant_id = None
            for candidate in db.scalars(select(members.c.tenant_id).where(members.c.user_id == user_id, members.c.active.is_(True)).order_by(members.c.tenant_id)):
                self.set_tenant(db, candidate)
                if self.tenant_available(db, candidate):
                    tenant_id = candidate
                    break
            if tenant_id is None:
                raise ControlError("此账号尚未加入可用的 Pajio 空间。")
            sid, csrf = secrets.token_urlsafe(48), secrets.token_urlsafe(32)
            self.set_session(db, digest(sid))
            if not self.postgres:
                db.execute(delete(sessions).where(sessions.c.expires <= int(time.time())))
            db.execute(insert(sessions).values(id_hash=digest(sid), user_id=user_id, tenant_id=tenant_id,
                                               csrf=csrf, expires=int(time.time()) + lifetime, auth_time=auth_time))
        return sid

    def session(self, sid):
        if not isinstance(sid, str) or len(sid) != 64:
            return None
        with self.transaction(session_hash=digest(sid)) as db:
            row = db.execute(select(sessions).where(sessions.c.id_hash == digest(sid), sessions.c.expires > int(time.time()))).mappings().first()
            if row:
                self.set_user(db, row["user_id"])
                self.set_tenant(db, row["tenant_id"])
                active = db.scalar(select(members.c.active).where(members.c.user_id == row["user_id"], members.c.tenant_id == row["tenant_id"]))
                if not active or not self.user_available(db, row["user_id"]):
                    row = None
                elif db.scalar(select(tenants.c.deletion_state).where(tenants.c.id == row["tenant_id"])) == "frozen":
                    row = None
        return SessionView(row["user_id"], row["tenant_id"], row["csrf"], row["expires"], row["auth_time"]) if row else None

    def memberships(self, session):
        with self.transaction(user_id=session.user_id) as db:
            if not self.user_available(db, session.user_id):
                return []
            result = []
            for tenant_id in db.scalars(select(members.c.tenant_id).where(members.c.user_id == session.user_id, members.c.active.is_(True)).order_by(members.c.tenant_id)):
                self.set_tenant(db, tenant_id)
                if self.tenant_available(db, tenant_id): result.append(tenant_id)
            return result

    def switch(self, sid, tenant_id):
        current = self.session(sid)
        if current is None:
            raise ControlError("登录已失效。")
        with self.transaction(mutating=True, user_id=current.user_id, tenant_id=tenant_id, session_hash=digest(sid)) as db:
            allowed = db.scalar(select(members.c.tenant_id).where(members.c.user_id == current.user_id, members.c.tenant_id == tenant_id, members.c.active.is_(True)))
            if not allowed or not self.user_available(db, current.user_id) or not self.tenant_available(db, tenant_id):
                raise ControlError("此账号不能进入该 Pajio。")
            db.execute(update(sessions).where(sessions.c.id_hash == digest(sid)).values(tenant_id=tenant_id))

    def logout(self, sid):
        if isinstance(sid, str):
            with self.transaction(session_hash=digest(sid)) as db:
                db.execute(delete(sessions).where(sessions.c.id_hash == digest(sid)))

    def route(self, session):
        # Recheck current membership at dispatch; no browser-supplied route or tenant.
        with self.transaction(mutating=True, user_id=session.user_id, tenant_id=session.tenant_id) as db:
            if not self.user_available(db, session.user_id) or not self.tenant_available(db, session.tenant_id):
                return None
            row = db.execute(select(routes).join(members, routes.c.tenant_id == members.c.tenant_id)
                             .where(members.c.user_id == session.user_id, members.c.active.is_(True),
                                    routes.c.tenant_id == session.tenant_id)).mappings().first()
        return dict(row) if row else None

    def private_owner_scope(self, session, expected_route):
        """Validate operator-owned personal space, including under membership RLS.

        Registry count/digest is the operator's full membership snapshot. A web
        role only sees its own membership and MUST NOT count those visible rows.
        Missing/shared/unknown registry retains legacy routing, without granting
        personal-device files. A declared private space always fails closed.
        """
        with self.transaction(user_id=session.user_id, tenant_id=session.tenant_id) as db:
            row = db.execute(select(ownership).where(ownership.c.tenant_id == session.tenant_id)).mappings().first()
            route = db.execute(select(routes).where(routes.c.tenant_id == session.tenant_id)).mappings().first()
            if not route or dict(route) != expected_route:
                raise ControlError('个人空间路由已变更。')
            if not row or row['classification'] != 'private':
                return None
            expected = digest(json.dumps([(session.user_id, True)], separators=(',', ':')))
            if (not self.user_available(db, session.user_id) or not self.tenant_available(db, session.tenant_id)
                    or row['owner_user_id'] != session.user_id or row['member_count'] != 1
                    or row['member_digest'] != expected or row['instance_id'] != route['instance_id']
                    or not db.scalar(select(members.c.tenant_id).where(members.c.tenant_id == session.tenant_id,
                          members.c.user_id == session.user_id, members.c.active.is_(True)))):
                raise ControlError('个人空间归属未通过验证。')
            from .mobile_auth import session_storage_scope
            return session_storage_scope(session.user_id, session.tenant_id)


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
