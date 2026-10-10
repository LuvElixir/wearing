#!/usr/bin/env python3
"""One fixed call, under a dedicated EXECUTE-only database identity."""
import argparse
import json
from pathlib import Path

from sqlalchemy import create_engine, text

from wearing.cloud.instance import read_private
from wearing.cloud.migrations.invitation_0003 import CLEANUP_FUNCTION_BODY
from wearing.cloud.postgres import validate_database_url


def cleanup(database_url):
    validate_database_url(database_url, development=False)
    engine = create_engine(database_url, hide_parameters=True)
    try:
        with engine.begin() as db:
            db.execute(text("SET LOCAL statement_timeout='10s'"))
            db.execute(text("SET LOCAL lock_timeout='2s'"))
            roles = db.execute(text('''SELECT r.rolname,r.rolsuper,r.rolbypassrls,r.rolcreatedb,r.rolcreaterole
              FROM pg_catalog.pg_roles r WHERE pg_catalog.pg_has_role(current_user,r.oid,'MEMBER')''')).mappings().all()
            if any(any(r[k] for k in ('rolsuper','rolbypassrls','rolcreatedb','rolcreaterole')) for r in roles):
                raise ValueError('maintenance_role_boundary')
            current = db.scalar(text('SELECT current_user'))
            if {r['rolname'] for r in roles} != {current, 'wearing_cleanup'}:
                raise ValueError('maintenance_role_boundary')
            target = db.execute(text('''SELECT p.prosecdef,p.prosrc,p.proconfig,pg_get_userbyid(p.proowner) AS owner,
              p.proowner=n.nspowner AS schema_owner,r.rolsuper,r.rolbypassrls,r.rolcreatedb,r.rolcreaterole,
              EXISTS(SELECT 1 FROM aclexplode(COALESCE(p.proacl,acldefault('f',p.proowner))) a
                WHERE a.grantee=0 AND a.privilege_type='EXECUTE') AS public_execute
              FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace JOIN pg_roles r ON r.oid=p.proowner
              WHERE n.nspname='wearing_control' AND p.proname='delete_expired_states' AND p.pronargs=0''')).mappings().one()
            if (not target['prosecdef'] or target['prosrc'] != CLEANUP_FUNCTION_BODY
                    or target['proconfig'] != ['search_path=pg_catalog, wearing_control'] or target['owner']==current
                    or not target['schema_owner'] or target['public_execute']
                    or any(target[k] for k in ('rolsuper','rolbypassrls','rolcreatedb','rolcreaterole'))):
                raise ValueError('maintenance_function_boundary')
            if db.scalar(text("SELECT has_schema_privilege(current_user,'wearing_control','CREATE')")):
                raise ValueError('maintenance_schema_boundary')
            tables = db.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='wearing_control'")).scalars().all()
            for table in tables:
                for permission in ('SELECT','INSERT','UPDATE','DELETE','TRUNCATE','REFERENCES','TRIGGER'):
                    if db.scalar(text('SELECT has_table_privilege(current_user,:table,:permission)'),
                                 {'table':'wearing_control.'+table,'permission':permission}):
                        raise ValueError('maintenance_table_boundary')
                for permission in ('SELECT','INSERT','UPDATE','REFERENCES'):
                    if db.scalar(text('SELECT has_any_column_privilege(current_user,:table,:permission)'),
                                 {'table':'wearing_control.'+table,'permission':permission}):
                        raise ValueError('maintenance_column_boundary')
            allowed = db.execute(text('''SELECT p.proname,p.pronargs FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
              WHERE n.nspname='wearing_control' AND has_function_privilege(current_user,p.oid,'EXECUTE')''')).all()
            if allowed != [('delete_expired_states', 0)]:
                raise ValueError('maintenance_function_boundary')
            count = db.scalar(text('SELECT wearing_control.delete_expired_states()'))
            if type(count) is not int or not 0 <= count <= 5000:
                raise ValueError('maintenance_count_boundary')
            return count
    finally:
        engine.dispose()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    args = parser.parse_args()
    config = json.loads(read_private(Path(args.config)))
    print(json.dumps({'expired_states_removed': cleanup(config['database_url'])}))


if __name__ == '__main__':
    try:
        main()
    except Exception:
        raise SystemExit('expired_state_cleanup_failed') from None
