"""Immutable capacity bindings and authenticated, fenced activation outbox."""
from alembic import op
from sqlalchemy import text
from wearing.cloud.migrations.bundle_0004 import (ACTIVATION_FUNCTIONS, DEFINER_TABLES, FUNCTION_ARGUMENTS,
    FUNCTION_BODIES, FUNCTION_SIGNATURES, REGISTRATION_FUNCTIONS, TABLES, TRIGGER_BODIES, WEB_FUNCTIONS)

revision = 'wearing_control_0004'
down_revision = 'wearing_control_0003'
branch_labels = None
depends_on = None


def upgrade():
    db = op.get_bind()
    if db.scalar(text("""SELECT count(*) FROM pg_catalog.pg_roles WHERE rolname='wearing_activation'
       AND NOT rolcanlogin AND NOT rolsuper AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolbypassrls""")) != 1:
        raise RuntimeError('Provision the restricted activation NOLOGIN role before migration')
    owner = db.scalar(text('SELECT current_user'))
    quote = db.dialect.identifier_preparer.quote
    db.execute(text("""CREATE TABLE wearing_control.wearing_bundles (
      id varchar(32) PRIMARY KEY CHECK(id ~ '^[a-f0-9]{32}$'),
      tenant_id varchar(128) NOT NULL UNIQUE REFERENCES wearing_control.wearing_tenants(id),
      instance_id varchar(128) NOT NULL, host varchar(128) NOT NULL,
      reservation_sha256 varchar(64) NOT NULL CHECK(reservation_sha256 ~ '^[a-f0-9]{64}$'),
      worker_plan_sha256 varchar(64) NOT NULL CHECK(worker_plan_sha256 ~ '^[a-f0-9]{64}$'),
      members_json text NOT NULL CHECK(jsonb_typeof(members_json::jsonb)='object'),
      reservation_expires_at integer NOT NULL, created_at integer NOT NULL,
      CHECK(reservation_expires_at>created_at))"""))
    db.execute(text("""ALTER TABLE wearing_control.wearing_invitations
      ADD COLUMN bundle_id varchar(32) UNIQUE REFERENCES wearing_control.wearing_bundles(id)"""))
    db.execute(text("""CREATE TABLE wearing_control.wearing_bundle_activations (
      id varchar(32) PRIMARY KEY CHECK(id ~ '^[a-f0-9]{32}$'),
      invitation_id varchar(32) NOT NULL UNIQUE REFERENCES wearing_control.wearing_invitations(id),
      bundle_id varchar(32) NOT NULL UNIQUE REFERENCES wearing_control.wearing_bundles(id),
      user_id varchar(128) NOT NULL REFERENCES wearing_control.wearing_users(id),
      tenant_id varchar(128) NOT NULL REFERENCES wearing_control.wearing_tenants(id), instance_id varchar(128) NOT NULL,
      ownership_revision integer NOT NULL CHECK(ownership_revision>0),
      member_digest varchar(64) NOT NULL CHECK(member_digest ~ '^[a-f0-9]{64}$'),
      state varchar(32) NOT NULL DEFAULT 'reserved' CHECK(state IN ('reserved','preparing','installing','pairing','ready','needs_review')),
      members_json text NOT NULL CHECK(jsonb_typeof(members_json::jsonb)='object'),
      step varchar(80) NOT NULL DEFAULT 'planned', receipt_sha256 varchar(64) CHECK(receipt_sha256 ~ '^[a-f0-9]{64}$'),
      reason varchar(80) CHECK(reason='provisioning_requires_review'), generation integer NOT NULL DEFAULT 0 CHECK(generation>=0),
      lease_owner varchar(32) CHECK(lease_owner ~ '^[a-f0-9]{32}$'), lease_until integer,
      created_at integer NOT NULL, updated_at integer NOT NULL,
      CHECK((lease_owner IS NULL)=(lease_until IS NULL)),
      CHECK(state<>'ready' OR (receipt_sha256 IS NOT NULL
        AND members_json::jsonb->'core'->>'state'='ready'
        AND members_json::jsonb->'linux'->>'state'='ready'
        AND members_json::jsonb->'android'->>'state'='ready')))"""))
    db.execute(text('CREATE INDEX wearing_activation_claim ON wearing_control.wearing_bundle_activations(state,lease_until,created_at,id)'))
    for table in sorted(TABLES):
        db.execute(text(f'REVOKE ALL ON wearing_control.{table} FROM PUBLIC,wearing_web,wearing_registration,wearing_activation'))
        db.execute(text(f'ALTER TABLE wearing_control.{table} ENABLE ROW LEVEL SECURITY'))
        db.execute(text(f'ALTER TABLE wearing_control.{table} FORCE ROW LEVEL SECURITY'))
        db.execute(text(f'CREATE POLICY operator_all ON wearing_control.{table} TO wearing_operator USING(true) WITH CHECK(true)'))
        db.execute(text(f'CREATE POLICY web_scope ON wearing_control.{table} FOR SELECT TO wearing_web USING(false)'))
        db.execute(text(f'CREATE POLICY invitation_definer ON wearing_control.{table} TO {quote(owner)} USING(true) WITH CHECK(true)'))
        db.execute(text(f'GRANT SELECT ON wearing_control.{table} TO wearing_web,wearing_operator'))
    db.execute(text('GRANT INSERT ON wearing_control.wearing_bundles TO wearing_operator'))
    db.execute(text('GRANT USAGE ON SCHEMA wearing_control TO wearing_activation'))
    db.execute(text('GRANT SELECT ON wearing_control.alembic_version TO wearing_activation'))
    for name, body in FUNCTION_BODIES.items():
        result = 'boolean' if name == 'invitation_check' else 'jsonb'
        db.exec_driver_sql(f'CREATE OR REPLACE FUNCTION wearing_control.{name}({FUNCTION_ARGUMENTS[name]}) RETURNS {result} '
            f'LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,wearing_control AS $body${body}$body$',
            execution_options={'no_parameters': True})
        signature = f'wearing_control.{name}({FUNCTION_SIGNATURES[name]})'
        db.execute(text(f'REVOKE ALL ON FUNCTION {signature} FROM PUBLIC,wearing_web,wearing_registration,wearing_operator,wearing_activation'))
        for allowed, role in ((WEB_FUNCTIONS,'wearing_web'),(REGISTRATION_FUNCTIONS,'wearing_registration'),(ACTIVATION_FUNCTIONS,'wearing_activation')):
            if name in allowed:
                db.execute(text(f'GRANT EXECUTE ON FUNCTION {signature} TO {role}'))
    for name, body in TRIGGER_BODIES.items():
        db.exec_driver_sql(f'CREATE FUNCTION wearing_control.{name}() RETURNS trigger LANGUAGE plpgsql '
            f'SET search_path=pg_catalog,wearing_control AS $body${body}$body$', execution_options={'no_parameters': True})
        db.execute(text(f'REVOKE ALL ON FUNCTION wearing_control.{name}() FROM PUBLIC,wearing_web,wearing_registration,wearing_operator,wearing_activation'))
    for name, table, events in (
        ('bundle_immutable','wearing_bundles','UPDATE OR DELETE'),
        ('invitation_bundle_immutable','wearing_invitations','INSERT OR UPDATE'),
        ('activation_scope_immutable','wearing_bundle_activations','UPDATE'),
    ):
        db.execute(text(f'CREATE TRIGGER {name} BEFORE {events} ON wearing_control.{table} '
                        f'FOR EACH ROW EXECUTE FUNCTION wearing_control.{name}()'))


def downgrade():
    raise RuntimeError('Capacity reservations and activation receipts must not be automatically discarded')
