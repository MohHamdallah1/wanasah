"""stage5b2 pricing workflow guards

Revision ID: f2a9c4e7d1b6
Revises: e5a1c9d4b7f2
"""

from typing import Sequence, Union

from alembic import op


revision: str = "f2a9c4e7d1b6"
down_revision: Union[str, Sequence[str], None] = "e5a1c9d4b7f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM role_permissions rp
                JOIN permissions p ON p.id = rp.permission_id
                WHERE p.code IN (
                    'pricing.read',
                    'pricing.publish',
                    'pricing.assign'
                )
                LIMIT 1
            )
            THEN
                RAISE EXCEPTION
                    'Refusing Stage5B2 permission rename: temporary B1 pricing permissions are already assigned';
            END IF;
        END
        $$;
        """
    )

    op.execute(
        "DELETE FROM permissions "
        "WHERE code IN ('pricing.read','pricing.publish','pricing.assign')"
    )

    op.execute(
        "INSERT INTO permissions (code) VALUES "
        "('pricing.view'),"
        "('pricing.manage'),"
        "('pricing.approve') "
        "ON CONFLICT (code) DO NOTHING"
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION guard_published_price_entry_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                IF OLD.is_published IS TRUE THEN
                    RAISE EXCEPTION
                        'published price entries are immutable and cannot be deleted'
                        USING ERRCODE = '55000';
                END IF;
                RETURN OLD;
            END IF;

            IF OLD.is_published IS TRUE THEN
                IF NEW.is_published IS DISTINCT FROM TRUE
                   OR NEW.company_id IS DISTINCT FROM OLD.company_id
                   OR NEW.price_book_id IS DISTINCT FROM OLD.price_book_id
                   OR NEW.publication_id IS DISTINCT FROM OLD.publication_id
                   OR NEW.product_variant_id IS DISTINCT FROM OLD.product_variant_id
                   OR NEW.uom_id IS DISTINCT FROM OLD.uom_id
                   OR NEW.amount IS DISTINCT FROM OLD.amount
                   OR NEW.priority IS DISTINCT FROM OLD.priority
                   OR NEW.metadata IS DISTINCT FROM OLD.metadata
                   OR lower(NEW.effectivity) IS DISTINCT FROM lower(OLD.effectivity)
                   OR lower_inc(NEW.effectivity) IS DISTINCT FROM lower_inc(OLD.effectivity)
                   OR upper_inc(NEW.effectivity) IS DISTINCT FROM FALSE
                THEN
                    RAISE EXCEPTION
                        'published price evidence is immutable'
                        USING ERRCODE = '55000';
                END IF;

                IF upper(OLD.effectivity) IS NOT NULL THEN
                    IF NEW.effectivity IS DISTINCT FROM OLD.effectivity THEN
                        RAISE EXCEPTION
                            'closed published price range cannot be rewritten'
                            USING ERRCODE = '55000';
                    END IF;
                ELSE
                    IF upper(NEW.effectivity) IS NOT NULL
                       AND upper(NEW.effectivity) <= lower(NEW.effectivity)
                    THEN
                        RAISE EXCEPTION
                            'published price closure must remain a positive half-open range'
                            USING ERRCODE = '55000';
                    END IF;
                END IF;
            END IF;

            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_published_price_entry_guard
        BEFORE UPDATE OR DELETE ON price_book_entries
        FOR EACH ROW EXECUTE FUNCTION guard_published_price_entry_mutation()
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION guard_price_publication_history()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                IF OLD.status IN ('PUBLISHED', 'SUPERSEDED') THEN
                    RAISE EXCEPTION
                        'published price publication history cannot be deleted'
                        USING ERRCODE = '55000';
                END IF;
                RETURN OLD;
            END IF;

            IF OLD.status IN ('PUBLISHED', 'SUPERSEDED') THEN
                IF OLD.status = 'SUPERSEDED' AND NEW.status IS DISTINCT FROM 'SUPERSEDED' THEN
                    RAISE EXCEPTION
                        'superseded publication is terminal'
                        USING ERRCODE = '55000';
                END IF;
                IF OLD.status = 'PUBLISHED'
                   AND NEW.status NOT IN ('PUBLISHED', 'SUPERSEDED')
                THEN
                    RAISE EXCEPTION
                        'published publication may only become SUPERSEDED'
                        USING ERRCODE = '55000';
                END IF;

                IF NEW.company_id IS DISTINCT FROM OLD.company_id
                   OR NEW.price_book_id IS DISTINCT FROM OLD.price_book_id
                   OR NEW.revision IS DISTINCT FROM OLD.revision
                   OR NEW.effective_at IS DISTINCT FROM OLD.effective_at
                   OR NEW.created_by IS DISTINCT FROM OLD.created_by
                   OR NEW.approved_by IS DISTINCT FROM OLD.approved_by
                   OR NEW.approved_at IS DISTINCT FROM OLD.approved_at
                   OR NEW.published_at IS DISTINCT FROM OLD.published_at
                   OR NEW.request_id IS DISTINCT FROM OLD.request_id
                THEN
                    RAISE EXCEPTION
                        'published publication evidence is immutable'
                        USING ERRCODE = '55000';
                END IF;
            END IF;

            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_price_publication_history_guard
        BEFORE UPDATE OR DELETE ON price_publications
        FOR EACH ROW EXECUTE FUNCTION guard_price_publication_history()
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION guard_price_assignment_history()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION
                    'price assignment history is immutable'
                    USING ERRCODE = '55000';
            END IF;

            IF NEW.company_id IS DISTINCT FROM OLD.company_id
               OR NEW.price_book_id IS DISTINCT FROM OLD.price_book_id
               OR NEW.scope_type IS DISTINCT FROM OLD.scope_type
               OR NEW.scope_id IS DISTINCT FROM OLD.scope_id
               OR NEW.priority IS DISTINCT FROM OLD.priority
               OR NEW.revision IS DISTINCT FROM OLD.revision
               OR NEW.created_by IS DISTINCT FROM OLD.created_by
               OR lower(NEW.effectivity) IS DISTINCT FROM lower(OLD.effectivity)
               OR lower_inc(NEW.effectivity) IS DISTINCT FROM lower_inc(OLD.effectivity)
               OR upper_inc(NEW.effectivity) IS DISTINCT FROM FALSE
            THEN
                RAISE EXCEPTION
                    'price assignment identity/history is immutable'
                    USING ERRCODE = '55000';
            END IF;

            IF upper(OLD.effectivity) IS NOT NULL THEN
                IF NEW.effectivity IS DISTINCT FROM OLD.effectivity THEN
                    RAISE EXCEPTION
                        'closed price assignment range cannot be rewritten'
                        USING ERRCODE = '55000';
                END IF;
            ELSE
                IF upper(NEW.effectivity) IS NOT NULL
                   AND upper(NEW.effectivity) <= lower(NEW.effectivity)
                THEN
                    RAISE EXCEPTION
                        'price assignment closure must remain a positive half-open range'
                        USING ERRCODE = '55000';
                END IF;
            END IF;

            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_price_assignment_history_guard
        BEFORE UPDATE OR DELETE ON price_book_assignments
        FOR EACH ROW EXECUTE FUNCTION guard_price_assignment_history()
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM role_permissions rp
                JOIN permissions p ON p.id = rp.permission_id
                WHERE p.code IN (
                    'pricing.view',
                    'pricing.manage',
                    'pricing.approve'
                )
                LIMIT 1
            )
            THEN
                RAISE EXCEPTION
                    'Refusing Stage5B2 downgrade: pricing permissions are assigned';
            END IF;
        END
        $$;
        """
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM price_book_entries
                WHERE is_published IS TRUE
                LIMIT 1
            )
            OR EXISTS (
                SELECT 1 FROM price_book_assignments
                LIMIT 1
            )
            OR EXISTS (
                SELECT 1 FROM price_publications
                WHERE status IN ('PUBLISHED', 'SUPERSEDED')
                LIMIT 1
            )
            THEN
                RAISE EXCEPTION
                    'Refusing guard downgrade: immutable pricing history exists';
            END IF;
        END
        $$;
        """
    )

    op.execute(
        "DROP TRIGGER IF EXISTS trg_price_assignment_history_guard "
        "ON price_book_assignments"
    )
    op.execute("DROP FUNCTION IF EXISTS guard_price_assignment_history()")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_price_publication_history_guard "
        "ON price_publications"
    )
    op.execute("DROP FUNCTION IF EXISTS guard_price_publication_history()")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_published_price_entry_guard "
        "ON price_book_entries"
    )
    op.execute("DROP FUNCTION IF EXISTS guard_published_price_entry_mutation()")

    op.execute(
        "DELETE FROM permissions WHERE code IN ('pricing.view','pricing.approve')"
    )
    op.execute(
        "INSERT INTO permissions (code) VALUES "
        "('pricing.read'),"
        "('pricing.manage'),"
        "('pricing.publish'),"
        "('pricing.assign') "
        "ON CONFLICT (code) DO NOTHING"
    )
