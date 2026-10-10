"""One-use admission and a separate, create-only identity registration boundary."""
from alembic import op
from sqlalchemy import text
from wearing.cloud.migrations.invitation_0003 import (CLEANUP_FUNCTION_BODY, DEFINER_TABLES, FUNCTION_ARGUMENTS,
    FUNCTION_BODIES, FUNCTION_SIGNATURES, REGISTRATION_FUNCTIONS, WEB_FUNCTIONS)

revision = 'wearing_control_0003'
down_revision = 'wearing_control_0002'
branch_labels = None
depends_on = None


def upgrade():
    db = op.get_bind()
    if db.scalar(text("""SELECT count(*) FROM pg_catalog.pg_roles WHERE rolname IN ('wearing_registration','wearing_cleanup')
       AND NOT rolcanlogin AND NOT rolsuper AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolbypassrls""")) != 2:
        raise RuntimeError('Provision the restricted registration and cleanup NOLOGIN roles before migration')
    owner = db.scalar(text('SELECT current_user'))
    quote = db.dialect.identifier_preparer.quote
    db.execute(text('CREATE INDEX wearing_oidc_states_expiry ON wearing_control.wearing_oidc_states(expires,id_hash)'))
    db.execute(text('GRANT USAGE ON SCHEMA wearing_control TO wearing_cleanup'))
    db.execute(text(f'CREATE POLICY cleanup_definer ON wearing_control.wearing_oidc_states TO {quote(owner)} USING(true) WITH CHECK(true)'))
    db.exec_driver_sql('CREATE FUNCTION wearing_control.delete_expired_states() RETURNS integer LANGUAGE plpgsql '
        'SECURITY DEFINER SET search_path=pg_catalog,wearing_control AS $body$'+CLEANUP_FUNCTION_BODY+'$body$',
        execution_options={'no_parameters': True})
    db.execute(text('REVOKE ALL ON FUNCTION wearing_control.delete_expired_states() FROM PUBLIC,wearing_web,wearing_registration,wearing_operator'))
    db.execute(text('GRANT EXECUTE ON FUNCTION wearing_control.delete_expired_states() TO wearing_cleanup'))
    db.execute(text("""CREATE TABLE wearing_control.wearing_invitations (
      id varchar(32) PRIMARY KEY, code_hash varchar(64) NOT NULL UNIQUE,
      issuer text NOT NULL, tenant_id varchar(128) NOT NULL UNIQUE REFERENCES wearing_control.wearing_tenants(id),
      instance_id varchar(128) NOT NULL, created_at integer NOT NULL, expires_at integer NOT NULL CHECK(expires_at>created_at),
      revoked_at integer, redeemed_user_id varchar(128) REFERENCES wearing_control.wearing_users(id), redeemed_at integer,
      registration_id varchar(32) UNIQUE, username_hash varchar(64), registration_subject varchar(512),
      CHECK((redeemed_user_id IS NULL) = (redeemed_at IS NULL)),
      CHECK((registration_id IS NULL) = (username_hash IS NULL)),
      CHECK(registration_subject IS NULL OR registration_id IS NOT NULL))"""))
    db.execute(text('REVOKE ALL ON wearing_control.wearing_invitations FROM PUBLIC,wearing_web,wearing_registration'))
    db.execute(text('ALTER TABLE wearing_control.wearing_invitations ENABLE ROW LEVEL SECURITY'))
    db.execute(text('ALTER TABLE wearing_control.wearing_invitations FORCE ROW LEVEL SECURITY'))
    db.execute(text('CREATE POLICY operator_all ON wearing_control.wearing_invitations TO wearing_operator USING(true) WITH CHECK(true)'))
    db.execute(text('CREATE POLICY web_scope ON wearing_control.wearing_invitations FOR SELECT TO wearing_web USING(false)'))
    db.execute(text('GRANT SELECT,INSERT,UPDATE,DELETE ON wearing_control.wearing_invitations TO wearing_operator'))
    db.execute(text('GRANT SELECT ON wearing_control.wearing_invitations TO wearing_web'))
    db.execute(text('GRANT USAGE ON SCHEMA wearing_control TO wearing_registration'))
    db.execute(text('GRANT SELECT ON wearing_control.alembic_version TO wearing_registration'))
    # FORCE RLS still applies to SECURITY DEFINER. Only the separate schema owner
    # executes these policies; neither public worker can SET ROLE to this owner.
    for table in sorted(DEFINER_TABLES):
        db.execute(text(f'CREATE POLICY invitation_definer ON wearing_control.{table} TO {quote(owner)} USING(true) WITH CHECK(true)'))
    for name, body in FUNCTION_BODIES.items():
        result = 'boolean' if name == 'invitation_check' else 'jsonb'
        db.exec_driver_sql(f'CREATE FUNCTION wearing_control.{name}({FUNCTION_ARGUMENTS[name]}) RETURNS {result} '
            f'LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,wearing_control AS $body${body}$body$',
            execution_options={'no_parameters': True})
        signature = f'wearing_control.{name}({FUNCTION_SIGNATURES[name]})'
        db.execute(text(f'REVOKE ALL ON FUNCTION {signature} FROM PUBLIC,wearing_web,wearing_registration,wearing_operator'))
        if name in WEB_FUNCTIONS:
            db.execute(text(f'GRANT EXECUTE ON FUNCTION {signature} TO wearing_web'))
        if name in REGISTRATION_FUNCTIONS:
            db.execute(text(f'GRANT EXECUTE ON FUNCTION {signature} TO wearing_registration'))


def downgrade():
    raise RuntimeError('Admission and registration receipts must not be automatically discarded')
