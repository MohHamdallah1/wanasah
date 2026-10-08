"""Complete runtime grants and legacy tenant RLS for clean bootstrap.

Revision ID: 91d6f0e3c8a2
Revises: 7ab3d98601f6

This migration replaces the security/bootstrap work that historically lived in
``db_manager.py``.  Alembic is now the only schema authority.
"""
from __future__ import annotations

import os
import re

from alembic import op
from sqlalchemy import text
from sqlalchemy.engine import make_url


revision = "91d6f0e3c8a2"
down_revision = "7ab3d98601f6"
branch_labels = None
depends_on = None


LEGACY_TENANT_TABLES = (
    "branches",
    "dispatch_load_plan_lines",
    "dispatch_routes",
    "domain_audit_events",
    "drivers",
    "import_logs",
    "inventory_balances",
    "inventory_damage_events",
    "inventory_locations",
    "inventory_locks",
    "inventory_movement_impacts",
    "inventory_movements",
    "inventory_stock_policies",
    "inventory_transfer_headers",
    "inventory_transfer_lines",
    "offer_rules",
    "operation_idempotency",
    "override_reasons",
    "product_barcodes",
    "product_batches",
    "product_locations",
    "product_uom_conversions",
    "product_variants",
    "products",
    "role_permissions",
    "roles",
    "session_inventory_snapshots",
    "shops",
    "shortage_requests",
    "stocktake_count_attempt_lines",
    "stocktake_count_attempts",
    "stocktake_lines",
    "stocktake_sessions",
    "system_audit_logs",
    "system_settings",
    "transactional_outbox",
    "user_location_access",
    "user_roles",
    "vehicles",
    "visit_returns",
    "work_break_logs",
    "work_sessions",
    "zones",
)

RUNTIME_DML_TABLES = (
    "branches",
    "companies",
    "countries",
    "dispatch_load_plan_lines",
    "dispatch_routes",
    "drivers",
    "governorates",
    "import_logs",
    "inventory_balances",
    "inventory_damage_events",
    "inventory_locations",
    "inventory_locks",
    "inventory_movement_impacts",
    "inventory_movements",
    "inventory_stock_policies",
    "inventory_transfer_headers",
    "inventory_transfer_lines",
    "login_attempts",
    "offer_definitions",
    "offer_rules",
    "offer_version_products",
    "offer_version_scopes",
    "offer_versions",
    "operation_idempotency",
    "override_reasons",
    "permissions",
    "price_book_assignments",
    "price_book_entries",
    "price_books",
    "price_publications",
    "product_barcodes",
    "product_batches",
    "product_import_admission_rejections",
    "product_import_global_source_capacity",
    "product_import_jobs",
    "product_import_rows",
    "product_import_source_chunks",
    "product_import_sources",
    "product_import_tenant_source_capacity",
    "product_import_worker_registry",
    "product_locations",
    "product_uom_conversions",
    "product_variants",
    "products",
    "refresh_tokens",
    "role_permissions",
    "roles",
    "route_commercial_contexts",
    "sales_line_adjustments",
    "sales_line_price_components",
    "sales_line_tax_components",
    "sales_return_adjustments",
    "sales_return_documents",
    "sales_return_lines",
    "sales_return_quantity_components",
    "sales_return_tax_components",
    "sales_reward_evidence",
    "sales_visit_revisions",
    "session_inventory_snapshots",
    "shops",
    "shortage_requests",
    "stocktake_count_attempt_lines",
    "stocktake_count_attempts",
    "stocktake_lines",
    "stocktake_sessions",
    "system_settings",
    "tax_jurisdictions",
    "tax_rule_components",
    "tax_rule_scopes",
    "tax_rule_set_versions",
    "tax_rule_sets",
    "tenant_operational_policies",
    "token_blacklist",
    "transactional_outbox",
    "uom",
    "user_location_access",
    "user_roles",
    "vehicles",
    "visit_items",
    "visit_returns",
    "visits",
    "work_break_logs",
    "work_sessions",
    "zones",
)

APPEND_ONLY_AUDIT_TABLES = (
    "system_audit_logs",
    "domain_audit_events",
)


def _runtime_role() -> str:
    raw = os.getenv("DATABASE_URL")
    if not raw:
        raise RuntimeError("DATABASE_URL is required to resolve the runtime database role.")
    role = make_url(raw).username
    if not role or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", role):
        raise RuntimeError("Runtime database role could not be resolved safely.")

    row = op.get_bind().execute(
        text(
            "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = :role"
        ),
        {"role": role},
    ).mappings().one_or_none()
    if row is None:
        raise RuntimeError(f"Runtime database role {role!r} does not exist.")
    if bool(row["rolsuper"]) or bool(row["rolbypassrls"]):
        raise RuntimeError(
            "Runtime database role must not be superuser or BYPASSRLS."
        )
    return role


def _quote_role(role: str) -> str:
    return '"' + role.replace('"', '""') + '"'


def _grant_owned_sequences(table_names: tuple[str, ...], quoted_role: str) -> None:
    bind = op.get_bind()
    for table_name in table_names:
        rows = bind.execute(
            text(
                """
                SELECT pg_get_serial_sequence(
                    format('public.%I', table_name),
                    column_name
                ) AS sequence_name
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = :table_name
                  AND column_default LIKE 'nextval(%'
                """
            ),
            {"table_name": table_name},
        ).scalars().all()
        for sequence_name in rows:
            if not sequence_name:
                continue
            if not re.fullmatch(r"public\.[A-Za-z_][A-Za-z0-9_$]*", sequence_name):
                raise RuntimeError(
                    f"Unexpected sequence identifier for {table_name}: {sequence_name!r}"
                )
            op.execute(
                f"GRANT USAGE, SELECT ON SEQUENCE {sequence_name} TO {quoted_role}"
            )
            op.execute(
                f"REVOKE UPDATE ON SEQUENCE {sequence_name} FROM {quoted_role}"
            )


def _complete_legacy_rls() -> None:
    bind = op.get_bind()
    expr = (
        "company_id = "
        "NULLIF(current_setting('app.current_tenant', true), '')::integer"
    )
    for table_name in LEGACY_TENANT_TABLES:
        state = bind.execute(
            text(
                """
                SELECT c.relrowsecurity, c.relforcerowsecurity
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public' AND c.relname = :table_name
                """
            ),
            {"table_name": table_name},
        ).mappings().one_or_none()
        if state is None:
            raise RuntimeError(f"Expected tenant table is missing: {table_name}")

        if not bool(state["relrowsecurity"]):
            op.execute(f'ALTER TABLE "{table_name}" ENABLE ROW LEVEL SECURITY')
        if not bool(state["relforcerowsecurity"]):
            op.execute(f'ALTER TABLE "{table_name}" FORCE ROW LEVEL SECURITY')

        policy_count = bind.scalar(
            text(
                """
                SELECT count(*)
                FROM pg_policies
                WHERE schemaname = 'public' AND tablename = :table_name
                """
            ),
            {"table_name": table_name},
        )
        if int(policy_count or 0) == 0:
            op.execute(
                f"""
                CREATE POLICY tenant_isolation_policy
                ON "{table_name}"
                FOR ALL
                USING ({expr})
                WITH CHECK ({expr})
                """
            )


def _install_audit_append_only_guard(quoted_role: str) -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.prevent_system_audit_log_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'audit history is append-only'
                USING ERRCODE = '55000';
        END;
        $$;
        """
    )
    for table_name in APPEND_ONLY_AUDIT_TABLES:
        op.execute(
            f"DROP TRIGGER IF EXISTS trg_{table_name}_append_only "
            f"ON public.{table_name}"
        )
        op.execute(
            f"""
            CREATE TRIGGER trg_{table_name}_append_only
            BEFORE UPDATE OR DELETE OR TRUNCATE
            ON public.{table_name}
            FOR EACH STATEMENT
            EXECUTE FUNCTION public.prevent_system_audit_log_mutation()
            """
        )
        op.execute(f"REVOKE ALL ON TABLE public.{table_name} FROM {quoted_role}")
        op.execute(
            f"GRANT SELECT, INSERT ON TABLE public.{table_name} TO {quoted_role}"
        )


def upgrade() -> None:
    role = _runtime_role()
    quoted_role = _quote_role(role)

    _complete_legacy_rls()

    op.execute(f"GRANT USAGE ON SCHEMA public TO {quoted_role}")
    op.execute(f"REVOKE CREATE ON SCHEMA public FROM {quoted_role}")

    for table_name in RUNTIME_DML_TABLES:
        op.execute(
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.{table_name} "
            f"TO {quoted_role}"
        )
        op.execute(
            f"REVOKE TRUNCATE, REFERENCES, TRIGGER ON TABLE public.{table_name} "
            f"FROM {quoted_role}"
        )

    _grant_owned_sequences(
        RUNTIME_DML_TABLES + APPEND_ONLY_AUDIT_TABLES,
        quoted_role,
    )

    _install_audit_append_only_guard(quoted_role)

    op.execute(f"REVOKE ALL ON TABLE public.platform_admins FROM {quoted_role}")
    op.execute(f"GRANT SELECT ON TABLE public.platform_admins TO {quoted_role}")
    op.execute(
        f"REVOKE ALL ON SEQUENCE public.platform_admins_id_seq FROM {quoted_role}"
    )
    op.execute(f"REVOKE ALL ON TABLE public.alembic_version FROM {quoted_role}")


def downgrade() -> None:
    raise RuntimeError(
        "Refusing to downgrade the runtime-access/RLS security baseline. "
        "Restore a reviewed backup or ship an explicit forward migration instead."
    )
