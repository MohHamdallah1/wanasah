"""Real PostgreSQL, isolated temporary cluster; never reads application .env.

Run under WSL with PostgreSQL 16 tools installed. The fixture retains its test directory and stops only its own server in finally.
"""
import asyncio
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import sys
import uuid

import asyncpg
import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from inventory_access import InventoryAccess, require_transfer, require_stocktake
from models import InventoryLocation, InventoryTransferHeader
from fastapi import HTTPException

TOOLS = Path('/usr/lib/postgresql/16/bin')


@pytest.fixture(scope='module')
def cluster():
    if not (TOOLS/'initdb').exists():
        pytest.fail('PostgreSQL 16 test runtime missing; this security gate cannot be skipped')
    directory = tempfile.mkdtemp(prefix='wanasah-4d-')
    if directory:
        root = Path(directory)
        def run(*args):
            subprocess.run([str(TOOLS/args[0]), *args[1:]], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        run('initdb', '-D', str(root/'data'), '-A', 'trust', '-U', 'postgres', '--no-locale')
        run('pg_ctl', '-D', str(root/'data'), '-l', str(root/'server.log'),
            '-o', f"-k {root} -h '' -p 5432", '-w', 'start')
        try:
            yield directory
        finally:
            run('pg_ctl', '-D', str(root/'data'), '-m', 'fast', '-w', 'stop')


BASE_SQL = '''
CREATE TABLE companies(id integer PRIMARY KEY);
CREATE TABLE roles(id integer PRIMARY KEY, company_id integer NOT NULL REFERENCES companies(id),
                   name text, is_system_role boolean DEFAULT false, UNIQUE(company_id,id));
CREATE TABLE permissions(id integer PRIMARY KEY, code text UNIQUE NOT NULL);
CREATE TABLE role_permissions(role_id integer REFERENCES roles(id) ON DELETE CASCADE,
    permission_id integer REFERENCES permissions(id), PRIMARY KEY(role_id,permission_id));
CREATE TABLE user_roles(id integer PRIMARY KEY, company_id integer NOT NULL, driver_id integer NOT NULL,
    role_id integer NOT NULL, FOREIGN KEY(company_id,role_id) REFERENCES roles(company_id,id));
CREATE TABLE user_location_access(id integer PRIMARY KEY, company_id integer NOT NULL,
    driver_id integer NOT NULL, location_id integer NOT NULL, role_id integer NOT NULL,
    FOREIGN KEY(company_id,role_id) REFERENCES roles(company_id,id));
CREATE TABLE inventory_locations(id integer PRIMARY KEY, company_id integer NOT NULL);
CREATE TABLE inventory_transfer_headers(id integer PRIMARY KEY, company_id integer NOT NULL,
    source_location_id integer NOT NULL, destination_location_id integer NOT NULL);
CREATE TABLE stocktake_sessions(id integer PRIMARY KEY, company_id integer NOT NULL, location_id integer NOT NULL);
INSERT INTO companies VALUES (1),(2);
INSERT INTO roles(id,company_id,name) VALUES (10,1,'Operator'),(20,2,'Operator'),(30,1,'Observer');
INSERT INTO permissions VALUES (1,'inventory.read'),(2,'transfer.send'),(3,'transfer.receive'),
    (4,'stocktake.count'),(5,'location.create'),(6,'stocktake.approve');
INSERT INTO role_permissions VALUES (10,1),(10,2),(10,4),(10,5),(20,1),(20,6),(30,3);
INSERT INTO inventory_locations VALUES (100,1),(101,1),(200,2);
INSERT INTO user_location_access VALUES (1,1,7,100,10),(2,1,7,101,30),(3,2,7,200,20);
INSERT INTO inventory_transfer_headers VALUES (1,1,100,101),(2,2,200,200);
INSERT INTO stocktake_sessions VALUES (1,1,100),(2,1,101),(3,2,200);
'''


@pytest_asyncio.fixture
async def database(cluster):
    name = 'test_' + uuid.uuid4().hex
    admin = await asyncpg.connect(host=cluster, user='postgres', database='postgres')
    await admin.execute(f'CREATE DATABASE "{name}"')
    connection = await asyncpg.connect(host=cluster, user='postgres', database=name)
    await connection.execute(BASE_SQL)
    migration = Path(__file__).with_name('stage4d_role_permissions.sql').read_text()
    await connection.execute(migration)
    engine = create_async_engine('postgresql+asyncpg://postgres@/'+name, connect_args={'host': cluster})
    try:
        yield connection, engine, migration
    finally:
        await engine.dispose()
        await connection.close()
        await admin.close()


@pytest.mark.asyncio
async def test_migration_preserves_grants_and_is_repeatable(database):
    conn, _, migration = database
    assert await conn.fetchval('SELECT count(*) FROM role_permissions') == 7
    assert await conn.fetchval('SELECT count(*) FROM role_permissions WHERE company_id=2') == 2
    await conn.execute(migration)
    assert await conn.fetchval('SELECT count(*) FROM role_permissions') == 7
    with pytest.raises(asyncpg.ForeignKeyViolationError):
        await conn.execute('INSERT INTO role_permissions VALUES (20,2,1)')


@pytest.mark.asyncio
async def test_rls_select_insert_update_delete_and_no_tenant(database):
    conn, _, _ = database
    role = 'app_' + uuid.uuid4().hex
    await conn.execute(f'CREATE ROLE "{role}" NOLOGIN NOSUPERUSER NOBYPASSRLS')
    await conn.execute(f'GRANT USAGE ON SCHEMA public TO "{role}"')
    await conn.execute(f'GRANT SELECT,INSERT,UPDATE,DELETE ON role_permissions TO "{role}"')
    await conn.execute(f'SET ROLE "{role}"')
    assert await conn.fetchval('SELECT count(*) FROM role_permissions') == 0
    await conn.execute("SELECT set_config('app.current_tenant','1',false)")
    assert [r['company_id'] for r in await conn.fetch('SELECT DISTINCT company_id FROM role_permissions')] == [1]
    assert await conn.execute('DELETE FROM role_permissions WHERE company_id=2') == 'DELETE 0'
    assert await conn.execute('UPDATE role_permissions SET company_id=1 WHERE company_id=2') == 'UPDATE 0'
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await conn.execute('INSERT INTO role_permissions(company_id,role_id,permission_id) VALUES (2,20,3)')
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await conn.execute('UPDATE role_permissions SET company_id=2 WHERE role_id=10')
    await conn.execute('RESET ROLE')


@pytest.mark.asyncio
async def test_scope_permissions_revocation_and_company_roles(database):
    conn, engine, _ = database
    async with AsyncSession(engine) as db:
        access = InventoryAccess(db, SimpleNamespace(id=7, company_id=1, is_admin=False))
        await access.require('inventory.read', 100)
        for code, location in [('inventory.read',101), ('inventory.read',200), ('stocktake.approve',100), ('location.create',100)]:
            with pytest.raises(HTTPException):
                await access.require(code, location)
        assert list((await db.scalars(select(InventoryLocation.id).where(
            InventoryLocation.company_id==1, access.location_filter('inventory.read')))).all()) == [100]
        await require_transfer(access, 'transfer.send', 1, 'source')
        await require_transfer(access, 'transfer.receive', 1, 'destination')
        with pytest.raises(HTTPException):
            await require_transfer(access, 'transfer.send', 1, 'destination')
        with pytest.raises(HTTPException):
            await require_transfer(access, 'transfer.send', 2, 'source')
        await require_stocktake(access, 'stocktake.count', 1)
        with pytest.raises(HTTPException):
            await require_stocktake(access, 'stocktake.count', 2)
        with pytest.raises(HTTPException):
            await require_stocktake(access, 'stocktake.count', 3)
        await conn.execute('DELETE FROM user_location_access WHERE id=1')
        with pytest.raises(HTTPException):
            await access.require('inventory.read',100)
        await conn.execute('INSERT INTO user_roles VALUES (1,1,7,10)')
        await access.require('inventory.read',101)
        await access.require('location.create')
        with pytest.raises(HTTPException):
            await access.require('inventory.read',200)


@pytest.mark.asyncio
async def test_legacy_admin_remains_tenant_scoped(database):
    _, engine, _ = database
    async with AsyncSession(engine) as db:
        access = InventoryAccess(db, SimpleNamespace(id=8, company_id=1, is_admin=True))
        await access.require('stocktake.approve',101)
        with pytest.raises(HTTPException) as error:
            await access.require('stocktake.approve',200)
        assert error.value.status_code == 404
