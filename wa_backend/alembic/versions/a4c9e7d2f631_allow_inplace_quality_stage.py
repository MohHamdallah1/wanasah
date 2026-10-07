"""Allow tightly-scoped in-place whole-product quality staging.

Revision ID: a4c9e7d2f631
Revises: e31f6c2a9d74
"""
from alembic import op

revision = "a4c9e7d2f631"
down_revision = "e31f6c2a9d74"
branch_labels = None
depends_on = None

_TABLE = "inventory_transfer_headers"
_CONSTRAINT = "ck_inventory_transfer_headers_chk_transfer_header_disti_e7f1"
_INPLACE_QUALITY_CHECK = """
(
    source_location_id <> destination_location_id
    OR (
        workflow_type = 'DIRECT'
        AND status = 'POSTED'
        AND transfer_purpose IN ('DISPOSAL','RETURN_TO_VENDOR')
        AND transit_location_id IS NULL
        AND reference_number LIKE 'QSTG-%'
        AND tenant_policy_id IS NOT NULL
        AND tenant_policy_revision IS NOT NULL
        AND commercial_context IS NOT NULL
        AND commercial_context ->> 'quality_stage_v1' = 'true'
    )
)
"""


def upgrade():
    # The repository metadata uses a naming convention for check constraints.
    # This is already the physical database name, so mark it fixed to prevent
    # Alembic from applying the convention a second time.
    fixed_name = op.f(_CONSTRAINT)
    op.drop_constraint(fixed_name, _TABLE, type_="check")
    op.create_check_constraint(fixed_name, _TABLE, _INPLACE_QUALITY_CHECK)


def downgrade():
    # Never destroy immutable quality evidence merely to make a downgrade possible.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM inventory_transfer_headers
                WHERE source_location_id = destination_location_id
            ) THEN
                RAISE EXCEPTION
                    'Cannot downgrade: in-place quality transfer evidence exists';
            END IF;
        END
        $$;
        """
    )
    fixed_name = op.f(_CONSTRAINT)
    op.drop_constraint(fixed_name, _TABLE, type_="check")
    op.create_check_constraint(
        fixed_name,
        _TABLE,
        "source_location_id <> destination_location_id",
    )
