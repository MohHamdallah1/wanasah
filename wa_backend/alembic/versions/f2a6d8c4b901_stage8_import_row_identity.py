"""Stage 8 Product Import immutable row identity.

Revision ID: f2a6d8c4b901
Revises: e8b4c1d7a6f2
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "f2a6d8c4b901"
down_revision = "e8b4c1d7a6f2"
branch_labels = None
depends_on = None

_TABLE = "product_import_rows"
_UNIQUE = "uq_product_import_row_job_identity"
_TRIGGER = "trg_product_import_row_identity_immutable"
_FUNCTION = "enforce_product_import_row_identity_immutable"


def upgrade() -> None:
    op.add_column(
        _TABLE,
        sa.Column(
            "row_identity",
            sa.Uuid(),
            nullable=True,
        ),
    )

    op.execute(
        f"""
        UPDATE {_TABLE}
        SET row_identity = gen_random_uuid()
        WHERE row_identity IS NULL
        """
    )

    op.alter_column(
        _TABLE,
        "row_identity",
        nullable=False,
        server_default=sa.text(
            "gen_random_uuid()"
        ),
    )

    op.create_unique_constraint(
        _UNIQUE,
        _TABLE,
        [
            "company_id",
            "job_id",
            "row_identity",
        ],
    )

    op.execute(
        f"""
        CREATE FUNCTION {_FUNCTION}()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.row_identity IS DISTINCT FROM OLD.row_identity THEN
                RAISE EXCEPTION
                    'Product Import row identity is immutable'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER {_TRIGGER}
        BEFORE UPDATE OF row_identity
        ON {_TABLE}
        FOR EACH ROW
        EXECUTE FUNCTION {_FUNCTION}()
        """
    )


def downgrade() -> None:
    op.execute(
        f"DROP TRIGGER IF EXISTS {_TRIGGER} ON {_TABLE}"
    )
    op.execute(
        f"DROP FUNCTION IF EXISTS {_FUNCTION}()"
    )
    op.drop_constraint(
        _UNIQUE,
        _TABLE,
        type_="unique",
    )
    op.drop_column(
        _TABLE,
        "row_identity",
    )
