"""Database access for every process (ADR 0017).

Business code obtains a connection only through :meth:`Database.tenant_transaction`, which sets
the tenant for row-level security before any statement runs. Forgetting the tenant therefore
cannot leak data: without it, tenant tables return no rows (ADR 0005).
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.conninfo import make_conninfo
from psycopg_pool import AsyncConnectionPool

from synapse.kernel.secrets import read_secret

# Transaction-local setting read by the SQL function app_current_tenant().
TENANT_SETTING = "app.tenant_id"


@dataclass(frozen=True)
class ConnectionSettings:
    host: str
    port: int
    dbname: str
    user: str
    password_file: Path
    # Identifies the process in pg_stat_activity, which is how operators find slow queries.
    application_name: str = "synapse"

    def conninfo(self) -> str:
        return make_conninfo(
            host=self.host,
            port=self.port,
            dbname=self.dbname,
            user=self.user,
            password=read_secret(self.password_file),
            application_name=self.application_name,
        )


class Database:
    """A connection pool for one process role."""

    def __init__(self, settings: ConnectionSettings, *, min_size: int = 1, max_size: int = 10):
        self._pool = AsyncConnectionPool(
            conninfo=settings.conninfo(),
            min_size=min_size,
            max_size=max_size,
            open=False,
            # Connections are checked before use, so a restarted database does not surface as
            # errors on the first request after the restart.
            check=AsyncConnectionPool.check_connection,
        )

    async def open(self) -> None:
        await self._pool.open(wait=True)

    async def close(self) -> None:
        await self._pool.close()

    @asynccontextmanager
    async def tenant_transaction(self, tenant_id: UUID) -> AsyncIterator[AsyncConnection]:
        """A transaction in which row-level security sees only ``tenant_id``."""
        async with self._pool.connection() as connection, connection.transaction():
            await connection.execute(
                "SELECT set_config(%s, %s, true)", (TENANT_SETTING, str(tenant_id))
            )
            yield connection

    @asynccontextmanager
    async def system_transaction(self) -> AsyncIterator[AsyncConnection]:
        """A transaction without a tenant, for cluster-wide maintenance only.

        Tenant tables return no rows here. Request handlers must never use this.
        """
        async with self._pool.connection() as connection, connection.transaction():
            yield connection
