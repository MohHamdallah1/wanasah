"""Add company principal, typed independent profiles and Company Owner slots.

Revision ID: e9c4b1a7d620
Revises: c6f1a4d8e203
Owner: domains/identity. Expand only: no legacy reads, writes or FK changes.
"""
from __future__ import annotations

import os
import re

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine import make_url

revision = "e9c4b1a7d620"
down_revision = "c6f1a4d8e203"
branch_labels = None
depends_on = None

_TABLES = ("company_principals", "backoffice_users", "field_representatives", "company_owners")


def _runtime_role() -> str:
    raw = os.getenv("DATABASE_URL")
    if not raw:
        raise RuntimeError("DATABASE_URL is required to resolve the runtime database role.")
    role = make_url(raw).username
    if not role or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", role):
        raise RuntimeError("Runtime database role could not be resolved safely.")
    if not op.get_context().as_sql:
        row = op.get_bind().execute(sa.text(
            "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = :role"
        ), {"role": role}).mappings().one_or_none()
        if row is None or row["rolsuper"] or row["rolbypassrls"]:
            raise RuntimeError("Runtime database role must exist without superuser or BYPASSRLS.")
    return role


def _timestamps():
    return (
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )


def upgrade() -> None:
    # Resolve restricted-role authority before emitting any new DDL.
    role = _runtime_role()
    quoted_role = '"' + role + '"'
    op.create_table(
        "company_principals",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(80), nullable=False),
        sa.Column("password_hash", sa.String(128), nullable=False),
        sa.Column("full_name", sa.String(120), nullable=False),
        sa.Column("phone_number", sa.String(20), nullable=True),
        sa.Column("principal_type", sa.String(32), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("auth_revision", sa.Integer(), nullable=False, server_default=sa.text("1")),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_company_principals")),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT", name=op.f("fk_company_principals_company_id_companies")),
        sa.UniqueConstraint("company_id", "id", name="uq_company_principals_company_id"),
        sa.UniqueConstraint("company_id", "username", name="uq_company_principals_company_username"),
        sa.UniqueConstraint("company_id", "id", "principal_type", name="uq_company_principals_company_id_type"),
        sa.CheckConstraint("principal_type IN ('BACKOFFICE', 'FIELD_REPRESENTATIVE')", name=op.f("ck_company_principals_principal_type")),
        sa.CheckConstraint("auth_revision > 0", name=op.f("ck_company_principals_auth_revision_positive")),
    )
    op.create_index("ix_company_principals_tenant_type_active_id", "company_principals",
                    ["company_id", "principal_type", "is_active", "id"])
    op.create_table(
        "backoffice_users",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("principal_id", sa.Integer(), nullable=False),
        sa.Column("principal_type", sa.String(32), nullable=False, server_default=sa.text("'BACKOFFICE'")),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_backoffice_users")),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT", name=op.f("fk_backoffice_users_company_id_companies")),
        sa.ForeignKeyConstraint(
            ["company_id", "principal_id", "principal_type"],
            ["company_principals.company_id", "company_principals.id", "company_principals.principal_type"],
            ondelete="RESTRICT", onupdate="RESTRICT", name="fk_backoffice_users_tenant_principal_type",
        ),
        sa.UniqueConstraint("company_id", "id", name="uq_backoffice_users_company_id"),
        sa.UniqueConstraint("company_id", "principal_id", name="uq_backoffice_users_tenant_principal"),
        sa.CheckConstraint("principal_type = 'BACKOFFICE'", name=op.f("ck_backoffice_users_principal_type")),
    )
    op.create_table(
        "field_representatives",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("principal_id", sa.Integer(), nullable=False),
        sa.Column("principal_type", sa.String(32), nullable=False, server_default=sa.text("'FIELD_REPRESENTATIVE'")),
        sa.Column("can_allow_debt", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("max_debt_limit", sa.Numeric(12, 3), nullable=False, server_default=sa.text("0.000")),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_field_representatives")),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT", name=op.f("fk_field_representatives_company_id_companies")),
        sa.ForeignKeyConstraint(
            ["company_id", "principal_id", "principal_type"],
            ["company_principals.company_id", "company_principals.id", "company_principals.principal_type"],
            ondelete="RESTRICT", onupdate="RESTRICT", name="fk_field_representatives_tenant_principal_type",
        ),
        sa.UniqueConstraint("company_id", "id", name="uq_field_representatives_company_id"),
        sa.UniqueConstraint("company_id", "principal_id", name="uq_field_representatives_tenant_principal"),
        sa.CheckConstraint("principal_type = 'FIELD_REPRESENTATIVE'", name=op.f("ck_field_representatives_principal_type")),
        sa.CheckConstraint("max_debt_limit >= 0", name=op.f("ck_field_representatives_max_debt_limit_nonnegative")),
    )
    op.create_table(
        "company_owners",
        sa.Column("company_id", sa.Integer(), nullable=False, autoincrement=False),
        sa.Column("backoffice_user_id", sa.Integer(), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("company_id", name=op.f("pk_company_owners")),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT", name=op.f("fk_company_owners_company_id_companies")),
        sa.ForeignKeyConstraint(
            ["company_id", "backoffice_user_id"],
            ["backoffice_users.company_id", "backoffice_users.id"],
            ondelete="RESTRICT", onupdate="RESTRICT", name="fk_company_owners_tenant_backoffice",
        ),
    )
    expr = "company_id = NULLIF(current_setting('app.current_tenant', true), '')::integer"
    for table in _TABLES:
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        op.execute(f'CREATE POLICY {table}_tenant_access ON "{table}" USING ({expr}) WITH CHECK ({expr})')
        op.execute(f'CREATE POLICY {table}_tenant_guard ON "{table}" AS RESTRICTIVE USING ({expr}) WITH CHECK ({expr})')
        op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON "{table}" TO {quoted_role}')
        op.execute(f'REVOKE TRUNCATE ON "{table}" FROM {quoted_role}')
    for table in _TABLES[:3]:
        op.execute(f'GRANT USAGE, SELECT ON SEQUENCE "{table}_id_seq" TO {quoted_role}')
        op.execute(f'REVOKE UPDATE ON SEQUENCE "{table}_id_seq" FROM {quoted_role}')


def downgrade() -> None:
    # Never silently erase credentials/ownership after later phases populate them.
    # A migration role unable to bypass FORCE RLS fails closed instead of seeing
    # an empty tenant slice and dropping another company's identity history.
    op.execute("SET LOCAL row_security = off")
    # Serialize the emptiness check with concurrent inserts before DROP. Locks
    # cover only these four additive tables, in principal -> profile -> owner order.
    op.execute("LOCK TABLE company_principals, backoffice_users, field_representatives, company_owners IN ACCESS EXCLUSIVE MODE")
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM company_owners)
               OR EXISTS (SELECT 1 FROM field_representatives)
               OR EXISTS (SELECT 1 FROM backoffice_users)
               OR EXISTS (SELECT 1 FROM company_principals) THEN
                RAISE EXCEPTION 'Cannot downgrade populated identity tables; explicit rollback mapping required';
            END IF;
        END $$;
    """)
    for table in reversed(_TABLES):
        op.drop_table(table)
