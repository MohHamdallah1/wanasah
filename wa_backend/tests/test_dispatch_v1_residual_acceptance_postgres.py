"""#841: remaining Dispatch V1 runtime evidence, extending exact-base PR #839.

Only disposable PG16 companies, full Alembic, restricted app Bearer FastAPI HTTP.
Intentional business FAILs stay RED; do not xfail, skip, mock or weaken.
Reuses verified #837 real HTTP/role + company fixtures, never edits them.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import os
from statistics import median
from time import perf_counter
from uuid import uuid4

import pytest
from sqlalchemy import delete, event, func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import engine as http_runtime_engine
from domains.taxation.models import (
    TaxJurisdiction, TaxRuleComponent, TaxRuleScope, TaxRuleSet, TaxRuleSetVersion,
)
from domains.taxation.publishing import publish_version as publish_tax_version
from models import (
    Company, DispatchRoute, ImportLog, InventoryCostEvent, InventoryMovement,
    Permission, Role, RouteCommercialContext, Shop, ShortageRequest, SystemAuditLog,
    UserLocationAccess, UserRole, Visit, VisitItem, WorkSession, Zone, role_permissions,
)
from tests.test_inbound_no_lot_frozen_postgres import pg  # noqa: F401
from tests.test_dispatch_v1_deep_acceptance_postgres import (
    _business_state, _client, _loaded_route_prerequisites, _login, _owner,
    _simple_shop,
)
from tests.test_live_stock_v1_route_sale_unload_postgres import _seed_mobile_uom_and_field
from tests.test_live_stock_v1_quantity_reconciliation_postgres import _seed_carton_conversion


pytestmark = [
    pytest.mark.skipif(
        os.environ.get("WANASAH_DISPATCH_DEEP_PG_GATE") != "1",
        reason="Only the #839 dedicated disposable PG16/real HTTP runtime",
    ),
    pytest.mark.asyncio(loop_scope="function"),
]


async def _grant_company(gate, tenant, actor, code):
    """Explicit scoped synthetic capability. Driver is an FK, never authority."""
    async with gate.session() as db:
        permission = await db.scalar(select(Permission).where(Permission.code == code))
        assert permission is not None, f"Migration missing capability: {code}"
        role = Role(
            company_id=tenant.company_id, name=f"841 {code} {uuid4().hex[:8]}"
        )
        db.add(role)
        await db.flush()
        await db.execute(role_permissions.insert().values(
            company_id=tenant.company_id, role_id=role.id,
            permission_id=permission.id,
        ))
        db.add(UserRole(
            company_id=tenant.company_id, role_id=role.id, driver_id=actor.driver_id
        ))
        await db.commit()
        return int(role.id)


async def _grant_warehouse(gate, tenant, actor, code):
    async with gate.session() as db:
        permission = await db.scalar(select(Permission).where(Permission.code == code))
        assert permission is not None
        role = Role(company_id=tenant.company_id, name=f"841 W1 {code} {uuid4().hex[:8]}")
        db.add(role)
        await db.flush()
        await db.execute(role_permissions.insert().values(
            company_id=tenant.company_id, role_id=role.id,
            permission_id=permission.id,
        ))
        db.add(UserLocationAccess(
            company_id=tenant.company_id, role_id=role.id,
            driver_id=actor.driver_id, location_id=tenant.location_id,
        ))
        await db.commit()
        return int(role.id)


async def _active_route(gate, client, tenant, owner):
    field, zone_id, shop_id, _vehicle_loc, payload = (
        await _loaded_route_prerequisites(gate, tenant)
    )
    launched = await client.post("/dispatch/route", json=payload, headers=owner)
    assert launched.status_code == 201, launched.text
    route_id = int(launched.json()["route_id"])
    field_headers = await _login(client, gate, tenant, field, "SyntheticFixture123")
    started = await client.post("/driver/sessions/start", json={},
                                headers=field_headers)
    assert started.status_code == 201, started.text
    session_id = int(started.json()["session_id"])
    authorized = await client.put(
        f"/admin/sessions/{session_id}/authorize", headers=owner,
        json={"is_authorized": True},
    )
    assert authorized.status_code == 200, authorized.text
    async with gate.session() as db:
        visit_id = await db.scalar(select(Visit.id).where(
            Visit.company_id == tenant.company_id, Visit.shop_id == shop_id,
            Visit.work_session_id == session_id, Visit.status == "Pending",
        ))
    assert visit_id is not None, "FIELD active route requires real pending Visit"
    return field, field_headers, route_id, zone_id, shop_id, session_id, int(visit_id)


@pytest.mark.parametrize("pg", ["FIFO"], indirect=True)
@pytest.mark.parametrize("kind", ["shop", "zone"])
async def test_f08_archive_mid_active_route_cannot_mutate_custody_or_hide_outcome(pg, kind):
    """Records live FIELD/route state. Whether shop archive itself is allowed = Owner."""
    tenant = pg.tenants[0]
    async with _client() as client:
        owner = await _owner(client, pg, tenant)
        field, field_headers, route_id, zone_id, shop_id, session_id, visit_id = (
            await _active_route(pg, client, tenant, owner)
        )
        before = await _business_state(pg, tenant)
        if kind == "shop":
            response = await client.put(
                "/dispatch/shops/bulk_update", headers=owner,
                json=[{"id": str(shop_id), "archived": True}],
            )
        else:
            response = await client.delete(
                f"/dispatch/zones/{zone_id}", headers=owner,
            )
        assert response.status_code in (200, 409), (
            f"F08 unexpected archive HTTP={response.status_code} {response.text}"
        )
        after = await _business_state(pg, tenant)
        async with pg.session() as db:
            visit = await db.get(Visit, visit_id)
            shop = await db.get(Shop, shop_id)
            zone = await db.get(Zone, zone_id)
            route = await db.get(DispatchRoute, route_id)
            session = await db.get(WorkSession, session_id)
            details = dict(
                http=response.status_code, visit=visit.status,
                shop_archived=bool(shop.is_archived), zone_active=bool(zone.is_active),
                route_status=route.status, work_session_ended=bool(session.end_time),
            )
        print(f"F08 kind={kind} ACTUAL={details} before={before} after={after} "
              "archive permission policy=OWNER_DECISION")
        assert all(after[key] == before[key] for key in
                   ("inventory_movements", "inventory_cost_events", "physical")), (
            f"F08 P0 archive mutated physical/cost without FIELD sale: {before} -> {after}"
        )
        if response.status_code == 409:
            assert not details["shop_archived"] and details["visit"] == "Pending"
        else:
            assert details["shop_archived"] and details["visit"] == "Cancelled"
            # A cancelled visit may never be completed via a stale FIELD action.
            stale = await client.put(
                f"/visits/{visit_id}", headers=field_headers,
                json={"request_id": str(uuid4()), "outcome": "Sale",
                      "cart_items": [{"product_variant_id": tenant.variant_id,
                                      "quantity": 0, "packs_quantity": 1}],
                      "cash_collected": "0", "debt_paid": "0"},
            )
            print(f"F08 FIELD-after-archive HTTP={stale.status_code} body={stale.text[:300]}")
            assert stale.status_code in (403, 404, 409), (
                f"F08 P0 cancelled visit executed after archive: {stale.status_code}"
            )
            assert await _business_state(pg, tenant) == after


@pytest.mark.parametrize("pg", ["FIFO"], indirect=True)
async def test_f12_active_route_tax_jurisdiction_change_uses_published_rule_or_blocks(pg):
    """Real published A=0% vs B=10%. Records SELECTED FROZEN commercial evidence."""
    tenant = pg.tenants[0]
    async with _client() as client:
        owner = await _owner(client, pg, tenant)
        # Existing helper publishes A zero tax and a 1.000-per-base-unit price.
        field, zone_id, shop_id, vehicle_location, launch = (
            await _loaded_route_prerequisites(pg, tenant)
        )
        # Actual FIELD carton resolution requires an explicitly authored UOM
        # conversion. The initial #841 run was blocked before tax evaluation
        # (DRIVER_MOBILE_CARTON_UOM_UNRESOLVED); add only legitimate test master.
        await _seed_carton_conversion(pg, tenant)
        async with pg.session() as db:
            a_jur = await db.scalar(select(Shop.tax_jurisdiction_id).where(
                Shop.company_id == tenant.company_id, Shop.id == shop_id
            ))
            earlier = datetime.now(timezone.utc) - timedelta(days=4)
            suffix = uuid4().hex[:10].upper()
            b = TaxJurisdiction(
                company_id=tenant.company_id, code="841B-" + suffix,
                name="Synthetic jurisdiction B", jurisdiction_type="COUNTRY",
                country_code="QA", created_by=tenant.owner.driver_id, is_active=True,
            )
            ruleset = TaxRuleSet(
                company_id=tenant.company_id, code="841TAX-" + suffix,
                name="Synthetic ten-percent proof", created_by=tenant.owner.driver_id,
            )
            db.add_all([b, ruleset])
            await db.flush()
            version = TaxRuleSetVersion(
                company_id=tenant.company_id, tax_rule_set_id=ruleset.id,
                revision=2, definition_version=1, status="DRAFT",
                price_mode="EXCLUSIVE", priority=0,
                effective_from=earlier, effective_to=None,
                created_by=tenant.owner.driver_id, request_id=uuid4(),
            )
            db.add(version)
            await db.flush()
            db.add_all([
                TaxRuleComponent(
                    company_id=tenant.company_id,
                    tax_rule_set_version_id=version.id,
                    component_code="TEN", name="Synthetic 10%",
                    sequence=1, rate=Decimal("0.10"), basis_mode="TAXABLE_BASE",
                ),
                TaxRuleScope(
                    company_id=tenant.company_id,
                    tax_rule_set_version_id=version.id,
                    scope_type="JURISDICTION", jurisdiction_id=b.id,
                ),
            ])
            await db.flush()
            published = await publish_tax_version(
                db, company_id=tenant.company_id,
                actor_id=tenant.owner.driver_id,
                version_id=version.id, expected_version=version.version,
            )
            assert published.status == "PUBLISHED"
            b_jur = int(b.id)
            await db.commit()

        launched = await client.post("/dispatch/route", headers=owner, json=launch)
        assert launched.status_code == 201, launched.text
        route_id = int(launched.json()["route_id"])
        async with pg.session() as db:
            commercial = await db.scalar(select(RouteCommercialContext).where(
                RouteCommercialContext.company_id == tenant.company_id,
                RouteCommercialContext.dispatch_route_id == route_id,
            ))
            assert commercial is not None
            locked_id, locked_tax_rev = int(commercial.id), int(commercial.tax_ruleset_version)

        field_headers = await _login(client, pg, tenant, field, "SyntheticFixture123")
        started = await client.post("/driver/sessions/start", headers=field_headers, json={})
        assert started.status_code == 201, started.text
        session_id = int(started.json()["session_id"])
        auth = await client.put(f"/admin/sessions/{session_id}/authorize",
                                headers=owner, json={"is_authorized": True})
        assert auth.status_code == 200, auth.text
        async with pg.session() as db:
            visit_id = await db.scalar(select(Visit.id).where(
                Visit.company_id == tenant.company_id,
                Visit.shop_id == shop_id, Visit.work_session_id == session_id,
                Visit.status == "Pending",
            ))
        assert visit_id is not None
        moved = await client.put(f"/dispatch/shops/{shop_id}", headers=owner,
                                  json={"taxJurisdictionId": b_jur})
        assert moved.status_code in (200, 409), moved.text
        before = await _business_state(pg, tenant)
        sale = await client.put(
            f"/visits/{visit_id}", headers=field_headers,
            json={"request_id": str(uuid4()), "outcome": "Sale",
                  "cart_items": [{"product_variant_id": tenant.variant_id,
                                  "quantity": 0, "packs_quantity": 10}],
                  "returns": [], "cash_collected": "11", "debt_paid": "0"},
        )
        after = await _business_state(pg, tenant)
        async with pg.session() as db:
            commercial = await db.get(RouteCommercialContext, locked_id)
            shop = await db.get(Shop, shop_id)
            visit = await db.get(Visit, visit_id)
            lines = (await db.scalars(select(VisitItem).where(
                VisitItem.company_id == tenant.company_id,
                VisitItem.visit_id == visit_id
            ))).all()
            details = dict(
                original_jurisdiction=a_jur, new_jurisdiction=b_jur,
                shop_jurisdiction=shop.tax_jurisdiction_id,
                update_http=moved.status_code, sale_http=sale.status_code,
                commercial_context_id=locked_id,
                tax_revision_before=locked_tax_rev,
                tax_revision_after=commercial.tax_ruleset_version,
                visit_status=visit.status, visit_tax=str(visit.tax_amount or 0),
                line_taxes=[str(x.tax_amount) for x in lines],
                tax_snapshots=[x.tax_snapshot for x in lines],
                cost_events_delta=after["inventory_cost_events"] - before["inventory_cost_events"],
            )
        print(f"F12 ACTUAL={details} sale_body={sale.text[:600]} "
              "live tax jurisdiction change policy=OWNER_DECISION")
        assert commercial.tax_ruleset_version == locked_tax_rev, (
            "F12 P0 frozen published commercial ceiling mutated during route"
        )
        if sale.status_code == 200:
            assert after["inventory_cost_events"] == before["inventory_cost_events"] + 1
            assert visit.status == "Completed" and len(lines) == 1
            assert lines[0].tax_snapshot is not None
            assert lines[0].commercial_context_id == locked_id
            # These are the exact *synthetic published rates* we controlled, not guessed law.
            expected_tax = Decimal("1.000") if moved.status_code == 200 else Decimal("0")
            assert Decimal(visit.tax_amount) == expected_tax, (
                f"F12 P0 tax reconciliation expected={expected_tax}, observed={visit.tax_amount}, {details}"
            )
        else:
            assert sale.status_code in (403, 409), sale.text
            assert after == before, "F12 blocked commercial sale mutated inventory/cost"


@pytest.mark.parametrize("pg", ["FIFO"], indirect=True)
async def test_f09_bulk_import_same_payload_retry_never_creates_duplicate_shops(pg):
    """Actual lost-success POST, two distinct no-phone/no-map Shops, durable ImportLog."""
    tenant = pg.tenants[0]
    zone_id, _shop = await _simple_shop(pg, tenant)
    tag = uuid4().hex[:9]
    names = [f"841 Import A {tag}", f"841 Import B {tag}"]
    payload = {
        "zoneId": zone_id, "fileName": f"841-lost-{tag}.csv",
        "shops": [{"name": name, "phone": "", "mapLink": ""} for name in names],
    }
    async with _client() as client:
        owner = await _owner(client, pg, tenant)
        first = await client.post("/dispatch/shops/bulk_import", headers=owner,
                                  json=payload)
        assert first.status_code == 201, first.text
        # Exact same successful file submission after response loss.
        replay = await client.post("/dispatch/shops/bulk_import", headers=owner,
                                   json=payload)
        async with pg.session() as db:
            shops = (await db.execute(select(Shop.name, func.count(Shop.id)).where(
                Shop.company_id == tenant.company_id,
                Shop.name.in_(names),
            ).group_by(Shop.name))).all()
            logs = (await db.execute(select(
                ImportLog.id, ImportLog.total_records,
                ImportLog.success_count, ImportLog.status,
            ).where(
                ImportLog.company_id == tenant.company_id,
                ImportLog.file_name == payload["fileName"],
            ).order_by(ImportLog.id))).all()
        counts = {name: int(count) for name, count in shops}
        log_rows = [tuple(row) for row in logs]
        print(f"F09-import HTTP={first.status_code}/{replay.status_code}, "
              f"shop_counts={counts}, logs={log_rows}, responses={first.text}/{replay.text}")
        assert replay.status_code == 201
        assert all(counts.get(name) == 1 for name in names), (
            f"F09 P1 duplicate shops on exact bulk import retry: {counts}, logs={log_rows}"
        )


@pytest.mark.parametrize("pg", ["FIFO"], indirect=True)
async def test_f09_import_invalid_item_rejected_as_whole_without_import_log(pg):
    tenant = pg.tenants[0]
    zone_id, _shop = await _simple_shop(pg, tenant)
    good_name = "841 valid should not persist " + uuid4().hex[:10]
    async with _client() as client:
        owner = await _owner(client, pg, tenant)
        before = await _business_state(pg, tenant)
        bad = await client.post(
            "/dispatch/shops/bulk_import", headers=owner,
            json={"zoneId": zone_id, "fileName": "841-invalid.csv",
                  "shops": [{"name": good_name}, {"name": ""}]},
        )
        assert bad.status_code == 422, bad.text
        async with pg.session() as db:
            rows = int(await db.scalar(select(func.count()).select_from(Shop).where(
                Shop.company_id == tenant.company_id, Shop.name == good_name
            )) or 0)
            logs = int(await db.scalar(select(func.count()).select_from(ImportLog).where(
                ImportLog.company_id == tenant.company_id,
                ImportLog.file_name == "841-invalid.csv",
            )) or 0)
        print(f"F09-invalid status={bad.status_code} created_shops={rows} import_logs={logs}")
        assert rows == 0 and logs == 0
        assert await _business_state(pg, tenant) == before


@pytest.mark.parametrize("pg", ["FIFO"], indirect=True)
async def test_f10_stale_credit_cap_and_metadata_two_authorized_backoffice_actors(pg):
    """New source of financial loss: old cap in metadata-only form after other actor updated cap."""
    tenant = pg.tenants[0]
    zone_id, shop_id = await _simple_shop(pg, tenant, debt_limit="150")
    await _grant_company(pg, tenant, tenant.ordinary, "dispatch.execute")
    async with _client() as client:
        owner = await _owner(client, pg, tenant)
        ordinary = await _login(client, pg, tenant, tenant.ordinary, "SyntheticFixture123")
        first = await client.put(
            f"/dispatch/shops/{shop_id}", headers=owner,
            json={"maxDebtLimit": "75.125"},
        )
        assert first.status_code == 200, first.text
        async with pg.session() as db:
            before_cap = Decimal(await db.scalar(select(Shop.max_debt_limit).where(
                Shop.company_id == tenant.company_id, Shop.id == shop_id
            )))
            audit_before = int(await db.scalar(select(func.count()).select_from(
                SystemAuditLog).where(
                SystemAuditLog.company_id == tenant.company_id,
                SystemAuditLog.target_id == f"Shop_{shop_id}",
            )) or 0)
        assert before_cap == Decimal("75.125")
        stale = await client.put(
            f"/dispatch/shops/{shop_id}", headers=ordinary,
            json={"name": "841 name-only stale form", "zoneId": zone_id,
                  "initialDebt": "0", "maxDebtLimit": "150"},
        )
        assert stale.status_code == 200, stale.text
        async with pg.session() as db:
            cap = Decimal(await db.scalar(select(Shop.max_debt_limit).where(
                Shop.company_id == tenant.company_id, Shop.id == shop_id
            )))
            audit_after = int(await db.scalar(select(func.count()).select_from(
                SystemAuditLog).where(
                SystemAuditLog.company_id == tenant.company_id,
                SystemAuditLog.target_id == f"Shop_{shop_id}",
            )) or 0)
        print(f"F10 Owner cap=75.125, ordinary stale name-only save HTTP={stale.status_code}, "
              f"actual_cap={cap} shop_financial_audit_delta={audit_after-audit_before}")
        assert cap == before_cap, (
            f"F10 P1 silent stale credit-limit overwrite: expected={before_cap}, "
            f"actual={cap}, audit_delta={audit_after-audit_before}"
        )


@pytest.mark.parametrize("pg", ["FIFO"], indirect=True)
async def test_f11_cross_tenant_mutations_and_read_only_backoffice_field_fail_closed(pg):
    tenant, foreign = pg.tenants
    zone_a, shop_a = await _simple_shop(pg, tenant)
    zone_b, shop_b = await _simple_shop(pg, foreign)
    # Warehouse-scoped dispatch.read does not imply dispatch.execute/shop mutation.
    await _grant_warehouse(pg, tenant, tenant.ordinary, "dispatch.read")
    field = await _seed_mobile_uom_and_field(pg, tenant)
    async with _client() as client:
        owner = await _owner(client, pg, tenant)
        foreign_owner = await _owner(client, pg, foreign)
        ordinary = await _login(client, pg, tenant, tenant.ordinary,
                                "SyntheticFixture123")
        field_headers = await _login(client, pg, tenant, field,
                                     "SyntheticFixture123")
        original = await _business_state(pg, tenant)
        original_b = await _business_state(pg, foreign)
        checks = [
            ("ordinary-shop", await client.put(
                f"/dispatch/shops/{shop_a}", headers=ordinary,
                json={"name": "FORBIDDEN ordinary edit"},
            )),
            ("ordinary-zone", await client.put(
                f"/dispatch/zones/{zone_a}", headers=ordinary,
                json={"name": "FORBIDDEN ordinary zone"},
            )),
            ("ordinary-shortage", await client.post(
                "/dispatch/shortages", headers=ordinary,
                json=[{"zoneId": zone_a, "shopId": shop_a,
                       "productId": tenant.variant_id, "quantity": 1}],
            )),
            ("field-shop", await client.put(
                f"/dispatch/shops/{shop_a}", headers=field_headers,
                json={"name": "FORBIDDEN field edit"},
            )),
            ("field-master-read", await client.get(
                "/dispatch/shops", headers=field_headers,
            )),
            ("foreign-shop", await client.put(
                f"/dispatch/shops/{shop_a}", headers=foreign_owner,
                json={"name": "FORBIDDEN foreign edit"},
            )),
            ("foreign-zone", await client.put(
                f"/dispatch/zones/{zone_a}", headers=foreign_owner,
                json={"name": "FORBIDDEN foreign zone"},
            )),
            ("foreign-shortage", await client.post(
                "/dispatch/shortages", headers=foreign_owner,
                json=[{"zoneId": zone_a, "shopId": shop_a,
                       "productId": foreign.variant_id, "quantity": 1}],
            )),
            ("owner-foreign-shop", await client.put(
                f"/dispatch/shops/{shop_b}", headers=owner,
                json={"name": "FORBIDDEN home owner foreign shop"},
            )),
        ]
        for key, response in checks:
            print(f"F11 {key} HTTP={response.status_code} body={response.text[:150]}")
            assert response.status_code in (401, 403, 404), (
                f"F11 P0 unauthorized write/read succeeded: {key}, "
                f"HTTP={response.status_code} {response.text[:200]}"
            )
        async with pg.session() as db:
            shop = await db.get(Shop, shop_a)
            zone = await db.get(Zone, zone_a)
            assert "FORBIDDEN" not in shop.name and "FORBIDDEN" not in zone.name
            assert int(await db.scalar(select(func.count()).select_from(
                ShortageRequest).where(
                ShortageRequest.company_id == tenant.company_id,
            )) or 0) == 0
        async with pg.session(1) as db:
            shop = await db.get(Shop, shop_b)
            assert "FORBIDDEN" not in shop.name
        assert await _business_state(pg, tenant) == original
        assert await _business_state(pg, foreign) == original_b


@pytest.mark.parametrize("pg", ["FIFO"], indirect=True)
async def test_f13_query_scale_progressive_100_500_2000_real_http(pg):
    """Measured evidence only; NO guessed V1 severity from unbounded response design."""
    tenant = pg.tenants[0]
    zone_id, _ = await _simple_shop(pg, tenant)
    total = 0
    async with _client() as client:
        owner = await _owner(client, pg, tenant)
        for target in (100, 500, 2000):
            delta = target - total
            async with pg.session() as db:
                await db.execute(insert(Shop), [
                    dict(company_id=tenant.company_id, zone_id=zone_id,
                         name=f"841-SCALE-{target}-{idx}-{uuid4().hex[:6]}",
                         is_active=True, is_archived=False, sequence=idx)
                    for idx in range(delta)
                ])
                await db.commit()
            total = target
            observations = {}
            for path in ("/dispatch/shops", "/dispatch/active_routes",
                         "/dispatch/shortages"):
                durations = []
                query_counts = []
                payload_bytes = []
                result_rows = []
                for _ in range(5):
                    count = [0]

                    def observe(_conn, _cursor, _stmt, _parameters, _ctx, _many):
                        count[0] += 1

                    event.listen(http_runtime_engine.sync_engine,
                                 "before_cursor_execute", observe)
                    start = perf_counter()
                    try:
                        response = await client.get(path, headers=owner)
                    finally:
                        elapsed = (perf_counter() - start) * 1000
                        event.remove(http_runtime_engine.sync_engine,
                                     "before_cursor_execute", observe)
                    assert response.status_code == 200, (
                        f"F13 {path} rows={target}, {response.status_code} {response.text[:300]}"
                    )
                    durations.append(round(elapsed, 2))
                    query_counts.append(count[0])
                    payload_bytes.append(len(response.content))
                    result_rows.append(len(response.json()))
                ordered = sorted(durations)
                observations[path] = {
                    "requested_shops": target,
                    "response_items": result_rows,
                    "response_bytes": payload_bytes,
                    "sql_queries": query_counts,
                    "p50_ms": median(durations),
                    "p95_ms_5_samples": ordered[-1] * 0.8 + ordered[-2] * 0.2,
                    "samples_ms": durations,
                }
                if path == "/dispatch/shops":
                    assert all(rows >= target for rows in result_rows)
            print(f"F13 MEASURED_PG16_HTTP_SCALE={observations} "
                  "latencies single CI machine, n=5: severity UNPROVEN")
