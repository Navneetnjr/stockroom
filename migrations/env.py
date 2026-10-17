from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app import models  # noqa: F401  (registers every table on Base.metadata)
from app.config import Config
from app.extensions import Base

# The Alembic Config object: gives access to the values in alembic.ini
config = context.config

# Set up Python logging from alembic.ini (keeping loggers that already exist, e.g. in tests)
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# The tables Alembic compares the database against when autogenerating migrations
target_metadata = Base.metadata

# Use a URL set by the caller (the tests do this), otherwise DATABASE_URL from .env
if not config.get_main_option("sqlalchemy.url"):
    if not Config.SQLALCHEMY_DATABASE_URI:
        raise RuntimeError("DATABASE_URL is not set. Copy .env.example to .env and fill it in.")
    # "%" must be doubled because alembic.ini values support %(name)s placeholders
    config.set_main_option("sqlalchemy.url", Config.SQLALCHEMY_DATABASE_URI.replace("%", "%%"))


def run_migrations_offline() -> None:
    """Write the migration SQL to the screen instead of running it (alembic upgrade --sql)."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Connect to the database and run the migrations."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
