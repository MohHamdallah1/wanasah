"""Temporary tenant-safe legacy Driver bridge, without changing any legacy FK.

Revision ID: a4d2e7c9b630
Revises: e9c4b1a7d620
"""
import os
import re

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine import make_url

revision = "a4d2e7c9b630"
down_revision = "e9c4b1a7d620"
branch_labels = None
depends_on = None

TABLE = "identity_legacy_driver_map"
TARGETS = {
    "backoffice_principal_id": "company_principals",
    "backoffice_user_id": "backoffice_users",
    "field_principal_id": "company_principals",
    "field_representative_id": "field_representatives",
}


def _runtime_role():
    raw = os.getenv("DATABASE_URL")
    role = make_url(raw).username if raw else None
    if not role or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", role):
        raise RuntimeError("Restricted runtime database role required")
    if not op.get_context().as_sql:
        row = op.get_bind().execute(sa.text(
            "SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=:role"
        ), {"role": role}).one_or_none()
        if row is None or row[0] or row[1]:
            raise RuntimeError("Runtime role must exist without superuser or BYPASSRLS")
    return '"' + role + '"'


def upgrade():
    role = _runtime_role()
    op.create_table(
        TABLE,
        sa.Column("company_id", sa.Integer(), nullable=False, autoincrement=False),
        sa.Column("legacy_driver_id", sa.Integer(), nullable=False, autoincrement=False),
        sa.Column("classification", sa.String(32), nullable=False),
        *[sa.Column(column, sa.Integer(), nullable=True) for column in TARGETS],
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("company_id", "legacy_driver_id", name=op.f("pk_identity_legacy_driver_map")),
        sa.ForeignKeyConstraint(["company_id", "legacy_driver_id"], ["drivers.company_id", "drivers.id"],
                                name="fk_identity_legacy_map_tenant_driver", ondelete="RESTRICT", onupdate="RESTRICT"),
        *[sa.ForeignKeyConstraint(["company_id", column], [f"{target}.company_id", f"{target}.id"],
                                 name=f"fk_identity_legacy_map_{column}", ondelete="RESTRICT", onupdate="RESTRICT")
          for column, target in TARGETS.items()],
        *[sa.UniqueConstraint("company_id", column, name=f"uq_identity_legacy_map_{column}") for column in TARGETS],
        sa.CheckConstraint("""
            (classification = 'BACKOFFICE_ONLY'
             AND backoffice_principal_id IS NOT NULL AND backoffice_user_id IS NOT NULL
             AND field_principal_id IS NULL AND field_representative_id IS NULL)
         OR (classification = 'FIELD_ONLY'
             AND backoffice_principal_id IS NULL AND backoffice_user_id IS NULL
             AND field_principal_id IS NOT NULL AND field_representative_id IS NOT NULL)
         OR (classification = 'DUAL_SPLIT'
             AND backoffice_principal_id IS NOT NULL AND backoffice_user_id IS NOT NULL
             AND field_principal_id IS NOT NULL AND field_representative_id IS NOT NULL
             AND backoffice_principal_id <> field_principal_id)
        """, name=op.f("ck_identity_legacy_driver_map_classification_targets")),
    )
    expr = "company_id = NULLIF(current_setting('app.current_tenant', true), '')::integer"
    op.execute(f'ALTER TABLE "{TABLE}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{TABLE}" FORCE ROW LEVEL SECURITY')
    op.execute(f'CREATE POLICY {TABLE}_tenant_access ON "{TABLE}" USING ({expr}) WITH CHECK ({expr})')
    op.execute(f'CREATE POLICY {TABLE}_tenant_guard ON "{TABLE}" AS RESTRICTIVE USING ({expr}) WITH CHECK ({expr})')
    op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON "{TABLE}" TO {role}')
    op.execute(f'REVOKE TRUNCATE ON "{TABLE}" FROM {role}')


def downgrade():
    op.execute("SET LOCAL row_security = off")
    op.execute(f'LOCK TABLE "{TABLE}" IN ACCESS EXCLUSIVE MODE')
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM identity_legacy_driver_map) THEN
            RAISE EXCEPTION 'Cannot downgrade populated identity bridge; explicit rollback mapping required';
        END IF;
    END $$;""")
    op.drop_table(TABLE)
