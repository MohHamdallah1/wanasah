"""Serialize FIELD assignments and shared role edits; no endpoint enforcement.

Revision ID: b2f6c8e4a901
Revises: fa6c1e8d2b73
"""
from alembic import op

revision = "b2f6c8e4a901"
down_revision = "fa6c1e8d2b73"
branch_labels = None
depends_on = None

# Frozen approved catalog, not a mutable Runtime import.
FIELD_CODES = (
    "work_session.read", "work_session.execute", "visit.read", "visit.execute",
    "inventory.read", "transfer.read", "transfer.receive", "transfer.reject",
    "catalog.read", "pricing.view", "reconciliation.execute", "shop.create",
)


def upgrade():
    # Refuse enforcement over corrupt legacy assignments; never silently rewrite.
    op.execute("SET LOCAL row_security = off")
    codes = ", ".join("'" + c + "'" for c in FIELD_CODES)
    op.execute(f"""
        DO $$ BEGIN
            IF EXISTS (
                SELECT 1 FROM public.field_representative_roles f
                JOIN public.role_permissions rp ON rp.company_id=f.company_id AND rp.role_id=f.role_id
                JOIN public.permissions p ON p.id=rp.permission_id
                WHERE p.code NOT IN ({codes})
            ) THEN RAISE EXCEPTION 'Unsafe pre-existing FIELD role assignment'; END IF;
        END; $$;
    """)
    op.execute("SET LOCAL row_security = on")
    op.execute("""
        CREATE FUNCTION public.lock_field_role_policy(c integer, r integer) RETURNS void
        LANGUAGE plpgsql AS $$
        BEGIN
            -- A real row version serializes even REPEATABLE READ snapshots:
            -- a stale competing transaction must abort rather than miss a grant.
            -- Phase 1 immutable default-role identity is never updated.
            UPDATE public.roles SET name=name WHERE company_id=c AND id=r AND system_key IS NULL;
            IF NOT FOUND THEN
                PERFORM 1 FROM public.roles WHERE company_id=c AND id=r
                    AND system_key='FIELD_REPRESENTATIVE_V1' FOR KEY SHARE;
                IF NOT FOUND THEN
                    RAISE EXCEPTION 'Role unavailable' USING ERRCODE='23503';
                END IF;
            END IF;
        END; $$;
    """)
    op.execute(f"""
        CREATE FUNCTION public.guard_field_role_assignment() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            PERFORM public.lock_field_role_policy(NEW.company_id, NEW.role_id);
            IF EXISTS (
                SELECT 1 FROM public.role_permissions rp
                JOIN public.permissions p ON p.id=rp.permission_id
                WHERE rp.company_id=NEW.company_id AND rp.role_id=NEW.role_id
                  AND p.code NOT IN ({codes})
            ) THEN
                RAISE EXCEPTION 'FIELD role contains forbidden capabilities' USING ERRCODE='42501';
            END IF;
            RETURN NEW;
        END; $$;
    """)
    op.execute("""
        CREATE TRIGGER field_assignment_allowlist
        BEFORE INSERT OR UPDATE ON public.field_representative_roles FOR EACH ROW
        EXECUTE FUNCTION public.guard_field_role_assignment();
    """)
    op.execute(f"""
        CREATE FUNCTION public.guard_field_assigned_role_edit() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            PERFORM public.lock_field_role_policy(NEW.company_id, NEW.role_id);
            IF EXISTS (
                SELECT 1 FROM public.field_representative_roles
                WHERE company_id=NEW.company_id AND role_id=NEW.role_id
            ) AND EXISTS (
                SELECT 1 FROM public.permissions WHERE id=NEW.permission_id AND code NOT IN ({codes})
            ) THEN
                RAISE EXCEPTION 'FIELD-assigned role cannot escalate' USING ERRCODE='42501';
            END IF;
            RETURN NEW;
        END; $$;
    """)
    op.execute("""
        CREATE TRIGGER field_assigned_role_edit_allowlist
        BEFORE INSERT OR UPDATE ON public.role_permissions FOR EACH ROW
        EXECUTE FUNCTION public.guard_field_assigned_role_edit();
    """)


def downgrade():
    raise RuntimeError("FIELD authorization guard rollback requires a reviewed forward migration.")
