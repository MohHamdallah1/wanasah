"""Make refresh-token rotation concurrency-safe.

Revision ID: 8b7d2c4e9f61
Revises: 12f4a8c7d9e3
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


revision = "8b7d2c4e9f61"
down_revision = "12f4a8c7d9e3"
branch_labels = None
depends_on = None

FK_NAME = "fk_refresh_tokens_replaced_by_id_refresh_tokens"
INDEX_NAME = "uq_refresh_tokens_replaced_by_id"


def _assert_ddl_role() -> None:
    bind = op.get_bind()
    row = bind.execute(
        text(
            """
            SELECT
                current_user AS current_user,
                owner.rolname AS table_owner,
                current_setting('is_superuser') = 'on'
                    AS is_superuser
            FROM pg_class AS rel
            JOIN pg_namespace AS ns
              ON ns.oid = rel.relnamespace
            JOIN pg_roles AS owner
              ON owner.oid = rel.relowner
            WHERE ns.nspname = 'public'
              AND rel.relname = 'refresh_tokens'
              AND rel.relkind = 'r'
            """
        )
    ).mappings().one()

    if (
        str(row["current_user"]) != str(row["table_owner"])
        and not bool(row["is_superuser"])
    ):
        raise RuntimeError(
            "Migration requires the refresh_tokens table owner "
            "or a superuser. Use DATABASE_URL_MIGRATION."
        )


def upgrade() -> None:
    _assert_ddl_role()

    op.add_column(
        "refresh_tokens",
        sa.Column("replaced_by_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        FK_NAME,
        "refresh_tokens",
        "refresh_tokens",
        ["replaced_by_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        INDEX_NAME,
        "refresh_tokens",
        ["replaced_by_id"],
        unique=True,
    )


def downgrade() -> None:
    _assert_ddl_role()

    op.drop_index(INDEX_NAME, table_name="refresh_tokens")
    op.drop_constraint(
        FK_NAME,
        "refresh_tokens",
        type_="foreignkey",
    )
    op.drop_column("refresh_tokens", "replaced_by_id")
