"""stage6 tax rule version hardening

Revision ID: a7d3e5f1c9b2
Revises: 6f0b8d3c2a91
"""

from typing import Sequence, Union

from alembic import op


revision: str = "a7d3e5f1c9b2"
down_revision: Union[str, Sequence[str], None] = "6f0b8d3c2a91"
branch_labels = None
depends_on = None

_MAX_DEPTH = 64


def _preflight_existing_hierarchy() -> None:
    op.execute(
        f"""
        DO $$
        DECLARE
            tenant_id integer;
        BEGIN
            FOR tenant_id IN SELECT id FROM companies ORDER BY id LOOP
                PERFORM set_config('app.current_tenant', tenant_id::text, true);

                IF EXISTS (
                    SELECT 1
                    FROM tax_jurisdictions child
                    JOIN tax_jurisdictions parent
                      ON parent.company_id = child.company_id
                     AND parent.id = child.parent_jurisdiction_id
                    WHERE child.company_id = tenant_id
                      AND child.country_code IS DISTINCT FROM parent.country_code
                ) THEN
                    RAISE EXCEPTION
                        'tax jurisdiction country hierarchy is invalid'
                        USING ERRCODE = '23514';
                END IF;

                IF EXISTS (
                    SELECT 1
                    FROM tax_jurisdictions child
                    JOIN tax_jurisdictions parent
                      ON parent.company_id = child.company_id
                     AND parent.id = child.parent_jurisdiction_id
                    WHERE child.company_id = tenant_id
                      AND child.is_active IS TRUE
                      AND parent.is_active IS FALSE
                ) THEN
                    RAISE EXCEPTION
                        'active tax jurisdiction has an inactive parent'
                        USING ERRCODE = '23514';
                END IF;

                IF EXISTS (
                    WITH RECURSIVE walk AS (
                        SELECT
                            j.id AS start_id,
                            j.id,
                            j.parent_jurisdiction_id AS parent_id,
                            1 AS depth,
                            ARRAY[j.id] AS path,
                            false AS cycle
                        FROM tax_jurisdictions j
                        WHERE j.company_id = tenant_id

                        UNION ALL

                        SELECT
                            walk.start_id,
                            parent.id,
                            parent.parent_jurisdiction_id,
                            walk.depth + 1,
                            walk.path || parent.id,
                            parent.id = ANY(walk.path)
                        FROM walk
                        JOIN tax_jurisdictions parent
                          ON parent.company_id = tenant_id
                         AND parent.id = walk.parent_id
                        WHERE walk.parent_id IS NOT NULL
                          AND walk.cycle IS FALSE
                          AND walk.depth <= {_MAX_DEPTH}
                    )
                    SELECT 1
                    FROM walk
                    WHERE cycle IS TRUE
                       OR depth > {_MAX_DEPTH}
                ) THEN
                    RAISE EXCEPTION
                        'tax jurisdiction hierarchy contains a cycle or exceeds {_MAX_DEPTH} levels'
                        USING ERRCODE = '23514';
                END IF;
            END LOOP;

            PERFORM set_config('app.current_tenant', '', true);
        END
        $$;
        """
    )


def _install_hierarchy_guard() -> None:
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION guard_tax_jurisdiction_cycle()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            parent_country text;
            parent_active boolean;
            hierarchy_has_cycle boolean;
            parent_depth integer;
        BEGIN
            IF NEW.parent_jurisdiction_id IS NOT NULL THEN
                IF NEW.parent_jurisdiction_id = NEW.id THEN
                    RAISE EXCEPTION
                        'tax jurisdiction cycle detected'
                        USING ERRCODE = '23514';
                END IF;

                SELECT country_code, is_active
                INTO parent_country, parent_active
                FROM tax_jurisdictions
                WHERE company_id = NEW.company_id
                  AND id = NEW.parent_jurisdiction_id
                FOR SHARE;

                IF FOUND THEN
                    IF parent_country IS DISTINCT FROM NEW.country_code THEN
                        RAISE EXCEPTION
                            'parent and child tax jurisdictions must belong to the same country'
                            USING ERRCODE = '23514';
                    END IF;
                    IF NEW.is_active IS TRUE AND parent_active IS FALSE THEN
                        RAISE EXCEPTION
                            'active tax jurisdiction requires an active parent'
                            USING ERRCODE = '23514';
                    END IF;
                END IF;

                WITH RECURSIVE ancestors AS (
                    SELECT
                        id,
                        parent_jurisdiction_id AS parent_id,
                        1 AS depth,
                        ARRAY[id] AS path,
                        false AS cycle
                    FROM tax_jurisdictions
                    WHERE company_id = NEW.company_id
                      AND id = NEW.parent_jurisdiction_id

                    UNION ALL

                    SELECT
                        parent.id,
                        parent.parent_jurisdiction_id,
                        ancestors.depth + 1,
                        ancestors.path || parent.id,
                        parent.id = ANY(ancestors.path)
                    FROM ancestors
                    JOIN tax_jurisdictions parent
                      ON parent.company_id = NEW.company_id
                     AND parent.id = ancestors.parent_id
                    WHERE ancestors.parent_id IS NOT NULL
                      AND ancestors.cycle IS FALSE
                      AND ancestors.depth < {_MAX_DEPTH}
                )
                SELECT
                    COALESCE(bool_or(id = NEW.id OR cycle IS TRUE), false),
                    COALESCE(max(depth), 0)
                INTO hierarchy_has_cycle, parent_depth
                FROM ancestors;

                IF hierarchy_has_cycle THEN
                    RAISE EXCEPTION
                        'tax jurisdiction cycle detected'
                        USING ERRCODE = '23514';
                END IF;

                IF parent_depth >= {_MAX_DEPTH} THEN
                    RAISE EXCEPTION
                        'tax jurisdiction hierarchy exceeds supported depth of {_MAX_DEPTH}'
                        USING ERRCODE = '23514';
                END IF;
            END IF;

            IF TG_OP = 'UPDATE' THEN
                IF NEW.country_code IS DISTINCT FROM OLD.country_code
                   AND EXISTS (
                       SELECT 1
                       FROM tax_jurisdictions child
                       WHERE child.company_id = NEW.company_id
                         AND child.parent_jurisdiction_id = NEW.id
                         AND child.country_code IS DISTINCT FROM NEW.country_code
                   ) THEN
                    RAISE EXCEPTION
                        'tax jurisdiction country change would invalidate child jurisdictions'
                        USING ERRCODE = '23514';
                END IF;

                IF OLD.is_active IS TRUE
                   AND NEW.is_active IS FALSE
                   AND EXISTS (
                       SELECT 1
                       FROM tax_jurisdictions child
                       WHERE child.company_id = NEW.company_id
                         AND child.parent_jurisdiction_id = NEW.id
                         AND child.is_active IS TRUE
                   ) THEN
                    RAISE EXCEPTION
                        'tax jurisdiction with active children cannot be deactivated'
                        USING ERRCODE = '23514';
                END IF;
            END IF;

            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute("DROP TRIGGER IF EXISTS trg_tax_jurisdiction_cycle ON tax_jurisdictions")
    op.execute(
        """
        CREATE TRIGGER trg_tax_jurisdiction_cycle
        BEFORE INSERT OR UPDATE OF
            parent_jurisdiction_id,
            company_id,
            country_code,
            is_active
        ON tax_jurisdictions
        FOR EACH ROW EXECUTE FUNCTION guard_tax_jurisdiction_cycle()
        """
    )


def _install_identity_guard() -> None:
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION guard_tax_jurisdiction_identity()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF (
                NEW.code IS DISTINCT FROM OLD.code
                OR NEW.jurisdiction_type IS DISTINCT FROM OLD.jurisdiction_type
                OR NEW.country_code IS DISTINCT FROM OLD.country_code
                OR NEW.subdivision_code IS DISTINCT FROM OLD.subdivision_code
                OR NEW.locality_code IS DISTINCT FROM OLD.locality_code
                OR NEW.parent_jurisdiction_id IS DISTINCT FROM OLD.parent_jurisdiction_id
            ) AND EXISTS (
                SELECT 1
                FROM tax_rule_scopes
                WHERE company_id = OLD.company_id
                  AND jurisdiction_id = OLD.id
            ) THEN
                RAISE EXCEPTION
                    'referenced tax jurisdiction identity is immutable'
                    USING ERRCODE = '55000';
            END IF;

            IF NEW.parent_jurisdiction_id
                   IS DISTINCT FROM OLD.parent_jurisdiction_id
               AND EXISTS (
                    WITH RECURSIVE
                    old_ancestors AS (
                        SELECT id, parent_jurisdiction_id AS parent_id, 1 AS depth
                        FROM tax_jurisdictions
                        WHERE company_id = OLD.company_id
                          AND id = OLD.parent_jurisdiction_id

                        UNION ALL

                        SELECT parent.id, parent.parent_jurisdiction_id,
                               old_ancestors.depth + 1
                        FROM old_ancestors
                        JOIN tax_jurisdictions parent
                          ON parent.company_id = OLD.company_id
                         AND parent.id = old_ancestors.parent_id
                        WHERE old_ancestors.parent_id IS NOT NULL
                          AND old_ancestors.depth < {_MAX_DEPTH}
                    ),
                    new_ancestors AS (
                        SELECT id, parent_jurisdiction_id AS parent_id, 1 AS depth
                        FROM tax_jurisdictions
                        WHERE company_id = NEW.company_id
                          AND id = NEW.parent_jurisdiction_id

                        UNION ALL

                        SELECT parent.id, parent.parent_jurisdiction_id,
                               new_ancestors.depth + 1
                        FROM new_ancestors
                        JOIN tax_jurisdictions parent
                          ON parent.company_id = NEW.company_id
                         AND parent.id = new_ancestors.parent_id
                        WHERE new_ancestors.parent_id IS NOT NULL
                          AND new_ancestors.depth < {_MAX_DEPTH}
                    ),
                    affected AS (
                        (
                            SELECT id FROM old_ancestors
                            EXCEPT
                            SELECT id FROM new_ancestors
                        )
                        UNION
                        (
                            SELECT id FROM new_ancestors
                            EXCEPT
                            SELECT id FROM old_ancestors
                        )
                    )
                    SELECT 1
                    FROM tax_rule_scopes scope
                    JOIN tax_rule_set_versions version
                      ON version.company_id = scope.company_id
                     AND version.id = scope.tax_rule_set_version_id
                    WHERE scope.company_id = OLD.company_id
                      AND scope.scope_type = 'JURISDICTION'
                      AND scope.jurisdiction_id IN (SELECT id FROM affected)
                      AND version.status IN (
                          'PENDING_APPROVAL',
                          'PUBLISHED',
                          'SUPERSEDED'
                      )
               ) THEN
                RAISE EXCEPTION
                    'tax jurisdiction topology is referenced by immutable tax version'
                    USING ERRCODE = '55000';
            END IF;

            RETURN NEW;
        END;
        $$;
        """
    )


def upgrade() -> None:
    _preflight_existing_hierarchy()
    _install_hierarchy_guard()
    _install_identity_guard()


def downgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION guard_tax_jurisdiction_cycle()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.parent_jurisdiction_id IS NULL THEN
                RETURN NEW;
            END IF;
            IF NEW.parent_jurisdiction_id = NEW.id THEN
                RAISE EXCEPTION 'tax jurisdiction cycle detected' USING ERRCODE = '23514';
            END IF;
            IF EXISTS (
                WITH RECURSIVE ancestors AS (
                    SELECT id, parent_jurisdiction_id, ARRAY[id] AS path
                    FROM tax_jurisdictions
                    WHERE company_id = NEW.company_id
                      AND id = NEW.parent_jurisdiction_id
                    UNION ALL
                    SELECT parent.id, parent.parent_jurisdiction_id,
                           ancestors.path || parent.id
                    FROM tax_jurisdictions parent
                    JOIN ancestors ON parent.id = ancestors.parent_jurisdiction_id
                    WHERE parent.company_id = NEW.company_id
                      AND NOT parent.id = ANY(ancestors.path)
                      AND cardinality(ancestors.path) < 64
                )
                SELECT 1 FROM ancestors WHERE id = NEW.id
            ) THEN
                RAISE EXCEPTION 'tax jurisdiction cycle detected' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute("DROP TRIGGER IF EXISTS trg_tax_jurisdiction_cycle ON tax_jurisdictions")
    op.execute(
        """
        CREATE TRIGGER trg_tax_jurisdiction_cycle
        BEFORE INSERT OR UPDATE OF parent_jurisdiction_id, company_id
        ON tax_jurisdictions
        FOR EACH ROW EXECUTE FUNCTION guard_tax_jurisdiction_cycle()
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION guard_tax_jurisdiction_identity()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF (
                NEW.code IS DISTINCT FROM OLD.code
                OR NEW.jurisdiction_type IS DISTINCT FROM OLD.jurisdiction_type
                OR NEW.country_code IS DISTINCT FROM OLD.country_code
                OR NEW.subdivision_code IS DISTINCT FROM OLD.subdivision_code
                OR NEW.locality_code IS DISTINCT FROM OLD.locality_code
                OR NEW.parent_jurisdiction_id IS DISTINCT FROM OLD.parent_jurisdiction_id
            ) AND EXISTS (
                SELECT 1 FROM tax_rule_scopes
                WHERE company_id = OLD.company_id
                  AND jurisdiction_id = OLD.id
            ) THEN
                RAISE EXCEPTION
                    'referenced tax jurisdiction identity is immutable'
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
