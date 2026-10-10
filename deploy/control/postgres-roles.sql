-- Execute as a database administrator on a dedicated Wearing control database.
-- No login passwords, superuser credentials or tenant content belong here.
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'wearing_web') THEN
    CREATE ROLE wearing_web NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
  END IF;
  IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'wearing_operator') THEN
    CREATE ROLE wearing_operator NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
  END IF;
  IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'wearing_registration') THEN
    CREATE ROLE wearing_registration NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
  END IF;
  IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'wearing_cleanup') THEN
    CREATE ROLE wearing_cleanup NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
  END IF;
  IF EXISTS (SELECT FROM pg_catalog.pg_roles
             WHERE rolname IN ('wearing_web', 'wearing_operator', 'wearing_registration', 'wearing_cleanup')
               AND (rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole OR rolbypassrls)) THEN
    RAISE EXCEPTION 'Existing Wearing privilege roles do not match the required boundary';
  END IF;
END $$;
-- Provision separate LOGIN roles through the operator's secret system, then:
-- GRANT wearing_web TO <application_login>;
-- GRANT wearing_operator TO <operator_login>;
-- GRANT wearing_registration TO <registration_broker_login>;
-- GRANT wearing_cleanup TO <expired_state_maintenance_login>;
-- The registration broker role can execute only the fixed invitation functions.
-- Never grant the operator, web or migration roles to the registration broker.
-- The migration owner must be separate from both; never grant it to the app.
