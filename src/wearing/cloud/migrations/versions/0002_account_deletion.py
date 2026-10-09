"""Explicit ownership and immutable self-service deletion admission."""
from alembic import op
from sqlalchemy import text

revision = "wearing_control_0002"
down_revision = "wearing_control_0001"
branch_labels = None
depends_on = None


def upgrade():
    db = op.get_bind()
    for table in ("wearing_users", "wearing_tenants"):
        db.execute(text(f"ALTER TABLE wearing_control.{table} ADD COLUMN deletion_state varchar(16) NOT NULL DEFAULT 'active' CHECK (deletion_state IN ('active','frozen'))"))
    db.execute(text("ALTER TABLE wearing_control.wearing_sessions ADD COLUMN auth_time integer"))
    db.execute(text("""CREATE TABLE wearing_control.wearing_tenant_ownership (
      tenant_id varchar(128) PRIMARY KEY REFERENCES wearing_control.wearing_tenants(id),
      classification varchar(16) NOT NULL CHECK(classification IN ('private','shared','unknown')),
      owner_user_id varchar(128) REFERENCES wearing_control.wearing_users(id),
      member_count integer NOT NULL CHECK(member_count>0), member_digest varchar(64) NOT NULL,
      instance_id varchar(128), revision integer NOT NULL CHECK(revision>0))"""))
    db.execute(text("""CREATE TABLE wearing_control.wearing_deletion_requests (
      id varchar(32) PRIMARY KEY, user_id varchar(128) NOT NULL UNIQUE REFERENCES wearing_control.wearing_users(id),
      request_key varchar(120) NOT NULL, plan_revision varchar(64) NOT NULL, plan_json text NOT NULL,
      created_at integer NOT NULL, state varchar(32) NOT NULL DEFAULT 'awaiting_operator'
        CHECK(state IN ('awaiting_operator','frozen','waiting','completed')),
      code varchar(64) NOT NULL DEFAULT 'adapter_unconfigured', updated_at integer,
      UNIQUE(user_id,request_key))"""))
    for table in ("wearing_tenant_ownership", "wearing_deletion_requests"):
        db.execute(text(f"REVOKE ALL ON wearing_control.{table} FROM PUBLIC, wearing_web"))
        db.execute(text(f"ALTER TABLE wearing_control.{table} ENABLE ROW LEVEL SECURITY"))
        db.execute(text(f"ALTER TABLE wearing_control.{table} FORCE ROW LEVEL SECURITY"))
        db.execute(text(f"CREATE POLICY operator_all ON wearing_control.{table} TO wearing_operator USING (true) WITH CHECK (true)"))
        db.execute(text(f"GRANT SELECT,INSERT,UPDATE,DELETE ON wearing_control.{table} TO wearing_operator"))
        db.execute(text(f"GRANT SELECT ON wearing_control.{table} TO wearing_web"))
    db.execute(text("""CREATE POLICY web_scope ON wearing_control.wearing_tenant_ownership FOR SELECT TO wearing_web USING
      (EXISTS (SELECT 1 FROM wearing_control.wearing_memberships m WHERE m.tenant_id=wearing_tenant_ownership.tenant_id
        AND m.user_id=current_setting('wearing.user_id',true)))"""))
    db.execute(text("""CREATE POLICY web_scope ON wearing_control.wearing_deletion_requests TO wearing_web
      USING (user_id=current_setting('wearing.user_id',true))
      WITH CHECK (user_id=current_setting('wearing.user_id',true) AND state='awaiting_operator'
        AND code='adapter_unconfigured' AND updated_at IS NULL
        AND EXISTS(SELECT 1 FROM wearing_control.wearing_users u WHERE u.id=user_id AND u.deletion_state='active'))"""))
    db.execute(text("GRANT INSERT (id,user_id,request_key,plan_revision,plan_json,created_at) ON wearing_control.wearing_deletion_requests TO wearing_web"))
    db.execute(text("DROP POLICY web_scope ON wearing_control.wearing_sessions"))
    db.execute(text("""CREATE POLICY web_scope ON wearing_control.wearing_sessions TO wearing_web
      USING (id_hash=current_setting('wearing.session_hash',true)) WITH CHECK
      (id_hash=current_setting('wearing.session_hash',true) AND user_id=current_setting('wearing.user_id',true)
       AND EXISTS(SELECT 1 FROM wearing_control.wearing_memberships m WHERE m.user_id=wearing_sessions.user_id
         AND m.tenant_id=wearing_sessions.tenant_id AND m.active)
       AND EXISTS(SELECT 1 FROM wearing_control.wearing_users u WHERE u.id=wearing_sessions.user_id AND u.deletion_state='active')
       AND NOT EXISTS(SELECT 1 FROM wearing_control.wearing_deletion_requests d WHERE d.user_id=wearing_sessions.user_id))"""))


def downgrade():
    raise RuntimeError("Deletion fences and receipts must not be automatically discarded")
