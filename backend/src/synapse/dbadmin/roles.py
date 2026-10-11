"""Database roles and their limits (ADR 0013, ADR 0017)."""

from dataclasses import dataclass

SCHEMA = "synapse"
MIGRATOR = "synapse_migrator"
RUNTIME_GROUP = "synapse_runtime"


@dataclass(frozen=True)
class LoginRole:
    name: str
    # Upper bound for one statement. Keeps a bad query from holding locks or CPU indefinitely.
    statement_timeout: str


RUNTIME_ROLES = (
    LoginRole("synapse_api", statement_timeout="10s"),
    LoginRole("synapse_worker", statement_timeout="15min"),
    LoginRole("synapse_scheduler", statement_timeout="30min"),
)

# Runs audit_prune() and nothing else (ADR 0022): not in the runtime group, so it holds no
# table, and it logs in only from the retention container synapsectl runs each night.
RETENTION = LoginRole("synapse_retention", statement_timeout="30min")

ALL_LOGIN_ROLES = (MIGRATOR, *(role.name for role in RUNTIME_ROLES), RETENTION.name)

# A transaction left open by a crashed or stuck client is closed after this long.
IDLE_IN_TRANSACTION_TIMEOUT = "60s"
