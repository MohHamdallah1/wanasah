"""stage6h1 commercial authority lock

Revision ID: 91e6b4c8d2f0
Revises: 8d4c6a2f1b90
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "91e6b4c8d2f0"
down_revision: Union[str, Sequence[str], None] = "8d4c6a2f1b90"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Tax jurisdiction is explicit commercial authority; never infer it from
    # address/zone/country. It remains nullable on Shop setup, while sale runtime
    # will fail closed until a valid jurisdiction is assigned.
    op.add_column(
        "shops",
        sa.Column("tax_jurisdiction_id", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_shops_company_tax_jurisdiction",
        "shops",
        ["company_id", "tax_jurisdiction_id"],
    )
    op.create_foreign_key(
        "fk_shop_tenant_tax_jurisdiction",
        "shops",
        "tax_jurisdictions",
        ["company_id", "tax_jurisdiction_id"],
        ["company_id", "id"],
        ondelete="RESTRICT",
    )

    # Never invent revision values for an old incomplete context. The dev DB is
    # disposable; fail explicitly so stale route data is reset rather than
    # silently backfilled with authorities that were never actually locked.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM route_commercial_contexts
                WHERE offer_ruleset_version IS NULL
                   OR tax_ruleset_version IS NULL
                   OR rounding_policy_version IS NULL
                   OR tenant_policy_revision IS NULL
            ) THEN
                RAISE EXCEPTION
                    'Stage 6H.1 refuses to backfill incomplete RouteCommercialContext rows';
            END IF;
        END
        $$;
        """
    )

    for column_name in (
        "offer_ruleset_version",
        "tax_ruleset_version",
        "rounding_policy_version",
        "tenant_policy_revision",
    ):
        op.alter_column(
            "route_commercial_contexts",
            column_name,
            existing_type=sa.Integer(),
            nullable=False,
        )

    op.create_check_constraint(
        "chk_route_commercial_context_offer_revision",
        "route_commercial_contexts",
        "offer_ruleset_version >= 0",
    )
    op.create_check_constraint(
        "chk_route_commercial_context_tax_revision",
        "route_commercial_contexts",
        "tax_ruleset_version > 0",
    )
    op.create_check_constraint(
        "chk_route_commercial_context_rounding_version",
        "route_commercial_contexts",
        "rounding_policy_version > 0",
    )
    op.create_check_constraint(
        "chk_route_commercial_context_tenant_policy_revision",
        "route_commercial_contexts",
        "tenant_policy_revision > 0",
    )

    # Typed DB contract for the one commercial rounding policy code.
    op.create_check_constraint(
        "chk_tenant_policy_commercial_rounding_payload",
        "tenant_operational_policies",
        """
        policy_code <> 'COMMERCIAL_ROUNDING'
        OR (
            schema_version = 1
            AND validated_payload ? 'currency_code'
            AND validated_payload ? 'precision'
            AND validated_payload ? 'mode'
            AND validated_payload - 'currency_code' - 'precision' - 'mode' = '{}'::jsonb
            AND jsonb_typeof(validated_payload->'currency_code') = 'string'
            AND (validated_payload->>'currency_code') ~ '^[A-Z][A-Z0-9]{2,9}$'
            AND jsonb_typeof(validated_payload->'precision') = 'number'
            AND (validated_payload->>'precision') ~ '^[0-6]$'
            AND jsonb_typeof(validated_payload->'mode') = 'string'
            AND (validated_payload->>'mode') IN ('HALF_UP','HALF_EVEN')
        )
        """,
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION guard_commercial_rounding_policy()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                IF OLD.policy_code = 'COMMERCIAL_ROUNDING'
                   AND OLD.status IN ('PUBLISHED', 'SUPERSEDED') THEN
                    RAISE EXCEPTION
                        'published commercial rounding policy is immutable';
                END IF;
                RETURN OLD;
            END IF;

            IF OLD.policy_code = 'COMMERCIAL_ROUNDING'
               AND OLD.status = 'SUPERSEDED' THEN
                RAISE EXCEPTION
                    'superseded commercial rounding policy is immutable';
            END IF;

            IF OLD.policy_code = 'COMMERCIAL_ROUNDING'
               AND OLD.status = 'PUBLISHED' THEN
                IF NEW.status <> 'SUPERSEDED'
                   OR NEW.company_id IS DISTINCT FROM OLD.company_id
                   OR NEW.policy_code IS DISTINCT FROM OLD.policy_code
                   OR NEW.schema_version IS DISTINCT FROM OLD.schema_version
                   OR NEW.revision IS DISTINCT FROM OLD.revision
                   OR NEW.validated_payload IS DISTINCT FROM OLD.validated_payload
                   OR NEW.effective_from IS DISTINCT FROM OLD.effective_from
                   OR NEW.approved_by IS DISTINCT FROM OLD.approved_by
                   OR NEW.approved_at IS DISTINCT FROM OLD.approved_at
                   OR NEW.created_by IS DISTINCT FROM OLD.created_by
                   OR NEW.created_at IS DISTINCT FROM OLD.created_at
                   OR NEW.effective_to IS NULL
                   OR NEW.effective_to < OLD.effective_from THEN
                    RAISE EXCEPTION
                        'published commercial rounding policy can only be superseded immutably';
                END IF;
            END IF;

            RETURN NEW;
        END
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_guard_commercial_rounding_policy
        BEFORE UPDATE OR DELETE ON tenant_operational_policies
        FOR EACH ROW
        EXECUTE FUNCTION guard_commercial_rounding_policy()
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_guard_commercial_rounding_policy "
        "ON tenant_operational_policies"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS guard_commercial_rounding_policy()"
    )
    op.drop_constraint(
        "chk_tenant_policy_commercial_rounding_payload",
        "tenant_operational_policies",
        type_="check",
    )

    for constraint_name in (
        "chk_route_commercial_context_tenant_policy_revision",
        "chk_route_commercial_context_rounding_version",
        "chk_route_commercial_context_tax_revision",
        "chk_route_commercial_context_offer_revision",
    ):
        op.drop_constraint(
            constraint_name,
            "route_commercial_contexts",
            type_="check",
        )

    for column_name in (
        "tenant_policy_revision",
        "rounding_policy_version",
        "tax_ruleset_version",
        "offer_ruleset_version",
    ):
        op.alter_column(
            "route_commercial_contexts",
            column_name,
            existing_type=sa.Integer(),
            nullable=True,
        )

    op.drop_constraint(
        "fk_shop_tenant_tax_jurisdiction",
        "shops",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_shops_company_tax_jurisdiction",
        table_name="shops",
    )
    op.drop_column("shops", "tax_jurisdiction_id")
