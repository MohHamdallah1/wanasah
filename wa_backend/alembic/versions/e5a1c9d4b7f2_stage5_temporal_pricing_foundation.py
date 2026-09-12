"""stage5 temporal pricing foundation

Revision ID: e5a1c9d4b7f2
Revises: b48467088c16
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "e5a1c9d4b7f2"
down_revision: Union[str, Sequence[str], None] = "b48467088c16"
branch_labels = None
depends_on = None


_TENANT_TABLES = (
    "price_books",
    "price_publications",
    "price_book_entries",
    "price_book_assignments",
    "route_commercial_contexts",
)


def _enable_rls(table_name: str) -> None:
    op.execute(f'ALTER TABLE "{table_name}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{table_name}" FORCE ROW LEVEL SECURITY')
    op.execute(
        f"""
        CREATE POLICY {table_name}_company_isolation
        ON "{table_name}"
        USING (
            company_id = NULLIF(
                current_setting('app.current_tenant', true),
                ''
            )::integer
        )
        WITH CHECK (
            company_id = NULLIF(
                current_setting('app.current_tenant', true),
                ''
            )::integer
        )
        """
    )


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    op.create_table(
        "price_books",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("currency_code", sa.String(length=10), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="ACTIVE", nullable=False),
        sa.Column(
            "applicability_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("length(trim(code)) > 0", name="chk_price_book_code_not_blank"),
        sa.CheckConstraint("length(trim(name)) > 0", name="chk_price_book_name_not_blank"),
        sa.CheckConstraint("length(trim(currency_code)) > 0", name="chk_price_book_currency_not_blank"),
        sa.CheckConstraint("status IN ('ACTIVE', 'ARCHIVED')", name="chk_price_book_status"),
        sa.CheckConstraint("version > 0", name="chk_price_book_version"),
        sa.CheckConstraint("jsonb_typeof(applicability_metadata) = 'object'", name="chk_price_book_applicability_object"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE", name="fk_price_book_company"),
        sa.ForeignKeyConstraint(["company_id", "created_by"], ["drivers.company_id", "drivers.id"], ondelete="RESTRICT", name="fk_price_book_tenant_creator"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "id", name="uq_price_books_company_id"),
        sa.UniqueConstraint("company_id", "code", name="uq_price_book_company_code"),
    )
    op.create_index("ix_price_book_company_status", "price_books", ["company_id", "status", "id"], unique=False)

    op.create_table(
        "price_publications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("price_book_id", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), server_default="DRAFT", nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("approved_by", sa.Integer(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("revision > 0", name="chk_price_publication_revision"),
        sa.CheckConstraint("status IN ('DRAFT','PENDING_APPROVAL','PUBLISHED','SUPERSEDED','CANCELLED')", name="chk_price_publication_status"),
        sa.CheckConstraint("version > 0", name="chk_price_publication_version"),
        sa.CheckConstraint(
            "status NOT IN ('PUBLISHED','SUPERSEDED') OR "
            "(effective_at IS NOT NULL AND approved_by IS NOT NULL AND approved_at IS NOT NULL AND published_at IS NOT NULL)",
            name="chk_price_publication_published_metadata",
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE", name="fk_price_publication_company"),
        sa.ForeignKeyConstraint(["company_id", "price_book_id"], ["price_books.company_id", "price_books.id"], ondelete="RESTRICT", name="fk_price_publication_tenant_book"),
        sa.ForeignKeyConstraint(["company_id", "created_by"], ["drivers.company_id", "drivers.id"], ondelete="RESTRICT", name="fk_price_publication_tenant_creator"),
        sa.ForeignKeyConstraint(["company_id", "approved_by"], ["drivers.company_id", "drivers.id"], ondelete="RESTRICT", name="fk_price_publication_tenant_approver"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "id", name="uq_price_publications_company_id"),
        sa.UniqueConstraint("company_id", "id", "price_book_id", name="uq_price_publication_company_id_book"),
        sa.UniqueConstraint("company_id", "revision", name="uq_price_publication_company_revision"),
        sa.UniqueConstraint("company_id", "request_id", name="uq_price_publication_company_request"),
    )
    op.create_index(
        "ix_price_publication_resolver",
        "price_publications",
        ["company_id", "price_book_id", "status", "revision", "effective_at"],
        unique=False,
    )

    op.create_table(
        "price_book_entries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("price_book_id", sa.Integer(), nullable=False),
        sa.Column("publication_id", sa.Integer(), nullable=False),
        sa.Column("product_variant_id", sa.Integer(), nullable=False),
        sa.Column("uom_id", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(20, 6), nullable=False),
        sa.Column("effectivity", postgresql.TSTZRANGE(), nullable=False),
        sa.Column("priority", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_published", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("amount >= 0", name="chk_price_book_entry_amount"),
        sa.CheckConstraint("priority >= 0", name="chk_price_book_entry_priority"),
        sa.CheckConstraint("version > 0", name="chk_price_book_entry_version"),
        sa.CheckConstraint(
            "NOT isempty(effectivity) AND lower(effectivity) IS NOT NULL AND lower_inc(effectivity) AND NOT upper_inc(effectivity)",
            name="chk_price_book_entry_effectivity_half_open",
        ),
        sa.CheckConstraint("jsonb_typeof(metadata) = 'object'", name="chk_price_book_entry_metadata_object"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE", name="fk_price_book_entry_company"),
        sa.ForeignKeyConstraint(["company_id", "price_book_id"], ["price_books.company_id", "price_books.id"], ondelete="RESTRICT", name="fk_price_book_entry_tenant_book"),
        sa.ForeignKeyConstraint(
            ["company_id", "publication_id", "price_book_id"],
            ["price_publications.company_id", "price_publications.id", "price_publications.price_book_id"],
            ondelete="RESTRICT",
            name="fk_price_book_entry_tenant_publication_book",
        ),
        sa.ForeignKeyConstraint(["company_id", "product_variant_id"], ["product_variants.company_id", "product_variants.id"], ondelete="RESTRICT", name="fk_price_book_entry_tenant_variant"),
        sa.ForeignKeyConstraint(["uom_id"], ["uom.id"], ondelete="RESTRICT", name="fk_price_book_entry_uom"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "id", name="uq_price_book_entries_company_id"),
        postgresql.ExcludeConstraint(
            ("company_id", "="),
            ("price_book_id", "="),
            ("product_variant_id", "="),
            ("uom_id", "="),
            ("effectivity", "&&"),
            where=sa.text("is_published IS TRUE"),
            using="gist",
            name="excl_price_book_entry_published_overlap",
        ),
    )
    op.create_index(
        "ix_price_book_entry_resolver",
        "price_book_entries",
        ["company_id", "price_book_id", "product_variant_id", "uom_id", "is_published", "priority", "publication_id"],
        unique=False,
    )

    op.create_table(
        "price_book_assignments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("price_book_id", sa.Integer(), nullable=False),
        sa.Column("scope_type", sa.String(length=30), nullable=False),
        sa.Column("scope_id", sa.Integer(), nullable=True),
        sa.Column(
            "customer_scope_id",
            sa.Integer(),
            sa.Computed("CASE WHEN scope_type = 'CUSTOMER' THEN scope_id ELSE NULL END", persisted=True),
            nullable=True,
        ),
        sa.Column(
            "branch_scope_id",
            sa.Integer(),
            sa.Computed("CASE WHEN scope_type = 'BRANCH' THEN scope_id ELSE NULL END", persisted=True),
            nullable=True,
        ),
        sa.Column(
            "scope_identity",
            sa.Integer(),
            sa.Computed("COALESCE(scope_id, 0)", persisted=True),
            nullable=False,
        ),
        sa.Column("priority", sa.Integer(), server_default="0", nullable=False),
        sa.Column("effectivity", postgresql.TSTZRANGE(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("scope_type IN ('CUSTOMER','BRANCH','COMPANY_DEFAULT')", name="chk_price_book_assignment_scope_type"),
        sa.CheckConstraint(
            "((scope_type IN ('CUSTOMER','BRANCH') AND scope_id IS NOT NULL AND scope_id > 0) "
            "OR (scope_type = 'COMPANY_DEFAULT' AND scope_id IS NULL))",
            name="chk_price_book_assignment_scope_id",
        ),
        sa.CheckConstraint("priority >= 0", name="chk_price_book_assignment_priority"),
        sa.CheckConstraint("revision > 0", name="chk_price_book_assignment_revision"),
        sa.CheckConstraint("version > 0", name="chk_price_book_assignment_version"),
        sa.CheckConstraint(
            "NOT isempty(effectivity) AND lower(effectivity) IS NOT NULL AND lower_inc(effectivity) AND NOT upper_inc(effectivity)",
            name="chk_price_book_assignment_effectivity_half_open",
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE", name="fk_price_book_assignment_company"),
        sa.ForeignKeyConstraint(["company_id", "price_book_id"], ["price_books.company_id", "price_books.id"], ondelete="RESTRICT", name="fk_price_book_assignment_tenant_book"),
        sa.ForeignKeyConstraint(["company_id", "customer_scope_id"], ["shops.company_id", "shops.id"], ondelete="RESTRICT", name="fk_price_book_assignment_tenant_customer"),
        sa.ForeignKeyConstraint(["company_id", "branch_scope_id"], ["branches.company_id", "branches.id"], ondelete="RESTRICT", name="fk_price_book_assignment_tenant_branch"),
        sa.ForeignKeyConstraint(["company_id", "created_by"], ["drivers.company_id", "drivers.id"], ondelete="RESTRICT", name="fk_price_book_assignment_tenant_creator"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "id", name="uq_price_book_assignments_company_id"),
        sa.UniqueConstraint("company_id", "revision", name="uq_price_book_assignment_company_revision"),
        postgresql.ExcludeConstraint(
            ("company_id", "="),
            ("scope_type", "="),
            ("scope_identity", "="),
            ("priority", "="),
            ("effectivity", "&&"),
            using="gist",
            name="excl_price_book_assignment_equal_priority_overlap",
        ),
    )
    op.create_index(
        "ix_price_book_assignment_resolver",
        "price_book_assignments",
        ["company_id", "scope_type", "scope_identity", "priority", "revision"],
        unique=False,
    )

    op.create_table(
        "route_commercial_contexts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("dispatch_route_id", sa.Integer(), nullable=False),
        sa.Column("pricing_locked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("price_publication_revision", sa.Integer(), nullable=False),
        sa.Column("assignment_revision", sa.Integer(), nullable=False),
        sa.Column("offer_ruleset_version", sa.Integer(), nullable=True),
        sa.Column("tax_ruleset_version", sa.Integer(), nullable=True),
        sa.Column("transaction_currency_code", sa.String(length=10), nullable=False),
        sa.Column("functional_currency_code", sa.String(length=10), nullable=False),
        sa.Column("rounding_policy_version", sa.Integer(), nullable=True),
        sa.Column("tenant_policy_revision", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("price_publication_revision > 0", name="chk_route_commercial_context_price_revision"),
        sa.CheckConstraint("assignment_revision > 0", name="chk_route_commercial_context_assignment_revision"),
        sa.CheckConstraint("length(trim(transaction_currency_code)) > 0", name="chk_route_commercial_context_transaction_currency"),
        sa.CheckConstraint("length(trim(functional_currency_code)) > 0", name="chk_route_commercial_context_functional_currency"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE", name="fk_route_commercial_context_company"),
        sa.ForeignKeyConstraint(["company_id", "dispatch_route_id"], ["dispatch_routes.company_id", "dispatch_routes.id"], ondelete="RESTRICT", name="fk_route_commercial_context_tenant_route"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "id", name="uq_route_commercial_contexts_company_id"),
        sa.UniqueConstraint("company_id", "dispatch_route_id", name="uq_route_commercial_context_route"),
    )
    op.create_index(
        "ix_route_commercial_context_lock",
        "route_commercial_contexts",
        ["company_id", "pricing_locked_at", "price_publication_revision", "assignment_revision"],
        unique=False,
    )

    op.execute(
        "INSERT INTO permissions (code) VALUES "
        "('pricing.read'),"
        "('pricing.manage'),"
        "('pricing.publish'),"
        "('pricing.assign') "
        "ON CONFLICT (code) DO NOTHING"
    )

    for table_name in _TENANT_TABLES:
        _enable_rls(table_name)

    op.execute(
        """
        CREATE OR REPLACE FUNCTION reject_route_commercial_context_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION
                'route_commercial_contexts is immutable after creation'
                USING ERRCODE = '55000';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_route_commercial_context_immutable
        BEFORE UPDATE OR DELETE ON route_commercial_contexts
        FOR EACH ROW EXECUTE FUNCTION reject_route_commercial_context_mutation()
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM route_commercial_contexts LIMIT 1)
               OR EXISTS (SELECT 1 FROM price_book_assignments LIMIT 1)
               OR EXISTS (SELECT 1 FROM price_book_entries LIMIT 1)
               OR EXISTS (SELECT 1 FROM price_publications LIMIT 1)
               OR EXISTS (SELECT 1 FROM price_books LIMIT 1)
            THEN
                RAISE EXCEPTION
                    'Refusing destructive downgrade: Stage 5 pricing tables contain data';
            END IF;
        END
        $$;
        """
    )

    op.execute(
        "DROP TRIGGER IF EXISTS trg_route_commercial_context_immutable "
        "ON route_commercial_contexts"
    )
    op.execute("DROP FUNCTION IF EXISTS reject_route_commercial_context_mutation()")

    op.drop_table("route_commercial_contexts")
    op.drop_table("price_book_assignments")
    op.drop_table("price_book_entries")
    op.drop_table("price_publications")
    op.drop_table("price_books")
