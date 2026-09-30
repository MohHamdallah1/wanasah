"""Product Import orphaned business-job recovery boundary.

Revision ID: a42c9f17e6b3
Revises: d31c7a940e62
"""
from __future__ import annotations

import os
import re

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.engine import make_url

revision = "a42c9f17e6b3"
down_revision = "d31c7a940e62"
branch_labels = None
depends_on = None


def upgrade() -> None:
    role = make_url(os.environ["DATABASE_URL"]).username
    if not role or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", role):
        raise RuntimeError("Cannot safely resolve runtime database role")
    bind = op.get_bind()
    if not bind.scalar(text(
        "SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user"
    )):
        raise RuntimeError(
            "Product Import recovery boundary requires DATABASE_URL_MIGRATION "
            "with RLS bypass"
        )
    quoted_role = bind.dialect.identifier_preparer.quote(role)

    op.create_index(
        "ix_product_import_job_orphan_recovery",
        "product_import_jobs",
        ["updated_at", "company_id", "id"],
        unique=False,
        postgresql_where=sa.text(
            "status IN ('QUEUED','PARSING','VALIDATING','IMPORTING','RETRYING')"
        ),
    )

    op.execute("""
        CREATE OR REPLACE FUNCTION public.product_import_claim_orphaned_jobs(
            p_stale_seconds integer,
            p_limit integer
        )
        RETURNS TABLE(company_id integer, job_id uuid)
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        SET row_security = off
        AS $function$
        BEGIN
            IF p_stale_seconds < 1 OR p_stale_seconds > 86400 THEN
                RAISE EXCEPTION 'p_stale_seconds must be between 1 and 86400';
            END IF;
            IF p_limit < 1 OR p_limit > 500 THEN
                RAISE EXCEPTION 'p_limit must be between 1 and 500';
            END IF;

            RETURN QUERY
            SELECT j.company_id, j.id
            FROM public.product_import_jobs AS j
            WHERE j.status IN (
                'QUEUED','PARSING','VALIDATING','IMPORTING','RETRYING'
            )
              AND j.updated_at < (
                  (CURRENT_TIMESTAMP AT TIME ZONE current_setting('TimeZone'))
                  - make_interval(secs => p_stale_seconds)
              )
              AND NOT EXISTS (
                  SELECT 1
                  FROM public.procrastinate_jobs AS q
                  WHERE q.task_name = 'wanasah.process_product_import'
                    AND q.status IN ('todo','doing')
                    AND q.args->>'job_id' = j.id::text
                    AND q.args->>'company_id' = j.company_id::text
              )
            ORDER BY j.updated_at, j.company_id, j.id
            FOR UPDATE OF j SKIP LOCKED
            LIMIT p_limit;
        END
        $function$;
    """)
    op.execute(
        "REVOKE ALL ON FUNCTION "
        "public.product_import_claim_orphaned_jobs(integer, integer) "
        "FROM PUBLIC"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION "
        "public.product_import_claim_orphaned_jobs(integer, integer) "
        f"TO {quoted_role}"
    )


def downgrade() -> None:
    op.execute(
        "DROP FUNCTION IF EXISTS "
        "public.product_import_claim_orphaned_jobs(integer, integer)"
    )
    op.drop_index(
        "ix_product_import_job_orphan_recovery",
        table_name="product_import_jobs",
    )
