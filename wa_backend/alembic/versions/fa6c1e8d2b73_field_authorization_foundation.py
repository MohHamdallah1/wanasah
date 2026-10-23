"""Persist the approved FIELD V1 assignment foundation, without enforcement.

Revision ID: fa6c1e8d2b73
Revises: 9c4f8a2d7e31

The protected system-role row is the one-time backfill marker. Only INSERT of
that row can seed existing representatives. Re-running the data step never
repairs/recreates assignments on an existing role, including deliberate revokes.
No startup hook, legacy Driver read or blanket permission grant is installed.
"""
import os
import re

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine import make_url

revision = "fa6c1e8d2b73"
down_revision = "9c4f8a2d7e31"
branch_labels = None
depends_on = None

# Frozen migration data: do not import a future mutable Runtime catalog.
FIELD_CODES = (
    "work_session.read", "work_session.execute", "visit.read", "visit.execute",
    "inventory.read", "transfer.read", "transfer.receive", "transfer.reject",
    "catalog.read", "pricing.view", "reconciliation.execute", "shop.create",
)
NEW_CODES = ("work_session.execute", "visit.execute", "shop.create")
SYSTEM_KEY = "FIELD_REPRESENTATIVE_V1"


def _runtime_role():
    raw = os.environ.get("DATABASE_URL", "")
    role = make_url(raw).username if raw else None
    if not role or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", role):
        raise RuntimeError("Restricted runtime database role is required.")
    row = op.get_bind().execute(sa.text(
        "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname=:role"
    ), {"role": role}).mappings().one_or_none()
    if row is None or row["rolsuper"] or row["rolbypassrls"]:
        raise RuntimeError("Runtime must not be superuser or BYPASSRLS.")
    return '"' + role + '"'


def _provision_and_backfill():
    """Migration-only, transaction-owned; role existence permanently prevents reseeding.

    Fail on a name collision rather than adopting a human-created role. Explicit
    company predicates and tenant context protect every tenant-owned statement.
    New representative creation remains the separately owned Phase 2 transaction.
    """
    bind = op.get_bind()
    previous = bind.scalar(sa.text("SELECT current_setting('app.current_tenant', true)"))
    missing = set(FIELD_CODES) - set(bind.scalars(sa.text(
        "SELECT code FROM permissions WHERE code IN :codes"
    ).bindparams(sa.bindparam("codes", expanding=True)), {"codes": FIELD_CODES}))
    if missing:
        raise RuntimeError("FIELD permission catalog is incomplete.")
    companies = bind.scalars(sa.text("SELECT id FROM companies ORDER BY id")).all()
    for company_id in companies:
        bind.execute(sa.text("SELECT set_config('app.current_tenant', :tenant, true)"),
                     {"tenant": str(company_id)})
        role_id = bind.scalar(sa.text("""
            INSERT INTO roles(company_id, name, is_system_role, system_key)
            VALUES (:company, 'FIELD_REPRESENTATIVE_V1', true, :key)
            ON CONFLICT (company_id, system_key) DO NOTHING RETURNING id
        """), {"company": company_id, "key": SYSTEM_KEY})
        if role_id is None:
            continue
        bind.execute(sa.text("""
            INSERT INTO role_permissions(company_id, role_id, permission_id)
            SELECT :company, :role, id FROM permissions WHERE code IN :codes
        """).bindparams(sa.bindparam("codes", expanding=True)),
                     {"company": company_id, "role": role_id, "codes": FIELD_CODES})
        bind.execute(sa.text("""
            INSERT INTO field_representative_roles(company_id, field_representative_id, role_id)
            SELECT company_id, id, :role FROM field_representatives
            WHERE company_id=:company
            ON CONFLICT DO NOTHING
        """), {"company": company_id, "role": role_id})
    # Restore only after success; on failure the caller must roll back the whole
    # migration transaction (including tenant context), preserving the SQL cause.
    bind.execute(sa.text("SELECT set_config('app.current_tenant', :tenant, true)"),
                 {"tenant": previous or ""})


def _install_system_role_guards():
    codes = ", ".join("'" + code + "'" for code in FIELD_CODES)
    op.execute("""
        CREATE FUNCTION public.guard_field_system_role_identity() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.system_key = 'FIELD_REPRESENTATIVE_V1' THEN
                RAISE EXCEPTION 'Protected FIELD system role identity' USING ERRCODE='42501';
            END IF;
            IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
            IF NEW.system_key IS NOT NULL THEN
                RAISE EXCEPTION 'Cannot promote an existing role to a system identity' USING ERRCODE='42501';
            END IF;
            RETURN NEW;
        END; $$;
    """)
    op.execute("""
        CREATE TRIGGER field_system_role_identity
        BEFORE UPDATE OR DELETE ON public.roles FOR EACH ROW
        EXECUTE FUNCTION public.guard_field_system_role_identity();
    """)
    # Existing ordinary/system Backoffice roles remain outside these guards.
    # Runtime provisioning may INSERT a new exact bundle in one transaction;
    # existing default permissions cannot be edited or deleted, even via other APIs.
    op.execute(f"""
        CREATE FUNCTION public.guard_field_system_role_permissions() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE protected boolean; capability text;
        BEGIN
            IF TG_OP IN ('UPDATE', 'DELETE') THEN
                SELECT system_key = 'FIELD_REPRESENTATIVE_V1' INTO protected
                  FROM public.roles WHERE company_id=OLD.company_id AND id=OLD.role_id;
                IF protected THEN
                    RAISE EXCEPTION 'Protected FIELD system role permissions' USING ERRCODE='42501';
                END IF;
            END IF;
            IF TG_OP IN ('INSERT', 'UPDATE') THEN
                SELECT system_key = 'FIELD_REPRESENTATIVE_V1' INTO protected
                  FROM public.roles WHERE company_id=NEW.company_id AND id=NEW.role_id;
                IF protected THEN
                    SELECT code INTO capability FROM public.permissions WHERE id=NEW.permission_id;
                    IF capability IS NULL OR capability NOT IN ({codes}) THEN
                        RAISE EXCEPTION 'Invalid FIELD system role permission' USING ERRCODE='42501';
                    END IF;
                END IF;
                RETURN NEW;
            END IF;
            RETURN OLD;
        END; $$;
    """)
    op.execute("""
        CREATE TRIGGER field_system_role_permissions
        BEFORE INSERT OR UPDATE OR DELETE ON public.role_permissions FOR EACH ROW
        EXECUTE FUNCTION public.guard_field_system_role_permissions();
    """)
    op.execute(f"""
        CREATE FUNCTION public.check_field_system_role_bundle() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE actual integer;
        BEGIN
            IF NEW.system_key = 'FIELD_REPRESENTATIVE_V1' THEN
                SELECT count(*) INTO actual FROM public.role_permissions rp
                  JOIN public.permissions p ON p.id=rp.permission_id
                  WHERE rp.company_id=NEW.company_id AND rp.role_id=NEW.id
                    AND p.code IN ({codes});
                IF actual <> 12 THEN
                    RAISE EXCEPTION 'FIELD system role requires the exact twelve capabilities'
                        USING ERRCODE='23514';
                END IF;
            END IF;
            RETURN NULL;
        END; $$;
    """)
    op.execute("""
        CREATE CONSTRAINT TRIGGER field_system_role_exact_bundle
        AFTER INSERT ON public.roles DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
        EXECUTE FUNCTION public.check_field_system_role_bundle();
    """)
    op.execute(f"""
        CREATE FUNCTION public.guard_field_catalog_identity() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.code IN ({codes}) THEN
                RAISE EXCEPTION 'Protected FIELD capability identity' USING ERRCODE='42501';
            END IF;
            IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
        END; $$;
    """)
    op.execute("""
        CREATE TRIGGER field_catalog_identity
        BEFORE UPDATE OR DELETE ON public.permissions FOR EACH ROW
        EXECUTE FUNCTION public.guard_field_catalog_identity();
    """)


def upgrade():
    role = _runtime_role()
    op.add_column("roles", sa.Column("system_key", sa.String(64), nullable=True))
    op.create_unique_constraint("uq_roles_company_system_key", "roles", ["company_id", "system_key"])
    op.create_check_constraint(op.f("ck_roles_role_system_key"), "roles",
        "system_key IS NULL OR (system_key = 'FIELD_REPRESENTATIVE_V1' AND is_system_role IS TRUE)")
    op.create_table(
        "field_representative_roles",
        sa.Column("company_id", sa.Integer(), nullable=False, autoincrement=False),
        sa.Column("field_representative_id", sa.Integer(), nullable=False, autoincrement=False),
        sa.Column("role_id", sa.Integer(), nullable=False, autoincrement=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("company_id", "field_representative_id", "role_id",
                                name=op.f("pk_field_representative_roles")),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT",
                                name=op.f("fk_field_representative_roles_company_id_companies")),
        sa.ForeignKeyConstraint(["company_id", "field_representative_id"],
            ["field_representatives.company_id", "field_representatives.id"],
            ondelete="RESTRICT", onupdate="RESTRICT", name="fk_field_roles_tenant_representative"),
        sa.ForeignKeyConstraint(["company_id", "role_id"], ["roles.company_id", "roles.id"],
            ondelete="RESTRICT", onupdate="RESTRICT", name="fk_field_roles_tenant_role"),
    )
    op.create_index("ix_field_roles_company_role", "field_representative_roles", ["company_id", "role_id"])
    expr = "company_id = NULLIF(current_setting('app.current_tenant', true), '')::integer"
    op.execute("ALTER TABLE field_representative_roles ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE field_representative_roles FORCE ROW LEVEL SECURITY")
    for name, kind in (("tenant_access", ""), ("tenant_guard", "AS RESTRICTIVE")):
        op.execute(f"CREATE POLICY field_roles_{name} ON field_representative_roles {kind} "
                   f"USING ({expr}) WITH CHECK ({expr})")
    op.execute(f"GRANT SELECT, INSERT, DELETE ON field_representative_roles TO {role}")
    op.execute(f"REVOKE UPDATE, TRUNCATE, REFERENCES, TRIGGER ON field_representative_roles FROM {role}")
    for code in NEW_CODES:
        op.execute(sa.text("INSERT INTO permissions(code) VALUES (:code) ON CONFLICT (code) DO NOTHING")
                   .bindparams(code=code))
    # Serialize the one-time snapshot with concurrent profile/role changes.
    op.execute("LOCK TABLE companies, field_representatives, roles, role_permissions "
               "IN SHARE ROW EXCLUSIVE MODE")
    _provision_and_backfill()
    _install_system_role_guards()


def downgrade():
    # Dropping the marker could regrant revoked assignments on a later upgrade.
    raise RuntimeError("FIELD grants/backfill evidence is forward-only; use a reviewed forward migration.")
