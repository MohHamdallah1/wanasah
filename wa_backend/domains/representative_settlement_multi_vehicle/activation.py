"""Fail closed until the ordered M04 migration and its prerequisites exist."""
from sqlalchemy import text

from .contracts import CustodyRejected


async def require_m04_schema(db):
    marker = await db.scalar(text("SELECT to_regprocedure('public.m04_custody_contract_version()')"))
    if marker is None:
        raise CustodyRejected("M04_CUSTODY_SCHEMA_NOT_READY", status=503)
    version = await db.scalar(text("SELECT public.m04_custody_contract_version()"))
    ready = await db.scalar(text("""
        SELECT COUNT(*) = 3 AND bool_and(relrowsecurity AND relforcerowsecurity)
        FROM pg_class WHERE oid IN (
          to_regclass('public.representative_vehicle_custody_checkpoints'),
          to_regclass('public.representative_vehicle_custody_checkpoint_epochs'),
          to_regclass('public.representative_vehicle_custody_checkpoint_lines'))
    """))
    # M02/M03 shared-schema prerequisites must not be silently worked around.
    keys = (await db.execute(text("""
        SELECT c.relname, array_agg(a.attname ORDER BY k.n)::text[] AS columns
        FROM pg_index i JOIN pg_class c ON c.oid=i.indrelid
        CROSS JOIN LATERAL unnest(i.indkey) WITH ORDINALITY k(attnum,n)
        JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum=k.attnum
        WHERE i.indisunique AND c.oid IN (
          'public.session_inventory_snapshots'::regclass,
          'public.stocktake_sessions'::regclass)
        GROUP BY c.relname, i.indexrelid
    """))).all() if ready and version == 1 else []
    by_table = {}
    for table, columns in keys:
        by_table.setdefault(table, []).append(set(columns))
    snapshot_key = {"company_id", "work_session_id", "location_id", "product_variant_id", "stock_status"}
    recon_key = {"company_id", "related_work_session_id", "location_id"}
    if (not ready or version != 1
            or snapshot_key not in by_table.get("session_inventory_snapshots", ())
            or recon_key not in by_table.get("stocktake_sessions", ())):
        raise CustodyRejected("M04_CUSTODY_SCHEMA_NOT_READY", status=503)
