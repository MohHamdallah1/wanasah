"""Supplier Master identity and Inventory-owned immutable supplier evidence.

Revision ID: b7f2a9c4d681
Revises: b8e4d7a91c52
Legacy movements remain untouched: absent evidence means unknown supplier.
"""
import os
import re
from alembic import op
from sqlalchemy.engine import make_url

revision = "b7f2a9c4d681"
down_revision = "b8e4d7a91c52"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("""
        CREATE TABLE suppliers (
            id SERIAL CONSTRAINT pk_suppliers PRIMARY KEY,
            company_id INTEGER NOT NULL CONSTRAINT fk_suppliers_company_id_companies REFERENCES companies(id) ON DELETE RESTRICT,
            name VARCHAR(300) NOT NULL,
            code VARCHAR(50), contact_person VARCHAR(150), phone VARCHAR(50),
            email VARCHAR(254), address VARCHAR(1000), notes VARCHAR(4000),
            is_active BOOLEAN NOT NULL DEFAULT true,
            version INTEGER NOT NULL DEFAULT 1,
            created_by INTEGER NOT NULL, updated_by INTEGER NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            search_text VARCHAR GENERATED ALWAYS AS (
                lower(name || ' ' || coalesce(code, '') || ' ' || coalesce(contact_person, '')
                      || ' ' || coalesce(phone, '') || ' ' || coalesce(email, ''))
            ) STORED,
            CONSTRAINT uq_suppliers_company_id UNIQUE (company_id, id),
            CONSTRAINT uq_suppliers_company_code UNIQUE (company_id, code),
            CONSTRAINT ck_suppliers_supplier_name_not_blank CHECK (length(trim(name)) > 0),
            CONSTRAINT ck_suppliers_supplier_version_positive CHECK (version > 0),
            CONSTRAINT fk_suppliers_tenant_creator FOREIGN KEY (company_id, created_by)
                REFERENCES drivers(company_id, id) ON DELETE RESTRICT,
            CONSTRAINT fk_suppliers_tenant_editor FOREIGN KEY (company_id, updated_by)
                REFERENCES drivers(company_id, id) ON DELETE RESTRICT
        )
    """)
    op.execute("CREATE INDEX ix_suppliers_company_active_id ON suppliers(company_id, is_active, id)")
    op.execute("CREATE INDEX ix_suppliers_search ON suppliers USING gin(search_text gin_trgm_ops)")
    op.execute("""
        CREATE TABLE inventory_supplier_evidence (
            company_id INTEGER NOT NULL,
            movement_id INTEGER NOT NULL,
            supplier_id INTEGER NOT NULL,
            supplier_name VARCHAR(300) NOT NULL,
            supplier_code VARCHAR(50), request_id UUID NOT NULL,
            CONSTRAINT pk_inventory_supplier_evidence PRIMARY KEY (company_id, movement_id),
            CONSTRAINT fk_supplier_evidence_movement FOREIGN KEY (company_id, movement_id)
                REFERENCES inventory_movements(company_id, id) ON DELETE RESTRICT,
            CONSTRAINT fk_supplier_evidence_supplier FOREIGN KEY (company_id, supplier_id)
                REFERENCES suppliers(company_id, id) ON DELETE RESTRICT
        )
    """)
    for table in ("suppliers", "inventory_supplier_evidence"):
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        expr = "company_id = NULLIF(current_setting('app.current_tenant', true), '')::integer"
        op.execute(f'CREATE POLICY {table}_tenant_guard ON "{table}" USING ({expr}) WITH CHECK ({expr})')
    op.execute("""
        CREATE FUNCTION protect_inventory_supplier_evidence() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'Supplier document evidence is immutable';
        END $$
    """)
    op.execute("""
        CREATE TRIGGER inventory_supplier_evidence_immutable
            BEFORE UPDATE OR DELETE ON inventory_supplier_evidence
            FOR EACH ROW EXECUTE FUNCTION protect_inventory_supplier_evidence();
    """)
    runtime_role = make_url(os.environ["DATABASE_URL"]).username
    if not runtime_role or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", runtime_role):
        raise RuntimeError("Runtime database role could not be resolved safely")
    op.execute(f'GRANT SELECT, INSERT, UPDATE ON suppliers TO "{runtime_role}"')
    op.execute(f'REVOKE DELETE, TRUNCATE ON suppliers FROM "{runtime_role}"')
    op.execute(f'GRANT USAGE, SELECT ON SEQUENCE suppliers_id_seq TO "{runtime_role}"')
    op.execute(f'GRANT SELECT, INSERT ON inventory_supplier_evidence TO "{runtime_role}"')
    op.execute(f'REVOKE UPDATE, DELETE, TRUNCATE ON inventory_supplier_evidence FROM "{runtime_role}"')
    op.execute("INSERT INTO permissions(code) VALUES ('supplier.read'), ('supplier.manage') ON CONFLICT(code) DO NOTHING")


def downgrade():
    # Fail before any destructive step. Exporting evidence requires an explicit plan.
    # Never let tenant RLS hide history from a non-BYPASSRLS migration role.
    # Such a role must fail closed instead of mistaking invisible rows for empty tables.
    op.execute("SET LOCAL row_security = off")
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM inventory_supplier_evidence) OR EXISTS (SELECT 1 FROM suppliers) THEN
                RAISE EXCEPTION 'Cannot downgrade: Supplier identity or historical evidence exists';
            END IF;
        END $$;
    """)
    op.drop_table("inventory_supplier_evidence")
    op.execute("DROP FUNCTION protect_inventory_supplier_evidence()")
    op.drop_table("suppliers")
    # Retain permission catalog entries, consistent with canonical RBAC migrations.
