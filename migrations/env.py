import sys
from pathlib import Path

# Ensure src/ is on path so `oki` is importable when running alembic directly
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from asyncio import run
from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection, pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from oki.config import Settings
from oki.db.base import Base

# Import all models so Base.metadata is populated for autogenerate
from oki.ads import models as _ads_models  # noqa: F401
from oki.analysis import models as _analysis_models  # noqa: F401
from oki.assets import models as _assets_models  # noqa: F401
from oki.campaigns import models as _campaigns_models  # noqa: F401
from oki.dubbing import models as _dubbing_models  # noqa: F401
from oki.finance import models as _finance_models  # noqa: F401
from oki.jobs import models as _jobs_models  # noqa: F401
from oki.renders import models as _renders_models  # noqa: F401
from oki.reviews import models as _reviews_models  # noqa: F401
from oki.shorts import models as _shorts_models  # noqa: F401
from oki.voices import models as _voices_models  # noqa: F401
from oki.translations import models as _translations_models  # noqa: F401
from oki.publications import models as _publications_models  # noqa: F401
from oki.youtube import models as _youtube_models  # noqa: F401
from oki.analytics import models as _analytics_models  # noqa: F401
from oki.sponsors import models as _sponsors_models  # noqa: F401
from oki.creators import models as _creators_models  # noqa: F401

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", Settings().database_url.replace("%", "%%"))
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run(run_async_migrations())
