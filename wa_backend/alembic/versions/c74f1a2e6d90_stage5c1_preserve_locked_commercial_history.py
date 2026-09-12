"""stage5c1 preserve locked commercial history

Revision ID: c74f1a2e6d90
Revises: a31c7e5d9b42
"""

from typing import Sequence, Union

from alembic import op


revision: str = "c74f1a2e6d90"
down_revision: Union[str, Sequence[str], None] = "a31c7e5d9b42"
branch_labels = None
depends_on = None


_HARDEN_PRICE_ENTRY_GUARD = r"""
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

            IF upper(NEW.effectivity) IS NOT NULL
               AND EXISTS (
                    SELECT 1
                    FROM price_publications AS p
                    JOIN route_commercial_contexts AS rc
                      ON rc.company_id = OLD.company_id
                    WHERE p.company_id = OLD.company_id
                      AND p.id = OLD.publication_id
                      AND p.price_book_id = OLD.price_book_id
                      AND p.published_at IS NOT NULL
                      AND p.published_at <= rc.pricing_locked_at
                      AND p.revision <= rc.price_publication_revision
                      AND OLD.effectivity @> rc.pricing_locked_at
                      AND rc.pricing_locked_at >= upper(NEW.effectivity)
                      AND EXISTS (
                            SELECT 1
                            FROM price_book_assignments AS a
                            WHERE a.company_id = OLD.company_id
                              AND a.price_book_id = OLD.price_book_id
                              AND a.revision <= rc.assignment_revision
                              AND a.effectivity @> rc.pricing_locked_at
                      )
               )
            THEN
                RAISE EXCEPTION
                    'published price closure would invalidate a locked route commercial context'
                    USING ERRCODE = '55000';
            END IF;
        END IF;
    END IF;

    RETURN NEW;
END;
$$;
"""


_HARDEN_ASSIGNMENT_GUARD = r"""
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

        IF upper(NEW.effectivity) IS NOT NULL
           AND EXISTS (
                SELECT 1
                FROM route_commercial_contexts AS rc
                WHERE rc.company_id = OLD.company_id
                  AND OLD.revision <= rc.assignment_revision
                  AND OLD.effectivity @> rc.pricing_locked_at
                  AND rc.pricing_locked_at >= upper(NEW.effectivity)
           )
        THEN
            RAISE EXCEPTION
                'price assignment closure would invalidate a locked route commercial context'
                USING ERRCODE = '55000';
        END IF;
    END IF;

    RETURN NEW;
END;
$$;
"""


_B2_PRICE_ENTRY_GUARD = r"""
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


_B2_ASSIGNMENT_GUARD = r"""
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


def upgrade() -> None:
    op.execute(_HARDEN_PRICE_ENTRY_GUARD)
    op.execute(_HARDEN_ASSIGNMENT_GUARD)


def downgrade() -> None:
    op.execute(_B2_PRICE_ENTRY_GUARD)
    op.execute(_B2_ASSIGNMENT_GUARD)
