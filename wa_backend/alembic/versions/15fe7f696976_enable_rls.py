"""Enable_RLS

Revision ID: 15fe7f696976
Revises: 4da1f4845859
Create Date: 2026-09-02 04:46:57.090093

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import os
from sqlalchemy.sql import text


# revision identifiers, used by Alembic.
revision: str = '15fe7f696976'
down_revision: Union[str, Sequence[str], None] = '4da1f4845859'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# الجداول المملوكة للمستأجر (Tenant-Owned) — يجب أن تحتوي company_id إلزامياً
TENANT_TABLES = [
    'branches', 'roles', 'user_roles', 'user_location_access', 'drivers',
    'zones', 'vehicles', 'vehicle_loads', 'work_sessions', 'session_inventory',
    'shops', 'dispatch_routes', 'visits', 'visit_items', 'visit_returns',
    'shortage_requests', 'offer_rules', 'system_audit_logs', 'inventory_transfers',
    'import_logs', 'work_break_logs', 'products', 'product_variants', 'uom_conversions',
    'system_settings'
]


def upgrade() -> None:
    conn = op.get_bind()

    # ================================================================
    # 1) دور التطبيق المقيد (غير Superuser) — هو الوحيد الذي تخضع
    #    اتصالاته لسياسات الـ RLS (السوبريوزر يتجاوزها دائماً).
    #    كلمة المرور تُقرأ من البيئة ولا تُخزَّن في هذا الملف إطلاقاً.
    # ================================================================
    app_password = os.getenv("WANASAH_APP_DB_PASSWORD")
    if not app_password:
        raise RuntimeError(
            "WANASAH_APP_DB_PASSWORD is not set in the environment - "
            "refusing to create the app role with a blind/placeholder password."
        )
    if not app_password.isalnum():
        raise RuntimeError(
            "WANASAH_APP_DB_PASSWORD must be strictly alphanumeric "
            "so it can be inlined into DDL safely."
        )

    role_exists = conn.execute(text(
        "SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'wanasah_app'"
    )).scalar()

    if not role_exists:
        conn.execute(text(
            f"CREATE ROLE wanasah_app WITH LOGIN PASSWORD '{app_password}'"
        ))
    else:
        # مزامنة كلمة المرور مع .env في كل تشغيل (idempotent)
        conn.execute(text(
            f"ALTER ROLE wanasah_app WITH LOGIN PASSWORD '{app_password}'"
        ))

    # ================================================================
    # 2) الصلاحيات: USAGE على المخطط إجباري (PG15+ يسحبه عن PUBLIC)
    #    + DEFAULT PRIVILEGES لتغطية الجداول المستقبلية تلقائياً
    # ================================================================
    conn.execute(text("GRANT USAGE ON SCHEMA public TO wanasah_app"))
    conn.execute(text("GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO wanasah_app"))
    conn.execute(text("GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO wanasah_app"))
    conn.execute(text("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO wanasah_app"))
    conn.execute(text("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO wanasah_app"))

    # ================================================================
    # 3) تفعيل وفرض RLS + سياسة العزل الصارمة لكل جدول مملوك للمستأجر
    #    الهوية تُقرأ من app.current_tenant الذي يحقنه محرك التطبيق
    #    مع كل اتصال (database.py: on_checkout).
    # ================================================================
    for table in TENANT_TABLES:
        conn.execute(text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
        # FORCE: حتى مالك الجداول (لو كان غير سوبريوزر) يخضع للسياسات
        conn.execute(text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))
        conn.execute(text(f"DROP POLICY IF EXISTS tenant_isolation_policy ON {table}"))
        # PERMISSIVE (الافتراضي): هي التي تمنح الوصول. RESTRICTIVE لا تمنح أبداً —
        # وسياسة RESTRICTIVE وحيدة بلا PERMISSIVE تعني حجب كل الصفوف للأبد.
        conn.execute(text(f"""
            CREATE POLICY tenant_isolation_policy ON {table}
            FOR ALL
            USING (company_id = NULLIF(current_setting('app.current_tenant', true), '')::integer)
            WITH CHECK (company_id = NULLIF(current_setting('app.current_tenant', true), '')::integer)
        """))


def downgrade() -> None:
    conn = op.get_bind()
    for table in TENANT_TABLES:
        conn.execute(text(f"DROP POLICY IF EXISTS tenant_isolation_policy ON {table}"))
        conn.execute(text(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY"))
        conn.execute(text(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY"))
    # ملاحظة: دور wanasah_app وصلاحياته تبقى (بنية تحتية) — إسقاطه قرار تشغيلي منفصل.
