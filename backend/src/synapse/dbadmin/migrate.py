"""Running Alembic migrations as the migrator role (ADR 0017)."""

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

from synapse.kernel.database import ConnectionSettings
from synapse.kernel.secrets import read_secret


def script_config() -> Config:
    """Configuration that locates the migration scripts, without any database credentials."""
    config = Config()
    config.set_main_option("script_location", "synapse:migrations")
    return config


def alembic_config(settings: ConnectionSettings) -> Config:
    config = script_config()
    url = URL.create(
        "postgresql+psycopg",
        username=settings.user,
        password=read_secret(settings.password_file),
        host=settings.host,
        port=settings.port,
        database=settings.dbname,
    )
    # Passed as an attribute, not as a config option, so the password never goes through
    # configparser interpolation or appears in Alembic's printed configuration.
    config.attributes["sqlalchemy_url"] = url
    return config


def upgrade(settings: ConnectionSettings, revision: str = "head") -> None:
    command.upgrade(alembic_config(settings), revision)


def set_audit_periods(
    settings: ConnectionSettings, *, events_days: int, question_days: int
) -> None:
    """How long audit events and a chat question's text are kept (ADR 0022), where
    audit_prune() reads them. The migrator alone writes them, from the installation's settings;
    the table's constraints keep the floors."""
    engine = create_engine(alembic_config(settings).attributes["sqlalchemy_url"])
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE audit_settings SET keep_events_days = :events, "
                    "keep_question_days = :questions"
                ),
                {"events": events_days, "questions": question_days},
            )
    finally:
        engine.dispose()


def current_revision(settings: ConnectionSettings) -> str | None:
    """The revision the database is at, or None if it has never been migrated."""
    engine = create_engine(alembic_config(settings).attributes["sqlalchemy_url"])
    try:
        with engine.connect() as connection:
            return MigrationContext.configure(connection).get_current_revision()
    finally:
        engine.dispose()
