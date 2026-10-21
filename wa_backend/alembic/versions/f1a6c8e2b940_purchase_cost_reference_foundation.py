"""Company/variant purchase-cost references; no accounting/history backfill.

Revision ID: f1a6c8e2b940
Revises: e6b4c2d9a731
"""
import os
import re

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import make_url

revision = "f1a6c8e2b940"
down_revision = "e6b4c2d9a731"
branch_labels = None
depends_on = None

_TABLES = ("purchase_cost_reference_commands", "purchase_cost_reference_changes", "purchase_cost_references")


def _values():
    return [
        sa.Column("amount", sa.Numeric(20, 6), nullable=False),
        sa.Column("purchase_uom_id", sa.Integer, sa.ForeignKey("uom.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("base_uom_id", sa.Integer, sa.ForeignKey("uom.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("factor_numerator", sa.Numeric(78, 0), nullable=False),
        sa.Column("factor_denominator", sa.Numeric(78, 0), nullable=False),
        sa.Column("currency_code", sa.String(10), nullable=False),
        sa.Column("source", sa.String(30), nullable=False),
        sa.Column("source_cost_event_id", sa.BigInteger, nullable=True),
        sa.Column("provenance", postgresql.JSONB, nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
    ]


def _constraints(prefix):
    return [
        sa.CheckConstraint("amount BETWEEN 0 AND 99999999999999.999999", name=prefix + "_amount"),
        sa.CheckConstraint("revision > 0", name=prefix + "_revision"),
        sa.CheckConstraint("factor_numerator > 0 AND factor_numerator < 'Infinity'::numeric AND "
            "factor_denominator > 0 AND factor_denominator < 'Infinity'::numeric", name=prefix + "_ratio"),
        sa.CheckConstraint("currency_code ~ '^[A-Z][A-Z0-9]{2,9}$'", name=prefix + "_currency"),
        sa.CheckConstraint("jsonb_typeof(provenance) = 'object'", name=prefix + "_provenance"),
        sa.CheckConstraint(
            "(source = 'MANUAL_PRODUCT' AND source_cost_event_id IS NULL) OR "
            "(source = 'SUPPLIER_INBOUND' AND source_cost_event_id IS NOT NULL)",
            name=prefix + "_source",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "product_variant_id"], ["product_variants.company_id", "product_variants.id"],
            name=prefix + "_variant_fk", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "source_cost_event_id"], ["inventory_cost_events.company_id", "inventory_cost_events.id"],
            name=prefix + "_event_fk", ondelete="RESTRICT",
        ),
    ]


def upgrade():
    op.create_table(
        _TABLES[0],
        sa.Column("company_id", sa.Integer, sa.ForeignKey("companies.id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("request_id", sa.Uuid, primary_key=True),
        sa.Column("operation", sa.String(30), nullable=False),
        sa.Column("actor_principal_id", sa.Integer, nullable=False),
        sa.Column("actor_backoffice_user_id", sa.Integer, nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("response_json", postgresql.JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id", "actor_principal_id"], ["company_principals.company_id", "company_principals.id"],
            name="pcrc_principal_fk", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "actor_backoffice_user_id"], ["backoffice_users.company_id", "backoffice_users.id"],
            name="pcrc_profile_fk", ondelete="RESTRICT",
        ),
        sa.CheckConstraint("request_hash ~ '^[0-9a-f]{64}$'", name="pcrc_hash"),
        sa.CheckConstraint("operation IN ('MANUAL_PRODUCT_SET','SUPPLIER_INBOUND_SET')", name="pcrc_operation"),
        sa.CheckConstraint("jsonb_typeof(response_json) = 'object'", name="pcrc_response"),
    )
    op.create_table(
        _TABLES[1],
        sa.Column("company_id", sa.Integer, sa.ForeignKey("companies.id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("product_variant_id", sa.Integer, primary_key=True),
        sa.Column("revision", sa.Integer, primary_key=True),
        sa.Column("request_id", sa.Uuid, nullable=False),
        sa.Column("before_snapshot", postgresql.JSONB, nullable=True),
        *_values(), *_constraints("pcrh"),
        sa.ForeignKeyConstraint(
            ["company_id", "request_id"], [_TABLES[0] + ".company_id", _TABLES[0] + ".request_id"],
            name="pcrh_command_fk", ondelete="RESTRICT",
        ),
    )
    op.create_table(
        _TABLES[2],
        sa.Column("company_id", sa.Integer, sa.ForeignKey("companies.id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("product_variant_id", sa.Integer, primary_key=True),
        sa.Column("revision", sa.Integer, nullable=False),
        *_values(), *_constraints("pcr"),
        sa.ForeignKeyConstraint(
            ["company_id", "product_variant_id", "revision"],
            [_TABLES[1] + ".company_id", _TABLES[1] + ".product_variant_id", _TABLES[1] + ".revision"],
            name="pcr_history_fk", ondelete="RESTRICT", deferrable=True, initially="DEFERRED",
        ),
    )
    for table in _TABLES:
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        expr = "company_id = NULLIF(current_setting('app.current_tenant', true), '')::integer"
        op.execute(f'CREATE POLICY {table}_tenant ON "{table}" USING ({expr}) WITH CHECK ({expr})')

    op.execute("""
        CREATE FUNCTION protect_purchase_reference_evidence() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'Purchase reference evidence is append-only' USING ERRCODE='55000';
        END $$;
    """)
    for table in _TABLES[:2]:
        op.execute(f"""
            CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION protect_purchase_reference_evidence();
        """)
        op.execute(f"""
            CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON {table}
            FOR EACH STATEMENT EXECUTE FUNCTION protect_purchase_reference_evidence();
        """)
    op.execute("""
        CREATE FUNCTION protect_purchase_reference_revision() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP <> 'UPDATE' THEN
                RAISE EXCEPTION 'Purchase reference cannot be deleted' USING ERRCODE='55000';
            END IF;
            IF NEW.company_id <> OLD.company_id OR NEW.product_variant_id <> OLD.product_variant_id
               OR NEW.revision <> OLD.revision + 1 THEN
                RAISE EXCEPTION 'Purchase reference revision must advance exactly once' USING ERRCODE='55000';
            END IF;
            RETURN NEW;
        END $$;
    """)
    op.execute("""
        CREATE TRIGGER purchase_reference_revision BEFORE UPDATE OR DELETE ON purchase_cost_references
        FOR EACH ROW EXECUTE FUNCTION protect_purchase_reference_revision();
    """)
    op.execute("""
        CREATE TRIGGER purchase_reference_no_truncate BEFORE TRUNCATE ON purchase_cost_references
        FOR EACH STATEMENT EXECUTE FUNCTION protect_purchase_reference_evidence();
    """)
    op.execute("""
        CREATE FUNCTION validate_purchase_reference_history() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM purchase_cost_reference_changes h
                WHERE h.company_id = NEW.company_id AND h.product_variant_id = NEW.product_variant_id
                  AND h.revision = NEW.revision
                  AND (to_jsonb(h) - 'request_id' - 'before_snapshot') = to_jsonb(NEW)
            ) THEN
                RAISE EXCEPTION 'Purchase reference requires identical immutable audit evidence'
                    USING ERRCODE='23514';
            END IF;
            RETURN NEW;
        END $$;
    """)
    op.execute("""
        CREATE CONSTRAINT TRIGGER purchase_reference_audited
        AFTER INSERT OR UPDATE ON purchase_cost_references
        DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
        EXECUTE FUNCTION validate_purchase_reference_history();
    """)
    op.execute("""
        CREATE FUNCTION validate_purchase_reference_actor() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM backoffice_users p
                WHERE p.company_id=NEW.company_id AND p.id=NEW.actor_backoffice_user_id
                  AND p.principal_id=NEW.actor_principal_id
            ) THEN
                RAISE EXCEPTION 'Purchase reference actor/profile mismatch' USING ERRCODE='23514';
            END IF;
            RETURN NEW;
        END $$;
    """)
    op.execute("""
        CREATE TRIGGER purchase_reference_actor BEFORE INSERT ON purchase_cost_reference_commands
        FOR EACH ROW EXECUTE FUNCTION validate_purchase_reference_actor();
    """)
    role = make_url(os.environ["DATABASE_URL"]).username
    if not role or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", role):
        raise RuntimeError("Runtime database role could not be resolved safely")
    for table in _TABLES[:2]:
        op.execute(f'GRANT SELECT, INSERT ON "{table}" TO "{role}"')
        op.execute(f'REVOKE UPDATE, DELETE, TRUNCATE ON "{table}" FROM "{role}"')
    op.execute(f'GRANT SELECT, INSERT, UPDATE ON purchase_cost_references TO "{role}"')
    op.execute(f'REVOKE DELETE, TRUNCATE ON purchase_cost_references FROM "{role}"')
    op.execute("""
        INSERT INTO permissions(code) VALUES
        ('inventory.purchase_cost_reference.read'), ('inventory.purchase_cost_reference.manage')
        ON CONFLICT(code) DO NOTHING
    """)


def downgrade():
    op.execute("SET LOCAL row_security = off")
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM purchase_cost_references)
               OR EXISTS (SELECT 1 FROM purchase_cost_reference_changes)
               OR EXISTS (SELECT 1 FROM purchase_cost_reference_commands) THEN
                RAISE EXCEPTION 'Refusing downgrade: purchase reference evidence exists';
            END IF;
        END $$;
    """)
    for table in reversed(_TABLES):
        op.drop_table(table)
    for function in ("validate_purchase_reference_actor", "validate_purchase_reference_history",
                     "protect_purchase_reference_revision", "protect_purchase_reference_evidence"):
        op.execute(f"DROP FUNCTION {function}()")
    # Keep catalog entries; never remove role grants as an implicit downgrade.
