"""Freeze company functional currency after provisioning; preserve historical costs.

Revision ID: c7f3a8e5d912
Revises: b9c5e18a0f42

The new trigger does not rewrite any existing company or accounting row.
"""

from alembic import op

revision = "c7f3a8e5d912"
down_revision = "b9c5e18a0f42"
branch_labels = None
depends_on = None

_FUNCTION = "public.wanasah_guard_company_currency_immutable_v1"
_TRIGGER = "trg_companies_currency_immutable_v1"


def upgrade() -> None:
    op.execute("""
        CREATE FUNCTION public.wanasah_guard_company_currency_immutable_v1()
        RETURNS trigger LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $guard$
        BEGIN
            IF NEW.currency_code IS DISTINCT FROM OLD.currency_code THEN
                RAISE EXCEPTION 'COMPANY_CURRENCY_IMMUTABLE'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END
        $guard$
    """)
    op.execute("""
        CREATE TRIGGER trg_companies_currency_immutable_v1
        BEFORE UPDATE OF currency_code ON public.companies
        FOR EACH ROW EXECUTE FUNCTION
        public.wanasah_guard_company_currency_immutable_v1()
    """)


def downgrade() -> None:
    # Once a company exists the irreversible currency contract must not be
    # silently weakened by an automated downgrade.
    op.execute("""
        DO $guard$
        BEGIN
          IF EXISTS (SELECT 1 FROM public.companies) THEN
             RAISE EXCEPTION 'COMPANY_CURRENCY_GUARD_DOWNGRADE_REFUSED_WITH_COMPANIES';
          END IF;
        END
        $guard$
    """)
    op.execute("DROP TRIGGER trg_companies_currency_immutable_v1 ON public.companies")
    op.execute("DROP FUNCTION public.wanasah_guard_company_currency_immutable_v1()")
