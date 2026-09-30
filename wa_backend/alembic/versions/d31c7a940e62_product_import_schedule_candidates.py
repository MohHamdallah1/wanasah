"""Durable event-driven Product Import maintenance candidates.

Revision ID: d31c7a940e62
Revises: ce41f0a92b68
"""
from __future__ import annotations

import os
import re

from alembic import op
from sqlalchemy import text
from sqlalchemy.engine import make_url

revision = "d31c7a940e62"
down_revision = "ce41f0a92b68"
branch_labels = None
depends_on = None

_TABLES = (
    "product_import_jobs", "product_import_sources",
    "product_import_tenant_source_capacity", "product_import_admission_rejections",
)


def upgrade() -> None:
    role = make_url(os.environ["DATABASE_URL"]).username
    if not role or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", role):
        raise RuntimeError("Cannot safely resolve runtime database role")
    if not op.get_bind().scalar(text(
        "SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user"
    )):
        raise RuntimeError("Candidate bootstrap requires DATABASE_URL_MIGRATION with RLS bypass")

    # Transactional DDL + writer locks close the bootstrap/registration gap.
    op.execute("LOCK TABLE " + ", ".join("public." + t for t in _TABLES)
               + " IN SHARE ROW EXCLUSIVE MODE")
    op.execute(
        "CREATE SEQUENCE public.product_import_schedule_generation AS bigint"
    )
    op.execute("""
        CREATE TABLE public.product_import_schedule_candidates (
            company_id integer NOT NULL REFERENCES public.companies(id) ON DELETE CASCADE,
            task_kind text NOT NULL CHECK (task_kind IN ('capacity', 'retention')),
            next_due_at timestamptz NOT NULL,
            generation bigint NOT NULL DEFAULT nextval('public.product_import_schedule_generation'),
            updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            PRIMARY KEY (company_id, task_kind)
        )
    """)
    op.execute("""
        CREATE INDEX ix_product_import_schedule_due
        ON public.product_import_schedule_candidates(task_kind, next_due_at, company_id)
    """)
    op.execute(
        "ALTER TABLE public.product_import_schedule_candidates ENABLE ROW LEVEL SECURITY"
    )
    op.execute(
        "ALTER TABLE public.product_import_schedule_candidates FORCE ROW LEVEL SECURITY"
    )
    op.execute("""
        CREATE POLICY product_import_schedule_tenant
        ON public.product_import_schedule_candidates
        USING (
            company_id = NULLIF(
                current_setting('app.current_tenant', true), ''
            )::integer
        )
    """)
    op.execute(
        "REVOKE ALL ON public.product_import_schedule_candidates FROM PUBLIC"
    )
    op.execute(
        "REVOKE ALL ON SEQUENCE public.product_import_schedule_generation FROM PUBLIC"
    )
    op.execute("""
        CREATE FUNCTION public.product_import_schedule_event() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
        DECLARE
            capacity_due boolean := false;
            retention_due timestamptz;
        BEGIN
            -- Read only the originating row, never tenant business tables.
            IF TG_TABLE_SCHEMA <> 'public' OR TG_RELID NOT IN (
                'public.product_import_jobs'::regclass,
                'public.product_import_sources'::regclass,
                'public.product_import_tenant_source_capacity'::regclass,
                'public.product_import_admission_rejections'::regclass
            ) THEN
                RAISE EXCEPTION 'Unsupported candidate event relation';
            END IF;
            IF TG_TABLE_NAME = 'product_import_jobs' THEN
                IF TG_OP = 'UPDATE' THEN
                    IF ROW(NEW.status, NEW.finished_at, NEW.source_id,
                           NEW.source_payload_cleared_at, NEW.source_payload IS NULL)
                       IS NOT DISTINCT FROM
                       ROW(OLD.status, OLD.finished_at, OLD.source_id,
                           OLD.source_payload_cleared_at, OLD.source_payload IS NULL) THEN
                        RETURN NEW;
                    END IF;
                END IF;
                capacity_due := NEW.status IN
                    ('QUEUED','PARSING','NEEDS_MAPPING','VALIDATING','IMPORTING','RETRYING');
                IF TG_OP = 'UPDATE' THEN
                    capacity_due := capacity_due OR OLD.status IN
                        ('QUEUED','PARSING','NEEDS_MAPPING','VALIDATING','IMPORTING','RETRYING');
                END IF;
                IF NEW.status IN ('VALIDATION_FAILED','COMPLETED','COMPLETED_WITH_ERRORS','FAILED')
                   AND NEW.finished_at IS NOT NULL THEN
                    -- Earliest policy deadline; worker refines detail/lineage deadlines under RLS.
                    retention_due := (NEW.finished_at AT TIME ZONE 'UTC') + interval '7 days';
                END IF;
            ELSIF TG_TABLE_NAME = 'product_import_sources' THEN
                capacity_due := true;
                IF TG_OP = 'UPDATE' AND NEW.deleted_at IS NOT DISTINCT FROM OLD.deleted_at THEN
                    RETURN NEW;
                END IF;
            ELSIF TG_TABLE_NAME = 'product_import_tenant_source_capacity' THEN
                capacity_due := NEW.live_bytes <> 0;
                IF TG_OP = 'UPDATE' THEN
                    IF NEW.live_bytes IS NOT DISTINCT FROM OLD.live_bytes THEN RETURN NEW; END IF;
                    capacity_due := capacity_due OR OLD.live_bytes <> 0;
                END IF;
            ELSIF TG_TABLE_NAME = 'product_import_admission_rejections' THEN
                capacity_due := NEW.created_at >= (clock_timestamp() AT TIME ZONE 'UTC') - interval '1 hour';
            ELSE
                RAISE EXCEPTION 'Unsupported candidate event source';
            END IF;
            IF capacity_due THEN
                INSERT INTO public.product_import_schedule_candidates AS c
                    (company_id, task_kind, next_due_at)
                VALUES (NEW.company_id, 'capacity', clock_timestamp())
                ON CONFLICT (company_id, task_kind) DO UPDATE SET
                    next_due_at = LEAST(c.next_due_at, EXCLUDED.next_due_at),
                    generation = nextval('public.product_import_schedule_generation'),
                    updated_at = clock_timestamp();
            END IF;
            IF retention_due IS NOT NULL THEN
                INSERT INTO public.product_import_schedule_candidates AS c
                    (company_id, task_kind, next_due_at)
                VALUES (NEW.company_id, 'retention', retention_due)
                ON CONFLICT (company_id, task_kind) DO UPDATE SET
                    next_due_at = LEAST(c.next_due_at, EXCLUDED.next_due_at),
                    generation = nextval('public.product_import_schedule_generation'),
                    updated_at = clock_timestamp();
            END IF;
            RETURN NEW;
        END $$
    """)
    op.execute(
        "REVOKE ALL ON FUNCTION public.product_import_schedule_event() FROM PUBLIC"
    )
    events = {
        "product_import_jobs": "INSERT OR UPDATE OF status, finished_at, source_id, source_payload, source_payload_cleared_at",
        "product_import_sources": "INSERT OR UPDATE OF deleted_at",
        "product_import_tenant_source_capacity": "INSERT OR UPDATE OF live_bytes",
        "product_import_admission_rejections": "INSERT",
    }
    for table, event in events.items():
        op.execute(f"CREATE TRIGGER product_import_schedule_event AFTER {event} ON public.{table} "
                   "FOR EACH ROW EXECUTE FUNCTION public.product_import_schedule_event()")

    op.execute("""
        CREATE FUNCTION public.product_import_claim_schedule(kind text, cutoff timestamptz, page_size integer)
        RETURNS TABLE(company_id integer, generation bigint)
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
        BEGIN
            IF kind IS NULL OR kind NOT IN ('capacity','retention') OR page_size IS NULL
               OR page_size < 1 OR page_size > 1000 OR cutoff IS NULL THEN
                RAISE EXCEPTION 'Invalid candidate claim';
            END IF;
            RETURN QUERY
            WITH due AS MATERIALIZED (
                SELECT c.company_id, c.task_kind FROM public.product_import_schedule_candidates c
                WHERE c.task_kind = kind AND c.next_due_at <= LEAST(cutoff, statement_timestamp())
                ORDER BY c.next_due_at, c.company_id LIMIT page_size FOR UPDATE SKIP LOCKED
            )
            UPDATE public.product_import_schedule_candidates c
            SET next_due_at = clock_timestamp() + CASE kind WHEN 'capacity'
                    THEN interval '5 minutes' ELSE interval '1 hour' END,
                updated_at = clock_timestamp()
            FROM due WHERE c.company_id = due.company_id AND c.task_kind = due.task_kind
            RETURNING c.company_id, c.generation;
        END $$
    """)
    op.execute("""
        CREATE FUNCTION public.product_import_finish_schedule(
            tenant integer, kind text, expected_generation bigint, deadline timestamptz)
        RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
        BEGIN
            IF tenant IS NULL OR tenant IS DISTINCT FROM
                NULLIF(current_setting('app.current_tenant', true), '')::integer THEN
                RAISE EXCEPTION 'Candidate tenant context mismatch' USING ERRCODE = '42501';
            END IF;
            IF deadline IS NULL THEN
                DELETE FROM public.product_import_schedule_candidates c
                WHERE c.company_id = tenant AND c.task_kind = kind AND c.generation = expected_generation;
            ELSE
                UPDATE public.product_import_schedule_candidates c
                SET next_due_at = deadline, updated_at = clock_timestamp(),
                    generation = nextval('public.product_import_schedule_generation')
                WHERE c.company_id = tenant AND c.task_kind = kind AND c.generation = expected_generation;
            END IF;
        END $$
    """)
    op.execute(
        "REVOKE ALL ON FUNCTION "
        "public.product_import_claim_schedule(text,timestamptz,integer) FROM PUBLIC"
    )
    op.execute(
        "REVOKE ALL ON FUNCTION "
        "public.product_import_finish_schedule(integer,text,bigint,timestamptz) FROM PUBLIC"
    )
    # Runtime reads its own candidate through FORCE RLS; only the bounded claim
    # function sees global control metadata. Neither callable reads business data.
    # Also neutralize default privileges: runtime must not directly mutate the
    # registry or call the trigger function outside its installed triggers.
    op.execute(f'REVOKE ALL ON public.product_import_schedule_candidates FROM "{role}"')
    op.execute(f'REVOKE ALL ON SEQUENCE public.product_import_schedule_generation FROM "{role}"')
    op.execute(f'REVOKE ALL ON FUNCTION public.product_import_schedule_event() FROM "{role}"')
    op.execute(f'GRANT SELECT ON public.product_import_schedule_candidates TO "{role}"')
    for signature in (
        "product_import_claim_schedule(text,timestamptz,integer)",
        "product_import_finish_schedule(integer,text,bigint,timestamptz)",
    ):
        op.execute(f'GRANT EXECUTE ON FUNCTION public.{signature} TO "{role}"')

    # One privileged, transactional bootstrap from relevant import records only.
    # UTC conversion matches the existing naive UTC business timestamps.
    op.execute("""
        INSERT INTO public.product_import_schedule_candidates(company_id, task_kind, next_due_at)
        SELECT company_id, 'capacity', clock_timestamp() FROM (
            SELECT company_id FROM public.product_import_tenant_source_capacity WHERE live_bytes <> 0
            UNION SELECT company_id FROM public.product_import_sources WHERE deleted_at IS NULL
            UNION SELECT company_id FROM public.product_import_jobs WHERE status IN
                ('QUEUED','PARSING','NEEDS_MAPPING','VALIDATING','IMPORTING','RETRYING')
            UNION SELECT company_id FROM public.product_import_admission_rejections
                WHERE created_at >= (clock_timestamp() AT TIME ZONE 'UTC') - interval '1 hour'
        ) relevant
    """)
    op.execute("""
        INSERT INTO public.product_import_schedule_candidates(company_id, task_kind, next_due_at)
        SELECT j.company_id, 'retention', min(d.deadline AT TIME ZONE 'UTC')
        FROM public.product_import_jobs j
        CROSS JOIN LATERAL (
            SELECT j.finished_at + interval '7 days' AS deadline
            WHERE j.source_payload IS NOT NULL OR (j.source_id IS NOT NULL AND j.source_payload_cleared_at IS NULL)
            UNION ALL SELECT j.finished_at + interval '30 days' WHERE EXISTS (
                SELECT 1 FROM public.product_import_rows r
                WHERE r.company_id = j.company_id AND r.job_id = j.id AND r.compacted_at IS NULL)
            UNION ALL SELECT j.finished_at + interval '365 days' WHERE EXISTS (
                SELECT 1 FROM public.product_import_rows r WHERE r.company_id = j.company_id AND r.job_id = j.id)
        ) d
        WHERE j.finished_at IS NOT NULL AND j.status IN
            ('VALIDATION_FAILED','COMPLETED','COMPLETED_WITH_ERRORS','FAILED')
        GROUP BY j.company_id
    """)


def downgrade() -> None:
    for table in _TABLES:
        op.execute(f"DROP TRIGGER product_import_schedule_event ON public.{table}")
    op.execute("DROP FUNCTION public.product_import_schedule_event()")
    op.execute("DROP FUNCTION public.product_import_claim_schedule(text,timestamptz,integer)")
    op.execute("DROP FUNCTION public.product_import_finish_schedule(integer,text,bigint,timestamptz)")
    op.execute("DROP TABLE public.product_import_schedule_candidates")
    op.execute("DROP SEQUENCE public.product_import_schedule_generation")
