from alembic import context
from sqlalchemy import text

from wearing.cloud.postgres import SCHEMA


connection = context.config.attributes.get("connection")
if connection is None or connection.dialect.name != "postgresql":
    raise RuntimeError("Use the Wearing PostgreSQL operator migration command")
connection.execute(text("CREATE SCHEMA IF NOT EXISTS wearing_control"))
context.configure(connection=connection, version_table_schema=SCHEMA, transactional_ddl=True)
with context.begin_transaction():
    context.run_migrations()
