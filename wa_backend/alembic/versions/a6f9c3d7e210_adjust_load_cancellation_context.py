"""Permanent idempotency cancellation state and Adjust Load context revision.

Revision ID: a6f9c3d7e210
Revises: e1b7c4d9a203
"""

from alembic import op
import sqlalchemy as sa

revision = "a6f9c3d7e210"
down_revision = "e1b7c4d9a203"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "operation_idempotency",
        sa.Column("state", sa.String(length=16), nullable=False, server_default="PENDING"),
    )
    op.add_column(
        "operation_idempotency",
        sa.Column("cancelled_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "operation_idempotency",
        sa.Column("cancelled_by", sa.Integer(), nullable=True),
    )
    op.execute(
        """
        UPDATE operation_idempotency
        SET state = CASE
            WHEN response_json IS NOT NULL AND completed_at IS NOT NULL
                THEN 'COMMITTED'
            ELSE 'PENDING'
        END
        """
    )
    op.create_foreign_key(
        "fk_operation_idempotency_tenant_canceller",
        "operation_idempotency",
        "drivers",
        ["company_id", "cancelled_by"],
        ["company_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "chk_operation_idempotency_state",
        "operation_idempotency",
        "state IN ('PENDING', 'COMMITTED', 'CANCELLED')",
    )
    op.create_check_constraint(
        "chk_operation_idempotency_lifecycle",
        "operation_idempotency",
        """
        (state = 'PENDING' AND response_json IS NULL AND completed_at IS NULL
            AND cancelled_at IS NULL AND cancelled_by IS NULL)
        OR
        (state = 'COMMITTED' AND response_json IS NOT NULL AND completed_at IS NOT NULL
            AND cancelled_at IS NULL AND cancelled_by IS NULL)
        OR
        (state = 'CANCELLED' AND response_json IS NULL AND completed_at IS NULL
            AND cancelled_at IS NOT NULL AND cancelled_by IS NOT NULL)
        """,
    )
    # CANCELLED is a permanent fence, not an application convention. Once the
    # row exists, even direct SQL cannot rewrite or prune it silently.
    op.execute(
        """
        CREATE FUNCTION guard_cancelled_operation_idempotency()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $
        BEGIN
            IF OLD.state = 'CANCELLED' THEN
                RAISE EXCEPTION 'CANCELLED idempotency fence is immutable'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_operation_idempotency_cancelled_immutable
        BEFORE UPDATE OR DELETE ON operation_idempotency
        FOR EACH ROW
        WHEN (OLD.state = 'CANCELLED')
        EXECUTE FUNCTION guard_cancelled_operation_idempotency()
        """
    )

    op.add_column(
        "dispatch_routes",
        sa.Column(
            "adjustment_context_revision",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )
    op.create_check_constraint(
        "chk_dispatch_route_adjustment_context_revision",
        "dispatch_routes",
        "adjustment_context_revision > 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        "chk_dispatch_route_adjustment_context_revision",
        "dispatch_routes",
        type_="check",
    )
    op.drop_column("dispatch_routes", "adjustment_context_revision")

    op.execute(
        "DROP TRIGGER IF EXISTS trg_operation_idempotency_cancelled_immutable "
        "ON operation_idempotency"
    )
    op.execute("DROP FUNCTION IF EXISTS guard_cancelled_operation_idempotency()")
    op.drop_constraint(
        "chk_operation_idempotency_lifecycle",
        "operation_idempotency",
        type_="check",
    )
    op.drop_constraint(
        "chk_operation_idempotency_state",
        "operation_idempotency",
        type_="check",
    )
    op.drop_constraint(
        "fk_operation_idempotency_tenant_canceller",
        "operation_idempotency",
        type_="foreignkey",
    )
    op.drop_column("operation_idempotency", "cancelled_by")
    op.drop_column("operation_idempotency", "cancelled_at")
    op.drop_column("operation_idempotency", "state")
