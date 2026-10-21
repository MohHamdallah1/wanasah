"""Expand scoped in-place quality staging to all CP8 quality purposes.

Revision ID: e6b4c2d9a731
Revises: d7a4c9e21b30
"""
from alembic import op

revision = "e6b4c2d9a731"
down_revision = "d7a4c9e21b30"
branch_labels = None
depends_on = None

_TABLE = "inventory_transfer_headers"
_CONSTRAINT = "ck_inventory_transfer_headers_chk_transfer_header_disti_e7f1"

_CURRENT_CHECK = """
(
    source_location_id <> destination_location_id
    OR (
        workflow_type = 'DIRECT'
        AND status = 'POSTED'
        AND transfer_purpose IN ('QUARANTINE','RECALL_RETURN','DISPOSAL','RETURN_TO_VENDOR')
        AND transit_location_id IS NULL
        AND reference_number LIKE 'QSTG-%'
        AND tenant_policy_id IS NOT NULL
        AND tenant_policy_revision IS NOT NULL
        AND commercial_context IS NOT NULL
        AND commercial_context ->> 'quality_stage_v1' = 'true'
    )
)
"""

_PRIOR_CHECK = """
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


def upgrade() -> None:
    fixed_name = op.f(_CONSTRAINT)
    op.drop_constraint(fixed_name, _TABLE, type_="check")
    op.create_check_constraint(fixed_name, _TABLE, _CURRENT_CHECK)


def downgrade() -> None:
    # Preserve immutable evidence rather than making older code silently accept
    # a database shape that cannot represent same-location quarantine/recall.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM inventory_transfer_headers
                WHERE source_location_id = destination_location_id
                  AND transfer_purpose IN ('QUARANTINE','RECALL_RETURN')
            ) THEN
                RAISE EXCEPTION
                    'Cannot downgrade: in-place quarantine/recall quality evidence exists';
            END IF;
        END
        $$;
        """
    )
    fixed_name = op.f(_CONSTRAINT)
    op.drop_constraint(fixed_name, _TABLE, type_="check")
    op.create_check_constraint(fixed_name, _TABLE, _PRIOR_CHECK)
