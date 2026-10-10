"""Expand principal-bound refresh storage alongside untouched legacy sessions.

Revision ID: b7e3f6a1c902
Revises: a4d2e7c9b630
"""
import os
import re

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine import make_url

revision = "b7e3f6a1c902"
down_revision = "a4d2e7c9b630"
branch_labels = None
depends_on = None
TABLE = "principal_refresh_tokens"


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
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("principal_id", sa.Integer(), nullable=False),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("token", sa.String(500), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("is_revoked", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("replaced_by_id", sa.Integer(), nullable=True),
        sa.Column("auth_revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_principal_refresh_tokens")),
        sa.UniqueConstraint("company_id", "id", name="uq_principal_refresh_tokens_company_id"),
        sa.UniqueConstraint("company_id", "principal_id", "channel", "id", name="uq_principal_refresh_tokens_session_id"),
        sa.UniqueConstraint("token", name="uq_principal_refresh_tokens_token"),
        sa.ForeignKeyConstraint(
            ["company_id", "principal_id"], ["company_principals.company_id", "company_principals.id"],
            name="fk_principal_refresh_tokens_tenant_principal", ondelete="CASCADE", onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "principal_id", "channel", "replaced_by_id"],
            [f"{TABLE}.company_id", f"{TABLE}.principal_id", f"{TABLE}.channel", f"{TABLE}.id"],
            name="fk_principal_refresh_tokens_session_successor",
            ondelete="SET NULL (replaced_by_id)", onupdate="RESTRICT",
        ),
        sa.CheckConstraint("channel IN ('DASHBOARD', 'FIELD')", name=op.f("ck_principal_refresh_tokens_channel")),
        sa.CheckConstraint("auth_revision > 0", name=op.f("ck_principal_refresh_tokens_auth_revision_positive")),
    )
    op.create_index("uq_principal_refresh_tokens_replaced_by_id", TABLE, ["replaced_by_id"], unique=True)
    op.create_index("ix_principal_refresh_tokens_principal_channel", TABLE, ["company_id", "principal_id", "channel", "is_revoked", "id"])
    op.create_index("ix_principal_refresh_tokens_expires_at", TABLE, ["expires_at"])
    op.create_index("ix_principal_refresh_tokens_tenant_revocation_expiry", TABLE, ["company_id", "is_revoked", "expires_at", "id"])
    expr = "company_id = NULLIF(current_setting('app.current_tenant', true), '')::integer"
    op.execute(f'ALTER TABLE "{TABLE}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{TABLE}" FORCE ROW LEVEL SECURITY')
    op.execute(f'CREATE POLICY {TABLE}_tenant_access ON "{TABLE}" USING ({expr}) WITH CHECK ({expr})')
    op.execute(f'CREATE POLICY {TABLE}_tenant_guard ON "{TABLE}" AS RESTRICTIVE USING ({expr}) WITH CHECK ({expr})')
    op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON "{TABLE}" TO {role}')
    op.execute(f'REVOKE TRUNCATE ON "{TABLE}" FROM {role}')
    op.execute(f'GRANT USAGE, SELECT ON SEQUENCE "{TABLE}_id_seq" TO {role}')
    op.execute(f'REVOKE UPDATE ON SEQUENCE "{TABLE}_id_seq" FROM {role}')


def downgrade():
    op.execute("SET LOCAL row_security = off")
    op.execute(f'LOCK TABLE "{TABLE}" IN ACCESS EXCLUSIVE MODE')
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM principal_refresh_tokens) THEN
            RAISE EXCEPTION 'Cannot downgrade populated principal refresh sessions; explicit rollback required';
        END IF;
    END $$;""")
    op.drop_table(TABLE)
