"""Alembic environment: connects as the migrator and runs migrations in one transaction each."""

from alembic import context
from sqlalchemy import create_engine

from synapse.dbadmin.roles import SCHEMA

url = context.config.attributes["sqlalchemy_url"]
engine = create_engine(url)

with engine.connect() as connection:
    context.configure(
        connection=connection,
        # The version table lives with everything else, in the synapse schema.
        version_table_schema=SCHEMA,
        transaction_per_migration=True,
    )
    with context.begin_transaction():
        context.run_migrations()

engine.dispose()
