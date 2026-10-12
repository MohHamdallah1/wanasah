"""Real PostgreSQL acceptance gate for canonical Backoffice capability access.

This gate is intentionally CI-only. It refuses to run unless pointed at the
synthetic database configured by the temporary dedicated workflow.

Run from ``wa_backend`` only after ``alembic upgrade head``::

    WANASAH_BACKOFFICE_CAPABILITY_GATE=1 \
    python tests/run_canonical_backoffice_capability_access_gate.py --run
"""
from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path
import sys

import psycopg
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
EXPECTED_DATABASE = "canonical_backoffice_capability_gate"
EXPECTED_RUNTIME = "backoffice_capability_runtime"


def _require_ci_database() -> tuple[str, str]:
    if os.environ.get("WANASAH_BACKOFFICE_CAPABILITY_GATE") != "1":
        raise RuntimeError("CI gate opt-in is required")
    raw_runtime = os.environ.get("DATABASE_URL", "")
    raw_admin = os.environ.get("DATABASE_URL_MIGRATION", "")
    if not raw_runtime or not raw_admin:
        raise RuntimeError("Synthetic CI database URLs are required")

    runtime_url = make_url(raw_runtime)
    admin_url = make_url(raw_admin)
    for url in (runtime_url, admin_url):
        if url.host not in {"127.0.0.1", "localhost"}:
            raise RuntimeError("Gate accepts localhost PostgreSQL only")
        if url.database != EXPECTED_DATABASE:
            raise RuntimeError("Gate refuses non-synthetic database names")
    if runtime_url.username != EXPECTED_RUNTIME:
        raise RuntimeError("Unexpected runtime database role")
    return raw_runtime, admin_url.set(drivername="postgresql").render_as_string(hide_password=False)


def _seed(admin_dsn: str) -> dict[str, int]:
    from domains.authorization.capabilities import PERMISSIONS

    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        def company(code: str) -> int:
            return conn.execute(
                """INSERT INTO companies(name,company_code,is_active,subscription_status,currency_code,timezone,created_at)
                   VALUES (%s,%s,true,'active','JOD','UTC',CURRENT_TIMESTAMP) RETURNING id""",
                (code, code),
            ).fetchone()[0]

        def driver(company_id: int, username: str, *, admin: bool = False) -> int:
            return conn.execute(
                """INSERT INTO drivers(company_id,username,password_hash,full_name,is_active,is_admin,created_at)
                   VALUES (%s,%s,'synthetic-not-for-login',%s,true,%s,CURRENT_TIMESTAMP) RETURNING id""",
                (company_id, username, username, admin),
            ).fetchone()[0]

        def location(company_id: int, code: str) -> int:
            return conn.execute(
                """INSERT INTO inventory_locations(company_id,name,code,location_type,is_system_managed,version,is_active,created_at,updated_at)
                   VALUES (%s,%s,%s,'WAREHOUSE',false,1,true,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP) RETURNING id""",
                (company_id, code, code),
            ).fetchone()[0]

        def role(company_id: int, name: str, codes: tuple[str, ...]) -> int:
            role_id = conn.execute(
                "INSERT INTO roles(company_id,name,is_system_role) VALUES (%s,%s,false) RETURNING id",
                (company_id, name),
            ).fetchone()[0]
            for code in codes:
                permission_id = conn.execute(
                    "INSERT INTO permissions(code) VALUES (%s) ON CONFLICT(code) DO UPDATE SET code=EXCLUDED.code RETURNING id",
                    (code,),
                ).fetchone()[0]
                conn.execute(
                    "INSERT INTO role_permissions(company_id,role_id,permission_id) VALUES (%s,%s,%s)",
                    (company_id, role_id, permission_id),
                )
            return role_id

        a, b = company("CAP-GATE-A"), company("CAP-GATE-B")
        owner_driver = driver(a, "owner-storage", admin=True)
        ordinary = driver(a, "ordinary")
        local_only = driver(a, "local-only")
        empty = driver(a, "empty")
        other_company_driver = driver(b, "other-company")

        a1, a2, a3 = location(a, "A-1"), location(a, "A-2"), location(a, "A-3")
        b1 = location(b, "B-1")

        company_a = role(a, "company-a", ("inventory.read",))
        local_a1 = role(a, "local-a1", ("transfer.send", "catalog.manage"))
        local_a2 = role(a, "local-a2", ("transfer.receive",))
        company_catalog = role(a, "company-catalog", ("catalog.manage",))
        company_b = role(b, "company-b", ("dispatch.execute", "inventory.read"))

        conn.execute(
            "INSERT INTO user_roles(company_id,driver_id,role_id) VALUES (%s,%s,%s)",
            (a, ordinary, company_a),
        )
        conn.execute(
            "INSERT INTO user_location_access(company_id,driver_id,location_id,role_id) VALUES (%s,%s,%s,%s)",
            (a, ordinary, a1, local_a1),
        )
        conn.execute(
            "INSERT INTO user_location_access(company_id,driver_id,location_id,role_id) VALUES (%s,%s,%s,%s)",
            (a, ordinary, a2, local_a2),
        )
        conn.execute(
            "INSERT INTO user_location_access(company_id,driver_id,location_id,role_id) VALUES (%s,%s,%s,%s)",
            (a, local_only, a1, local_a1),
        )
        conn.execute(
            "INSERT INTO user_roles(company_id,driver_id,role_id) VALUES (%s,%s,%s)",
            (b, other_company_driver, company_b),
        )

        # Keep every approved capability representable without granting it.
        for code in PERMISSIONS:
            conn.execute("INSERT INTO permissions(code) VALUES (%s) ON CONFLICT(code) DO NOTHING", (code,))

        return {
            "a": a, "b": b,
            "owner_driver": owner_driver,
            "ordinary": ordinary,
            "local_only": local_only,
            "empty": empty,
            "other_company_driver": other_company_driver,
            "a1": a1, "a2": a2, "a3": a3, "b1": b1,
            "company_catalog": company_catalog,
        }


async def _run(runtime_url: str, fixture: dict[str, int]) -> None:
    from domains.authorization.backoffice_access import (
        BackofficeCapabilityAccess,
        BackofficeCapabilityAccessRejected,
    )
    from domains.authorization.backoffice_subject import BackofficeAuthorizationSubject
    from domains.authorization.capabilities import COMPANY_ONLY, PERMISSIONS
    from models import InventoryLocation

    engine = create_async_engine(runtime_url, echo=False, hide_parameters=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    def subject(locator: int | None, *, owner: bool = False) -> BackofficeAuthorizationSubject:
        return BackofficeAuthorizationSubject(
            principal_id=700001,
            backoffice_user_id=800001,
            company_id=fixture["a"],
            is_company_owner=owner,
            legacy_grant_driver_id=locator,
        )

    ordinary_subject = subject(fixture["ordinary"])
    local_subject = subject(fixture["local_only"])
    empty_subject = subject(fixture["empty"])
    cross_company_locator_subject = subject(fixture["other_company_driver"])
    owner_subject = subject(None, owner=True)

    async def tenant_session(company_id: int):
        db = sessions()
        await db.begin()
        await db.execute(text("SELECT set_config('app.current_tenant', :c, true)"), {"c": str(company_id)})
        return db

    async def new_require_fails(access, code, **kwargs) -> bool:
        try:
            await access.require(code, **kwargs)
        except BackofficeCapabilityAccessRejected:
            return True
        return False

    try:
        # Canonical Owner: full approved catalog, no grant-row authority dependency.
        async with await tenant_session(fixture["a"]) as db:
            owner = BackofficeCapabilityAccess(db, owner_subject)
            assert await owner.codes() == sorted(PERMISSIONS)
            await owner.require("inventory.read")
            await owner.require("transfer.send", location_id=fixture["a1"])
            assert await new_require_fails(owner, "inventory.read", location_id=fixture["b1"])
            owner_locations = await owner.codes_by_location([fixture["a1"], fixture["a2"], fixture["b1"]])
            assert set(owner_locations) == {fixture["a1"], fixture["a2"]}
            assert all(codes == sorted(PERMISSIONS) for codes in owner_locations.values())
        print("OWNER_CANONICAL_AUTHORITY_AND_TENANT_LOCATION_FENCE=PASS", flush=True)

        # Ordinary company and exact-location grants with real SQL predicates.
        async with await tenant_session(fixture["a"]) as db:
            access = BackofficeCapabilityAccess(db, ordinary_subject)
            await access.require("inventory.read")
            assert await new_require_fails(access, "dispatch.execute")
            await access.require("transfer.send", location_id=fixture["a1"])
            assert await new_require_fails(access, "transfer.send", location_id=fixture["a2"])
            assert await new_require_fails(access, "transfer.send", location_id=fixture["b1"])

            filtered = list((await db.scalars(
                select(InventoryLocation.id)
                .where(
                    InventoryLocation.company_id == fixture["a"],
                    access.allows("transfer.send", location_id=InventoryLocation.id),
                )
                .order_by(InventoryLocation.id)
                .limit(50)
            )).all())
            assert filtered == [fixture["a1"]]
        print("ORDINARY_COMPANY_LOCATION_AND_PREPAGINATION_SQL=PASS", flush=True)

        # Company B grants cannot authorize company A, even if its legacy locator is supplied.
        async with await tenant_session(fixture["a"]) as db:
            empty = BackofficeCapabilityAccess(db, empty_subject)
            cross_company = BackofficeCapabilityAccess(db, cross_company_locator_subject)
            assert await new_require_fails(empty, "dispatch.execute", any_location=True)
            assert await new_require_fails(cross_company, "dispatch.execute", any_location=True)
            assert await new_require_fails(cross_company, "inventory.read", any_location=True)
            assert fixture["b1"] not in await empty.codes_by_location([fixture["a1"], fixture["b1"]])
        print("CROSS_COMPANY_GRANTS_AND_FOREIGN_LOCATIONS_CLOSED=PASS", flush=True)

        # COMPANY_ONLY from local assignment is ignored, company grant enables it.
        async with await tenant_session(fixture["a"]) as db:
            local = BackofficeCapabilityAccess(db, local_subject)
            assert "catalog.manage" in COMPANY_ONLY
            assert await new_require_fails(local, "catalog.manage", location_id=fixture["a1"])
            await db.execute(
                text("INSERT INTO user_roles(company_id,driver_id,role_id) VALUES (:c,:d,:r)"),
                {"c": fixture["a"], "d": fixture["local_only"], "r": fixture["company_catalog"]},
            )
            await db.flush()
            await local.require("catalog.manage", location_id=fixture["a1"])
        print("COMPANY_ONLY_LOCATION_EXCLUSION_AND_COMPANY_GRANT=PASS", flush=True)

        # any_location exact existing semantics.
        async with await tenant_session(fixture["a"]) as db:
            local = BackofficeCapabilityAccess(db, local_subject)
            empty = BackofficeCapabilityAccess(db, empty_subject)
            await local.require("transfer.send", any_location=True)
            assert await new_require_fails(empty, "transfer.send", any_location=True)
        print("ANY_LOCATION_SEMANTICS=PASS", flush=True)

        # require_all ALL semantics, then grant missing B and re-check.
        async with await tenant_session(fixture["a"]) as db:
            access = BackofficeCapabilityAccess(db, ordinary_subject)
            try:
                await access.require_all(("inventory.read", "dispatch.execute"), any_location=True)
            except BackofficeCapabilityAccessRejected:
                pass
            else:
                raise AssertionError("require_all accepted missing capability")

            dispatch_role = (
                await db.execute(
                    text("INSERT INTO roles(company_id,name,is_system_role) VALUES (:c,'dispatch-temp',false) RETURNING id"),
                    {"c": fixture["a"]},
                )
            ).scalar_one()
            dispatch_permission = (
                await db.execute(
                    text("INSERT INTO permissions(code) VALUES ('dispatch.execute') ON CONFLICT(code) DO UPDATE SET code=EXCLUDED.code RETURNING id")
                )
            ).scalar_one()
            await db.execute(
                text("INSERT INTO role_permissions(company_id,role_id,permission_id) VALUES (:c,:r,:p)"),
                {"c": fixture["a"], "r": dispatch_role, "p": dispatch_permission},
            )
            await db.execute(
                text("INSERT INTO user_roles(company_id,driver_id,role_id) VALUES (:c,:d,:r)"),
                {"c": fixture["a"], "d": fixture["ordinary"], "r": dispatch_role},
            )
            await db.flush()
            await access.require_all(("inventory.read", "dispatch.execute"), any_location=True)
        print("REQUIRE_ALL_ALL_SEMANTICS=PASS", flush=True)

        # codes(): canonical bounded catalog and company/local union, local COMPANY_ONLY excluded.
        async with await tenant_session(fixture["a"]) as db:
            access = BackofficeCapabilityAccess(db, ordinary_subject)
            global_codes = set(await access.codes())
            a1_codes = set(await access.codes(location_id=fixture["a1"]))
            a2_codes = set(await access.codes(location_id=fixture["a2"]))
            assert global_codes == {"inventory.read"}
            assert a1_codes == {"inventory.read", "transfer.send"}
            assert a2_codes == {"inventory.read", "transfer.receive"}
            assert "catalog.manage" not in a1_codes
            assert global_codes | a1_codes | a2_codes <= PERMISSIONS
        print("CODES_CANONICAL_BOUND_AND_UNION=PASS", flush=True)

        # codes_by_location(): global permissions everywhere visible; local only exact location.
        async with await tenant_session(fixture["a"]) as db:
            access = BackofficeCapabilityAccess(db, ordinary_subject)
            by_location = await access.codes_by_location(
                [fixture["a1"], fixture["a2"], fixture["a3"], fixture["b1"]]
            )
            assert set(by_location) == {fixture["a1"], fixture["a2"], fixture["a3"]}
            assert set(by_location[fixture["a1"]]) == {"inventory.read", "transfer.send"}
            assert set(by_location[fixture["a2"]]) == {"inventory.read", "transfer.receive"}
            assert set(by_location[fixture["a3"]]) == {"inventory.read"}

            local = BackofficeCapabilityAccess(db, local_subject)
            local_by = await local.codes_by_location([fixture["a1"], fixture["a2"], fixture["a3"], fixture["b1"]])
            assert set(local_by) == {fixture["a1"]}
            assert set(local_by[fixture["a1"]]) == {"transfer.send"}
        print("CODES_BY_LOCATION_EXACT_SCOPE_AND_OMISSIONS=PASS", flush=True)

        # Final source guard: no legacy authority dependency, bridge authority or ID aliasing.
        source = (BACKEND / "domains" / "authorization" / "backoffice_access.py").read_text(encoding="utf-8")
        forbidden = (
            "from models import Driver",
            ".is_admin",
            "legacy_full_authority",
            "classification",
            "driver_id = self.subject.principal_id",
            "driver_id = self.subject.backoffice_user_id",
            "subject.principal_id ==",
            "subject.backoffice_user_id ==",
        )
        for needle in forbidden:
            assert needle not in source, needle
        print("SOURCE_GUARDS=PASS", flush=True)
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()
    if not args.run:
        parser.error("--run is required")
    if Path.cwd().resolve() != BACKEND:
        raise RuntimeError("Run from wa_backend only")

    runtime_url, admin_dsn = _require_ci_database()
    fixture = _seed(admin_dsn)
    asyncio.run(_run(runtime_url, fixture))
    print("CANONICAL_BACKOFFICE_CAPABILITY_ACCESS_POSTGRES_GATE=PASS", flush=True)


if __name__ == "__main__":
    main()
