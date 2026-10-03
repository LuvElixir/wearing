"""Initial private control metadata, privileges and row scope."""

from alembic import op
from sqlalchemy import text

from wearing.cloud.control import metadata
from wearing.cloud.postgres import OPERATOR_ROLE, SCHEMA, TABLES, WEB_ROLE

revision = "wearing_control_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    db = op.get_bind()
    roles = db.execute(text("SELECT rolname FROM pg_catalog.pg_roles WHERE rolname IN ('wearing_web', 'wearing_operator')")).scalars().all()
    if set(roles) != {WEB_ROLE, OPERATOR_ROLE}:
        raise RuntimeError("Provision the two NOLOGIN privilege roles before migration")
    if db.scalar(text("""
        SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_roles
          WHERE rolname IN ('wearing_web', 'wearing_operator')
            AND (rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole OR rolbypassrls))
    """)):
        raise RuntimeError("Wearing privilege groups must be non-login, non-administrative roles")
    if db.scalar(text("""
        SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
          WHERE n.nspname = 'wearing_control' AND c.relname LIKE 'wearing_%')
    """)):
        raise RuntimeError("Initial migration refuses to adopt unversioned Wearing tables")
    metadata.create_all(db.execution_options(schema_translate_map={None: SCHEMA}))
    db.execute(text("REVOKE ALL ON SCHEMA wearing_control FROM PUBLIC"))
    db.execute(text("GRANT USAGE ON SCHEMA wearing_control TO wearing_web, wearing_operator"))
    for table in TABLES:
        db.execute(text(f"REVOKE ALL ON wearing_control.{table} FROM PUBLIC, wearing_web"))
        db.execute(text(f"ALTER TABLE wearing_control.{table} ENABLE ROW LEVEL SECURITY"))
        db.execute(text(f"ALTER TABLE wearing_control.{table} FORCE ROW LEVEL SECURITY"))
        db.execute(text(f"CREATE POLICY operator_all ON wearing_control.{table} TO wearing_operator USING (true) WITH CHECK (true)"))
        db.execute(text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON wearing_control.{table} TO wearing_operator"))
        db.execute(text(f"GRANT SELECT ON wearing_control.{table} TO wearing_web"))
    scopes = {
        "wearing_users": "(id = current_setting('wearing.user_id', true) OR (issuer = current_setting('wearing.issuer', true) AND subject = current_setting('wearing.subject', true)))",
        "wearing_memberships": "user_id = current_setting('wearing.user_id', true)",
        "wearing_tenants": "id = current_setting('wearing.tenant_id', true) AND EXISTS (SELECT 1 FROM wearing_control.wearing_memberships m WHERE m.tenant_id = id AND m.user_id = current_setting('wearing.user_id', true) AND m.active)",
        "wearing_routes": "tenant_id = current_setting('wearing.tenant_id', true) AND EXISTS (SELECT 1 FROM wearing_control.wearing_memberships m WHERE m.tenant_id = wearing_routes.tenant_id AND m.user_id = current_setting('wearing.user_id', true) AND m.active)",
        "wearing_sessions": "id_hash = current_setting('wearing.session_hash', true)",
        "wearing_oidc_states": "id_hash = current_setting('wearing.state_hash', true)",
    }
    for table, expression in scopes.items():
        if table == "wearing_sessions":
            check = expression + " AND user_id = current_setting('wearing.user_id', true) AND EXISTS (SELECT 1 FROM wearing_control.wearing_memberships m WHERE m.user_id = wearing_sessions.user_id AND m.tenant_id = wearing_sessions.tenant_id AND m.active)"
            db.execute(text(f"CREATE POLICY web_scope ON wearing_control.{table} TO wearing_web USING ({expression}) WITH CHECK ({check})"))
        elif table == "wearing_oidc_states":
            db.execute(text(f"CREATE POLICY web_scope ON wearing_control.{table} TO wearing_web USING ({expression}) WITH CHECK ({expression})"))
        else:
            db.execute(text(f"CREATE POLICY web_scope ON wearing_control.{table} FOR SELECT TO wearing_web USING ({expression})"))
    db.execute(text("GRANT INSERT, DELETE ON wearing_control.wearing_sessions, wearing_control.wearing_oidc_states TO wearing_web"))
    db.execute(text("GRANT UPDATE (tenant_id) ON wearing_control.wearing_sessions TO wearing_web"))
    db.execute(text("GRANT SELECT ON wearing_control.alembic_version TO wearing_web, wearing_operator"))


def downgrade():
    raise RuntimeError("This initial control migration has no destructive automatic downgrade")
