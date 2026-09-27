"""Stage 13 Product Import cancellation state and durable progress events.

Revision ID: d1f4a8c6e2b9
Revises: c9e5f2a7d310
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "d1f4a8c6e2b9"
down_revision = "c9e5f2a7d310"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "chk_product_import_job_status",
        "product_import_jobs",
        type_="check",
    )
    op.create_check_constraint(
        "chk_product_import_job_status",
        "product_import_jobs",
        (
            "status IN ("
            "'QUEUED','PARSING','NEEDS_MAPPING','VALIDATING',"
            "'VALIDATION_FAILED','IMPORTING','RETRYING','CANCELLED',"
            "'COMPLETED','COMPLETED_WITH_ERRORS','FAILED'"
            ")"
        ),
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION notify_product_import_progress()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF TG_OP = 'INSERT'
               OR NEW.status IS DISTINCT FROM OLD.status
               OR NEW.total_rows IS DISTINCT FROM OLD.total_rows
               OR NEW.processed_rows IS DISTINCT FROM OLD.processed_rows
               OR NEW.valid_rows IS DISTINCT FROM OLD.valid_rows
               OR NEW.failed_rows IS DISTINCT FROM OLD.failed_rows
            THEN
                PERFORM pg_notify(
                    'wanasah_product_import_progress',
                    json_build_object(
                        'event', 'PRODUCT_IMPORT_PROGRESS',
                        'company_id', NEW.company_id,
                        'job_id', NEW.id::text,
                        'status', NEW.status,
                        'version', NEW.version,
                        'total_rows', NEW.total_rows,
                        'processed_rows', NEW.processed_rows,
                        'valid_rows', NEW.valid_rows,
                        'failed_rows', NEW.failed_rows
                    )::text
                );
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_product_import_progress_notify
        AFTER INSERT OR UPDATE OF
            status,
            total_rows,
            processed_rows,
            valid_rows,
            failed_rows
        ON product_import_jobs
        FOR EACH ROW
        EXECUTE FUNCTION notify_product_import_progress()
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TRIGGER IF EXISTS trg_product_import_progress_notify
        ON product_import_jobs
        """
    )
    op.execute(
        "DROP FUNCTION IF EXISTS notify_product_import_progress()"
    )

    op.execute(
        """
        UPDATE product_import_jobs
        SET status = 'FAILED',
            error_summary = jsonb_build_object(
                'code',
                'PRODUCT_IMPORT_CANCELLED_DOWNGRADE'
            ),
            version = version + 1,
            updated_at = CURRENT_TIMESTAMP
        WHERE status = 'CANCELLED'
        """
    )

    op.drop_constraint(
        "chk_product_import_job_status",
        "product_import_jobs",
        type_="check",
    )
    op.create_check_constraint(
        "chk_product_import_job_status",
        "product_import_jobs",
        (
            "status IN ("
            "'QUEUED','PARSING','NEEDS_MAPPING','VALIDATING',"
            "'VALIDATION_FAILED','IMPORTING','RETRYING',"
            "'COMPLETED','COMPLETED_WITH_ERRORS','FAILED'"
            ")"
        ),
    )
