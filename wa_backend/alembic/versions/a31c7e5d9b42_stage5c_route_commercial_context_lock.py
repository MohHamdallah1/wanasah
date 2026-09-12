"""stage5c route commercial context lock

Revision ID: a31c7e5d9b42
Revises: f2a9c4e7d1b6
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a31c7e5d9b42"
down_revision: Union[str, Sequence[str], None] = "f2a9c4e7d1b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "work_sessions",
        sa.Column("commercial_context_id", sa.Integer(), nullable=True),
    )
    op.create_unique_constraint(
        "uq_work_sessions_commercial_context",
        "work_sessions",
        ["company_id", "commercial_context_id"],
    )
    op.create_foreign_key(
        "fk_work_session_tenant_commercial_context",
        "work_sessions",
        "route_commercial_contexts",
        ["company_id", "commercial_context_id"],
        ["company_id", "id"],
        ondelete="RESTRICT",
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION guard_work_session_commercial_context()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.commercial_context_id IS DISTINCT FROM OLD.commercial_context_id
            THEN
                RAISE EXCEPTION
                    'work session commercial context is immutable after creation'
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_work_session_commercial_context_immutable
        BEFORE UPDATE ON work_sessions
        FOR EACH ROW
        EXECUTE FUNCTION guard_work_session_commercial_context()
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM work_sessions
                WHERE commercial_context_id IS NOT NULL
                LIMIT 1
            )
            THEN
                RAISE EXCEPTION
                    'Refusing Stage5C downgrade: WorkSession commercial evidence exists';
            END IF;
        END
        $$;
        """
    )

    op.execute(
        "DROP TRIGGER IF EXISTS "
        "trg_work_session_commercial_context_immutable ON work_sessions"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS guard_work_session_commercial_context()"
    )
    op.drop_constraint(
        "fk_work_session_tenant_commercial_context",
        "work_sessions",
        type_="foreignkey",
    )
    op.drop_constraint(
        "uq_work_sessions_commercial_context",
        "work_sessions",
        type_="unique",
    )
    op.drop_column("work_sessions", "commercial_context_id")
