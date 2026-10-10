"""PostgreSQL control-plane migrations and transaction scopes, not tenant storage."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


SCHEMA = "wearing_control"
REVISION = "wearing_control_0004"
WEB_ROLE = "wearing_web"
OPERATOR_ROLE = "wearing_operator"
REGISTRATION_ROLE = "wearing_registration"
ACTIVATION_ROLE = "wearing_activation"
TABLES = ("wearing_users", "wearing_tenants", "wearing_memberships", "wearing_routes", "wearing_sessions", "wearing_oidc_states", "wearing_tenant_ownership", "wearing_deletion_requests", "wearing_invitations", "wearing_bundles", "wearing_bundle_activations")
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


def assert_database_boundary(engine, *, operator=False, registration=False, activation=False):
    with engine.connect() as db:
        version = db.execute(text("SELECT version_num FROM wearing_control.alembic_version")).scalars().all()
        if version != [REVISION]:
            raise DatabaseBoundaryError("平台数据库版本不匹配；请通过操作者迁移入口升级。")
        role = db.execute(text("""
            SELECT r.rolsuper, r.rolbypassrls, r.rolcreaterole, r.rolcreatedb,
                   pg_catalog.pg_has_role(current_user, 'wearing_web', 'MEMBER') AS web,
                   pg_catalog.pg_has_role(current_user, 'wearing_operator', 'MEMBER') AS operator,
                   pg_catalog.pg_has_role(current_user, 'wearing_registration', 'MEMBER') AS registration,
                   pg_catalog.pg_has_role(current_user, 'wearing_activation', 'MEMBER') AS activation,
                   pg_catalog.pg_has_role(current_user, 'wearing_cleanup', 'MEMBER') AS cleanup
            FROM pg_catalog.pg_roles r WHERE r.rolname = current_user
        """)).mappings().one()
        if operator:
            if not role["operator"] or role["web"] or role["registration"] or role["cleanup"] or role["activation"] or any(role[k] for k in ("rolsuper", "rolbypassrls", "rolcreaterole", "rolcreatedb")):
                raise DatabaseBoundaryError("登记和撤销需要单独的操作者角色。")
        elif registration:
            if not role["registration"] or role["web"] or role["operator"] or role["cleanup"] or role["activation"] or any(role[k] for k in ("rolsuper", "rolbypassrls", "rolcreaterole", "rolcreatedb")):
                raise DatabaseBoundaryError("注册服务需要独立的最小权限角色。")
        elif activation:
            if not role["activation"] or any(role[k] for k in ("web","operator","registration","cleanup","rolsuper","rolbypassrls","rolcreaterole","rolcreatedb")):
                raise DatabaseBoundaryError("分配服务需要独立的最小权限角色。")
        elif (any(role[k] for k in ("rolsuper", "rolbypassrls", "rolcreaterole", "rolcreatedb", "operator", "registration", "cleanup", "activation")) or not role["web"]):
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
        assert_invitation_functions(db, registration=registration, operator=operator, activation=activation)
        if operator:
            return
        if registration or activation:
            for table in TABLES:
                for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"):
                    if db.scalar(text("SELECT pg_catalog.has_table_privilege(current_user, :table, :privilege)"), {"table": SCHEMA + "." + table, "privilege": privilege}):
                        raise DatabaseBoundaryError("注册服务不能直接读取或修改平台数据表。")
                for privilege in ("SELECT", "INSERT", "UPDATE", "REFERENCES"):
                    if db.scalar(text("SELECT pg_catalog.has_any_column_privilege(current_user, :table, :privilege)"), {"table": SCHEMA + "." + table, "privilege": privilege}):
                        raise DatabaseBoundaryError("注册服务不能直接读取或修改平台字段。")
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
        from .migrations.bundle_0004 import DEFINER_TABLES
        expected = {(table, name) for table in TABLES for name in ("operator_all", "web_scope")}
        expected |= {(table, "invitation_definer") for table in DEFINER_TABLES}
        expected.add(('wearing_oidc_states','cleanup_definer'))
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
                    OR pg_catalog.pg_has_role(current_user, 'wearing_operator', 'MEMBER')
                    OR pg_catalog.pg_has_role(current_user, 'wearing_registration', 'MEMBER')
                    OR pg_catalog.pg_has_role(current_user, 'wearing_cleanup', 'MEMBER')
                    OR pg_catalog.pg_has_role(current_user, 'wearing_activation', 'MEMBER')))
            """)):
                raise DatabaseBoundaryError("迁移需要独立对象所有者，不能复用网页、操作者或超级用户凭据。")
            db.execute(text("SELECT pg_catalog.pg_advisory_xact_lock(8247991101)"))
            config.attributes["connection"] = db
            command.upgrade(config, "head")
    finally:
        engine.dispose()


def assert_invitation_functions(db, *, registration, operator, activation=False):
    """Reject broadened DEFINER grants/body/search_path, not merely missing RLS."""
    from .migrations.invitation_0003 import CLEANUP_FUNCTION_BODY
    from .migrations.bundle_0004 import (ACTIVATION_FUNCTIONS, DEFINER_TABLES, FUNCTION_BODIES,
        FUNCTION_SIGNATURES, REGISTRATION_FUNCTIONS, WEB_FUNCTIONS, TRIGGER_BODIES)
    expected = REGISTRATION_FUNCTIONS if registration else ACTIVATION_FUNCTIONS if activation else set() if operator else WEB_FUNCTIONS
    owners = set()
    for name, signature in {**FUNCTION_SIGNATURES,'delete_expired_states':''}.items():
        row = db.execute(text("""SELECT p.oid,p.prosrc,p.prosecdef,p.proconfig,p.proowner,
          r.rolname AS owner, r.rolsuper,r.rolbypassrls,r.rolcreaterole,r.rolcreatedb,
          pg_catalog.pg_has_role(current_user,p.proowner,'MEMBER') AS owns,
          pg_catalog.has_function_privilege(current_user,p.oid,'EXECUTE') AS executable,
          EXISTS(SELECT 1 FROM pg_catalog.aclexplode(COALESCE(p.proacl,pg_catalog.acldefault('f',p.proowner))) a
            WHERE a.grantee=0 AND a.privilege_type='EXECUTE') AS public_execute
          FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_roles r ON r.oid=p.proowner
          WHERE p.oid=pg_catalog.to_regprocedure(:signature)"""),
          {'signature': SCHEMA + '.' + name + '(' + signature + ')'}).mappings().first()
        body = CLEANUP_FUNCTION_BODY if name == 'delete_expired_states' else FUNCTION_BODIES[name]
        if (not row or not row['prosecdef'] or row['prosrc'] != body
                or row['proconfig'] != ['search_path=pg_catalog, wearing_control']
                or row['public_execute'] or row['owns'] or bool(row['executable']) != (name in expected)
                or any(row[k] for k in ('rolsuper','rolbypassrls','rolcreaterole','rolcreatedb'))):
            raise DatabaseBoundaryError('邀请码数据库函数的最小权限或实现校验未通过。')
        owners.add(row['owner'])
    if len(owners) != 1:
        raise DatabaseBoundaryError('邀请码数据库函数所有者不一致。')
    owner = next(iter(owners))
    rows = db.execute(text("""SELECT tablename,roles,cmd,qual,with_check FROM pg_catalog.pg_policies
        WHERE schemaname='wearing_control' AND policyname='invitation_definer'""")).mappings().all()
    if ({row['tablename'] for row in rows} != DEFINER_TABLES or any(
            list(row['roles']) != [owner] or row['cmd'] != 'ALL' or row['qual'] != 'true' or row['with_check'] != 'true'
            for row in rows)):
        raise DatabaseBoundaryError('邀请码数据库函数的行级作用域校验未通过。')
    cleanup = db.execute(text("""SELECT tablename,roles,cmd,qual,with_check FROM pg_catalog.pg_policies
        WHERE schemaname='wearing_control' AND policyname='cleanup_definer'""")).mappings().all()
    if (len(cleanup) != 1 or cleanup[0]['tablename'] != 'wearing_oidc_states'
            or list(cleanup[0]['roles']) != [owner] or cleanup[0]['cmd'] != 'ALL'
            or cleanup[0]['qual'] != 'true' or cleanup[0]['with_check'] != 'true'):
        raise DatabaseBoundaryError('过期状态清理函数的行级作用域校验未通过。')

    for name, body in TRIGGER_BODIES.items():
        row = db.execute(text("""SELECT p.prosrc,p.prosecdef,p.proconfig,p.proowner,
          pg_catalog.has_function_privilege(current_user,p.oid,'EXECUTE') executable,
          EXISTS(SELECT 1 FROM pg_catalog.aclexplode(COALESCE(p.proacl,pg_catalog.acldefault('f',p.proowner))) a
            WHERE a.grantee=0 AND a.privilege_type='EXECUTE') public_execute,
          (SELECT jsonb_agg(jsonb_build_object('name',t.tgname,'type',t.tgtype,'table',c.relname,
            'enabled',t.tgenabled,'condition',t.tgqual IS NULL,'schema',n.nspname))
            FROM pg_catalog.pg_trigger t JOIN pg_catalog.pg_class c ON c.oid=t.tgrelid
            JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
            WHERE t.tgfoid=p.oid AND NOT t.tgisinternal) triggers
          FROM pg_catalog.pg_proc p WHERE p.oid=pg_catalog.to_regprocedure(:signature)"""),
          {'signature': SCHEMA+'.'+name+'()'}).mappings().first()
        table, kind = {'bundle_immutable': ('wearing_bundles',27),
                       'invitation_bundle_immutable': ('wearing_invitations',23),
                       'activation_scope_immutable': ('wearing_bundle_activations',19)}[name]
        expected_trigger = [{'name':name,'type':kind,'table':table,'enabled':'O','condition':True,'schema':SCHEMA}]
        if (not row or row['prosrc'] != body or row['prosecdef'] or row['triggers'] != expected_trigger
                or row['proconfig'] != ['search_path=pg_catalog, wearing_control']
                or row['public_execute'] or row['executable']
                or row['proowner'] != db.scalar(text('SELECT oid FROM pg_catalog.pg_roles WHERE rolname=:owner'), {'owner': owner})):
            raise DatabaseBoundaryError('资源绑定不可变约束校验未通过。')
