"""Alembic environment.

All three schemas are in scope, so ``include_schemas`` is on and autogenerate
is told to ignore anything outside them - a stray table in ``public`` is not
ours to drop.
"""

from alembic import context
from sqlalchemy import engine_from_config, pool

# Importing the models is what registers them on Base.metadata.
import switchboard_core.db.knowledge
import switchboard_core.db.prose
from switchboard_core.db.base import KNOWLEDGE_SCHEMA, PROSE_SCHEMA, SOURCE_SCHEMA, Base
from switchboard_core.db.session import database_url

import switchboard_core.db.source  # noqa: F401  isort:skip

config = context.config
config.set_main_option("sqlalchemy.url", database_url())

target_metadata = Base.metadata

MANAGED_SCHEMAS = {SOURCE_SCHEMA, KNOWLEDGE_SCHEMA, PROSE_SCHEMA}


def include_name(name: str | None, type_: str, _parent: object) -> bool:
    if type_ == "schema":
        return name in MANAGED_SCHEMAS
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        include_schemas=True,
        include_name=include_name,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=True,
            include_name=include_name,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
