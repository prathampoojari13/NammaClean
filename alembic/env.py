import sys
from pathlib import Path
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from alembic import context

# Ensure app package is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
from app.core.database import Base
import geoalchemy2  # Register GeoAlchemy2 Alembic type comparator & operations
import app.models  # Register User, Ward, UserWardAssignment, CollectionPoint with Base.metadata


# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Normal Alembic commands use application settings. The guarded test-database
# migration utility supplies an already verified connection instead.
if not config.attributes.get("require_external_connection"):
    config.set_main_option("sqlalchemy.url", settings.sync_database_url)

# Add model's MetaData object here for 'autogenerate' support
target_metadata = Base.metadata


def include_object(object, name, type_, reflected, compare_to):
    """
    Filter objects so Alembic only manages application tables (users, wards, etc.)
    present in SQLAlchemy Base.metadata, completely ignoring PostGIS/tiger/external tables.
    """
    if type_ == "table":
        return name in target_metadata.tables
    return True



def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL and not an Engine,
    though an Engine is acceptable here as well. By skipping the Engine creation
    we don't even need a DBAPI to be available.
    """
    if config.attributes.get("require_external_connection"):
        raise RuntimeError("Guarded test-database migrations require an online verified connection.")

    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


def _run_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations on a supplied verified connection or the normal app URL."""
    if config.attributes.get("require_external_connection"):
        connection = config.attributes.get("connection")
        if connection is None:
            raise RuntimeError("A verified external connection is required for this migration.")
        _run_migrations(connection)
        return

    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        _run_migrations(connection)



if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
