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
  IF EXISTS (SELECT FROM pg_catalog.pg_roles
             WHERE rolname IN ('wearing_web', 'wearing_operator')
               AND (rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole OR rolbypassrls)) THEN
    RAISE EXCEPTION 'Existing Wearing privilege roles do not match the required boundary';
  END IF;
END $$;
-- Provision separate LOGIN roles through the operator's secret system, then:
-- GRANT wearing_web TO <application_login>;
-- GRANT wearing_operator TO <operator_login>;
-- The migration owner must be separate from both; never grant it to the app.
