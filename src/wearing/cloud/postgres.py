"""PostgreSQL control-plane migrations and transaction scopes, not tenant storage."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


SCHEMA = "wearing_control"
REVISION = "wearing_control_0002"
WEB_ROLE = "wearing_web"
OPERATOR_ROLE = "wearing_operator"
TABLES = ("wearing_users", "wearing_tenants", "wearing_memberships", "wearing_routes", "wearing_sessions", "wearing_oidc_states", "wearing_tenant_ownership", "wearing_deletion_requests")
CONTEXT_KEYS = ("user_id", "tenant_id", "session_hash", "issuer", "subject", "state_hash")


class DatabaseBoundaryError(ValueError):
    pass


def validate_database_url(value, *, development):
    url = make_url(value)
    if url.drivername != "postgresql+psycopg" or not url.database or not url.username:
        raise DatabaseBoundaryError("需要 PostgreSQL/Psycopg 的独立数据库与登录角色。")
    # SQLAlchemy query parameters override URI host. libpq service/hostaddr can
    # redirect elsewhere, so do not mistake a displayed loopback URI for local.
    host = url.query.get("host", url.host)
    if (not isinstance(host, str) or not host or "," in host
            or any(key in url.query for key in ("hostaddr", "service", "servicefile"))):
        raise DatabaseBoundaryError("平台数据库需要显式单一主机或本机 socket，不能使用连接重定向。")
    socket = host.startswith("/")
    local = host in {"localhost", "127.0.0.1", "::1"} or socket
    if development and not local:
        raise DatabaseBoundaryError("开发 PostgreSQL 仅允许本机回环地址或 Unix socket。")
    if not development and not socket and url.query.get("sslmode") != "verify-full":
        raise DatabaseBoundaryError("网络 PostgreSQL 连接需要 sslmode=verify-full。")


def scoped(db, **values):
    # Every transaction sets every key, including empty keys. Pool reuse cannot
    # inherit another user's authority, even if the connection had session SETs.
    for name in CONTEXT_KEYS:
        db.execute(text("SELECT pg_catalog.set_config(:name, :value, true)"),
                   {"name": "wearing." + name, "value": values.get(name, "")})
    db.execute(text("SELECT pg_catalog.set_config('row_security', 'on', true)"))


def set_user(db, user_id):
    db.execute(text("SELECT pg_catalog.set_config('wearing.user_id', :value, true)"), {"value": user_id})


def set_session(db, session_hash):
    db.execute(text("SELECT pg_catalog.set_config('wearing.session_hash', :value, true)"), {"value": session_hash})


def assert_database_boundary(engine, *, operator=False):
    with engine.connect() as db:
        version = db.execute(text("SELECT version_num FROM wearing_control.alembic_version")).scalars().all()
        if version != [REVISION]:
            raise DatabaseBoundaryError("平台数据库版本不匹配；请通过操作者迁移入口升级。")
        role = db.execute(text("""
            SELECT r.rolsuper, r.rolbypassrls, r.rolcreaterole, r.rolcreatedb,
                   pg_catalog.pg_has_role(current_user, 'wearing_web', 'MEMBER') AS web,
                   pg_catalog.pg_has_role(current_user, 'wearing_operator', 'MEMBER') AS operator
            FROM pg_catalog.pg_roles r WHERE r.rolname = current_user
        """)).mappings().one()
        if operator:
            if not role["operator"] or role["web"] or any(role[k] for k in ("rolsuper", "rolbypassrls", "rolcreaterole", "rolcreatedb")):
                raise DatabaseBoundaryError("登记和撤销需要单独的操作者角色。")
        elif (any(role[k] for k in ("rolsuper", "rolbypassrls", "rolcreaterole", "rolcreatedb", "operator")) or not role["web"]):
            raise DatabaseBoundaryError("网页数据库角色具有管理权限，或缺少应用角色授权。")
        if db.scalar(text("""
            SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_roles r
              WHERE (r.rolsuper OR r.rolbypassrls OR r.rolcreaterole OR r.rolcreatedb)
                AND pg_catalog.pg_has_role(current_user, r.oid, 'MEMBER'))
        """)):
            raise DatabaseBoundaryError("网页数据库角色不能切换到管理角色。")
        rows = db.execute(text("""
            SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity,
                   pg_catalog.pg_has_role(current_user, c.relowner, 'MEMBER') AS owns
            FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'wearing_control' AND c.relkind = 'r'
        """)).mappings().all()
        selected = {r["relname"]: r for r in rows}
        if any(name not in selected or not selected[name]["relrowsecurity"] or not selected[name]["relforcerowsecurity"] or selected[name]["owns"] for name in TABLES):
            raise DatabaseBoundaryError("平台数据表的所有权或 FORCE RLS 校验未通过。")
        if db.scalar(text("SELECT pg_catalog.has_schema_privilege(current_user, 'wearing_control', 'CREATE')")):
            raise DatabaseBoundaryError("网页数据库角色不能创建平台对象。")
        if operator:
            return
        for table in TABLES:
            name = SCHEMA + "." + table
            if not db.scalar(text("SELECT pg_catalog.has_table_privilege(current_user, :table, 'SELECT')"), {"table": name}):
                raise DatabaseBoundaryError("网页数据库角色缺少元数据读取权限。")
            for privilege in ("TRUNCATE", "REFERENCES", "TRIGGER"):
                if db.scalar(text("SELECT pg_catalog.has_table_privilege(current_user, :table, :privilege)"), {"table": SCHEMA + "." + table, "privilege": privilege}):
                    raise DatabaseBoundaryError("网页数据库角色存在额外的表级权限。")
            if table == "wearing_deletion_requests":
                for privilege in ("INSERT", "UPDATE", "DELETE"):
                    if db.scalar(text("SELECT pg_catalog.has_table_privilege(current_user, :table, :privilege)"), {"table": name, "privilege": privilege}):
                        raise DatabaseBoundaryError("注销请求只能写入指定的申请字段。")
                allowed_insert = {"id", "user_id", "request_key", "plan_revision", "plan_json", "created_at"}
                columns = allowed_insert | {"state", "code", "updated_at"}
                for column in columns:
                    for privilege in ("INSERT", "UPDATE", "REFERENCES"):
                        allowed = db.scalar(text("SELECT pg_catalog.has_column_privilege(current_user, :table, :column, :privilege)"), {"table": name, "column": column, "privilege": privilege})
                        if bool(allowed) != (privilege == "INSERT" and column in allowed_insert):
                            raise DatabaseBoundaryError("注销请求的字段权限不正确。")
            elif table not in {"wearing_sessions", "wearing_oidc_states"}:
                for privilege in ("INSERT", "UPDATE", "DELETE"):
                    if db.scalar(text("SELECT pg_catalog.has_table_privilege(current_user, :table, :privilege)"), {"table": SCHEMA + "." + table, "privilege": privilege}):
                        raise DatabaseBoundaryError("网页数据库角色不能修改会员或路由。")
                for privilege in ("INSERT", "UPDATE", "REFERENCES"):
                    if db.scalar(text("SELECT pg_catalog.has_any_column_privilege(current_user, :table, :privilege)"), {"table": name, "privilege": privilege}):
                        raise DatabaseBoundaryError("网页数据库角色不能修改会员或路由字段。")
            else:
                for privilege in ("INSERT", "DELETE"):
                    if not db.scalar(text("SELECT pg_catalog.has_table_privilege(current_user, :table, :privilege)"), {"table": name, "privilege": privilege}):
                        raise DatabaseBoundaryError("网页数据库角色缺少登录记录权限。")
                for column in ("id_hash", "user_id", "tenant_id", "csrf", "expires", "auth_time") if table == "wearing_sessions" else ("id_hash", "value", "expires"):
                    allowed = db.scalar(text("SELECT pg_catalog.has_column_privilege(current_user, :table, :column, 'UPDATE')"), {"table": name, "column": column})
                    if bool(allowed) != (table == "wearing_sessions" and column == "tenant_id"):
                        raise DatabaseBoundaryError("网页数据库角色只能更新登录记录的租户字段。")
        policies = db.execute(text("""
            SELECT tablename, policyname FROM pg_catalog.pg_policies WHERE schemaname = 'wearing_control'
        """)).all()
        expected = {(table, name) for table in TABLES for name in ("operator_all", "web_scope")}
        if set(policies) != expected:
            raise DatabaseBoundaryError("平台 RLS 策略缺失或存在额外策略。")


def same_database(first, second):
    a, b = make_url(first), make_url(second)
    return (a.drivername, a.host, a.port, a.database, a.query) == (b.drivername, b.host, b.port, b.database, b.query)


def migrate_database(value):
    url = make_url(value)
    if url.drivername != "postgresql+psycopg":
        raise DatabaseBoundaryError("生产迁移入口只接受 PostgreSQL。")
    engine = create_engine(value, hide_parameters=True)
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).with_name("migrations")))
    try:
        with engine.begin() as db:
            if db.scalar(text("""
                SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_roles r WHERE r.rolname = current_user
                  AND (r.rolsuper OR r.rolbypassrls OR r.rolcreaterole OR r.rolcreatedb
                    OR pg_catalog.pg_has_role(current_user, 'wearing_web', 'MEMBER')
                    OR pg_catalog.pg_has_role(current_user, 'wearing_operator', 'MEMBER')))
            """)):
                raise DatabaseBoundaryError("迁移需要独立对象所有者，不能复用网页、操作者或超级用户凭据。")
            db.execute(text("SELECT pg_catalog.pg_advisory_xact_lock(8247991101)"))
            config.attributes["connection"] = db
            command.upgrade(config, "head")
    finally:
        engine.dispose()
