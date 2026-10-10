import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
import sys
import os
from dotenv import load_dotenv

# Load .env variables so Alembic can read DATABASE_URL
load_dotenv()

sys.path.append(os.getcwd())

# استيراد الـ Base وكل الجداول لكي يكتشفها Alembic
from models import Base # إذا كان الـ Base معرف في database.py، غيرها لـ from database import Base
from models import * # استيراد إجباري لكل الجداول لتفعيل الرادار
from domains.offers import models as offer_models  # noqa: F401
from domains.taxation import models as taxation_models  # noqa: F401
from domains.sales_evidence import models as sales_evidence_models  # noqa: F401
from domains.sales_returns import models as sales_return_models  # noqa: F401
from domains.suppliers import models as supplier_models  # noqa: F401
from domains.identity import models as identity_models  # noqa: F401
from domains import inventory_supplier_evidence  # noqa: F401

target_metadata = Base.metadata

# Objects intentionally owned by SQL migrations or external libraries rather
# than SQLAlchemy metadata. Autogenerate must not propose destructive drops.
MIGRATION_MANAGED_TABLES = {
    "product_import_worker_registry",
    "product_import_schedule_candidates",
}
MIGRATION_MANAGED_INDEXES = {
    "ix_inventory_cost_event_purchase_latest",
    "ix_product_barcodes_company_active_barcode_trgm",
    "ix_product_import_job_orphan_recovery",
    "ix_product_variants_company_search_trgm",
    "ix_product_variant_simple_common_filters_seek",
    "ix_products_company_name_trgm",
    "ix_product_company_lower_name_id",
    "ix_shops_company_tax_jurisdiction",
}


def include_object(obj, name, type_, reflected, compare_to):
    table = getattr(obj, "table", None)
    table_name = getattr(table, "name", None)
    if type_ == "table" and (
        name.startswith("procrastinate_") or name in MIGRATION_MANAGED_TABLES
    ):
        return False
    if type_ == "index" and (
        (table_name and table_name.startswith("procrastinate_"))
        or table_name in MIGRATION_MANAGED_TABLES
        or name in MIGRATION_MANAGED_INDEXES
    ):
        return False
    return True


# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Dynamic override from .env — Alembic MUST run as the superuser (DATABASE_URL_MIGRATION)
# because it creates roles, grants privileges, and manages RLS policies that a
# restricted app user is not allowed to execute. Falls back to DATABASE_URL only
# when the migration URL is absent (e.g., legacy local setups).
db_url = os.getenv("DATABASE_URL_MIGRATION") or os.getenv("DATABASE_URL")
if db_url:
    # +++ درع السحاب: ضمان توافق البروتوكول مع asyncpg مهما كان صيغ الرابط +++
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
    if db_url.startswith("postgresql://") and "asyncpg" not in db_url:
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    config.set_main_option("sqlalchemy.url", db_url)

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
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


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """In this scenario we need to create an Engine
    and associate a connection with the context.

    """

    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""

    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
