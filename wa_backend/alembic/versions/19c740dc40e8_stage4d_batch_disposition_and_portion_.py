"""stage4d batch disposition and portion statuses

Revision ID: 19c740dc40e8
Revises: c3f4e5a6b7d8
"""

from typing import Sequence, Union

from alembic import op


revision: str = "19c740dc40e8"
down_revision: Union[str, Sequence[str], None] = "c3f4e5a6b7d8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # لا نصحح أي بيانات بصمت. إذا وجدت Reservation في Bucket غير AVAILABLE
    # فهذا فساد يجب كشفه قبل فرض القيد الجديد.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM inventory_balances
                WHERE stock_status <> 'AVAILABLE'
                  AND reserved_quantity <> 0
            ) THEN
                RAISE EXCEPTION
                    'Stage4D invariant violation: non-AVAILABLE balance has reserved quantity';
            END IF;
        END
        $$;
        """
    )

    op.drop_constraint(
        "chk_inv_bal_damaged_not_reserved",
        "inventory_balances",
        type_="check",
    )
    op.create_check_constraint(
        "chk_inv_bal_nonavailable_not_reserved",
        "inventory_balances",
        "stock_status = 'AVAILABLE' OR reserved_quantity = 0",
    )

    # Permission catalog عالمي؛ Admin الحالي يبقى bypass كامل،
    # والمستخدم المحدود لا يحصل على شيء حتى يُمنح Role صريحاً.
    op.execute(
        """
        INSERT INTO permissions (code)
        VALUES ('batch.disposition'), ('inventory.status_change')
        ON CONFLICT (code) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM permissions
        WHERE code IN ('batch.disposition', 'inventory.status_change')
        """
    )

    op.drop_constraint(
        "chk_inv_bal_nonavailable_not_reserved",
        "inventory_balances",
        type_="check",
    )
    op.create_check_constraint(
        "chk_inv_bal_damaged_not_reserved",
        "inventory_balances",
        "stock_status <> 'DAMAGED' OR reserved_quantity = 0",
    )
