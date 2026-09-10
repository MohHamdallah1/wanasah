"""Check/apply only the incremental role-permission migration; no schema rebuild."""
import argparse
import asyncio
from pathlib import Path
from urllib.parse import urlsplit
import asyncpg
from dotenv import dotenv_values


async def run(apply=False):
    values = dotenv_values(Path(__file__).resolve().parents[1]/'.env')
    dsn = values.get('DATABASE_URL_MIGRATION')
    if not dsn:
        raise RuntimeError('DATABASE_URL_MIGRATION is required')
    dsn = dsn.replace('postgresql+asyncpg://','postgresql://')
    # This local checkpoint must never migrate a remote production database.
    if urlsplit(dsn).hostname not in {'localhost','127.0.0.1','::1'}:
        raise RuntimeError('Local migration runner refuses remote databases')
    conn = await asyncpg.connect(dsn, timeout=10)
    try:
        tables = await conn.fetchval("SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_name IN ('roles','permissions','role_permissions')")
        if tables != 3:
            raise RuntimeError('RBAC baseline tables missing; no changes applied')
        before = await conn.fetchval('SELECT count(*) FROM role_permissions')
        column = await conn.fetchval("SELECT EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='role_permissions' AND column_name='company_id')")
        print(f'ROLE_PERMISSIONS_TENANT_COLUMN={bool(column)}')
        if apply:
            bypass = await conn.fetchval('SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname=current_user')
            if not bypass:
                raise RuntimeError('Migration connection cannot audit all tenants; no changes applied')
            await conn.execute(Path(__file__).with_name('stage4d_role_permissions.sql').read_text())
            after = await conn.fetchval('SELECT count(*) FROM role_permissions')
            if after != before:
                raise RuntimeError('Unexpected role grant row count after migration')
        state = await conn.fetchrow("SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid='public.role_permissions'::regclass")
        print(f'ROLE_PERMISSIONS_RLS={state[0]} FORCE={state[1]}')
        print('STAGE4D_DATABASE=' + ('APPLIED' if apply else 'CHECKED'))
    finally:
        await conn.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    try:
        asyncio.run(run(args.apply))
    except Exception as exc:
        # Never print the connection URL or database-driver diagnostics containing it.
        raise SystemExit(f'STAGE4D_DATABASE=FAIL ({type(exc).__name__})') from None
