"""Read-only catalog audit on the configured local DB; never expose credentials."""
import asyncio
from pathlib import Path
from urllib.parse import urlsplit
import asyncpg
from dotenv import dotenv_values


async def main():
    values=dotenv_values(Path(__file__).resolve().parents[1]/'.env')
    for key in ['DATABASE_URL_MIGRATION','DATABASE_URL']:
        dsn=(values.get(key) or '').replace('postgresql+asyncpg://','postgresql://')
        if urlsplit(dsn).hostname not in {'localhost','127.0.0.1','::1'}:
            raise RuntimeError('Audit only permits the configured local database')
    owner=await asyncpg.connect(values['DATABASE_URL_MIGRATION'].replace('postgresql+asyncpg://','postgresql://'),timeout=10)
    try:
        rows=await owner.fetch('''
            SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity,
              EXISTS(SELECT 1 FROM pg_policy p WHERE p.polrelid=c.oid
                AND pg_get_expr(p.polqual,p.polrelid) LIKE '%app.current_tenant%'
                AND pg_get_expr(p.polwithcheck,p.polrelid) LIKE '%app.current_tenant%') AS tenant_policy
            FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='public' AND c.relkind IN ('r','p') AND EXISTS(
              SELECT 1 FROM pg_attribute a WHERE a.attrelid=c.oid AND a.attname='company_id' AND NOT a.attisdropped)
            ORDER BY c.relname
        ''')
        failures=[r['relname'] for r in rows if not (r['relrowsecurity'] and r['relforcerowsecurity'] and r['tenant_policy'])]
        print(f'TENANT_TABLES_CHECKED={len(rows)}')
        print('RLS_CATALOG_GAPS='+(','.join(failures) if failures else 'NONE'))
        role_fks=await owner.fetch("SELECT conname FROM pg_constraint WHERE conrelid='public.role_permissions'::regclass AND contype='f'")
        print('ROLE_PERMISSION_FOREIGN_KEYS='+','.join(r['conname'] for r in role_fks))
    finally:
        await owner.close()
    app=await asyncpg.connect(values['DATABASE_URL'].replace('postgresql+asyncpg://','postgresql://'),timeout=10)
    try:
        privilege=await app.fetchrow('SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user')
        print(f'APP_SUPERUSER={privilege[0]} APP_BYPASSRLS={privilege[1]}')
        await app.execute("SELECT set_config('app.current_tenant','',false)")
        visible=await app.fetchval('SELECT count(*) FROM role_permissions')
        print(f'ROLE_GRANTS_VISIBLE_WITHOUT_TENANT={visible}')
        if failures or privilege[0] or privilege[1] or visible:
            raise RuntimeError('RLS catalog audit failed')
        print('STAGE4D_RLS_CATALOG_AUDIT=PASS')
    finally:
        await app.close()

if __name__=='__main__':
    try:
        asyncio.run(main())
    except Exception as exc:
        raise SystemExit(f'STAGE4D_RLS_CATALOG_AUDIT=FAIL ({type(exc).__name__})') from None
