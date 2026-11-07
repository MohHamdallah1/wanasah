"""#817: restricted PostgreSQL16 + genuine production-Bearer read-only operation grouping.

No production/database/local-PC data. Uses the CP10 disposable-only URL guard,
migrations, two companies and NOBYPASSRLS runtime role.
"""
from __future__ import annotations

from decimal import Decimal
from time import perf_counter
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from api import auth
from api.warehouse import ledger
from domains.inventory_supplier_evidence import InventorySupplierEvidence, record_supplier_evidence
from domains.ledger.operation_read import read_operation_groups, read_operation_movements
from domains.suppliers.contracts import SupplierSnapshot
from domains.suppliers.models import Supplier
from models import (
    Company, InventoryMovement, InventoryTransferHeader, StocktakeSession,
    StocktakeLine, StocktakeCountAttempt, StocktakeCountAttemptLine,
    Product, ProductBatch, ProductVariant, UOM, utc_now,
)
from domains.identity.models import CompanyPrincipal
from services import apply_inventory_movements_batch
from tests.test_cp10_ledger_postgres import pg


def _spec(tenant, variant_id, batch_id, warehouse_id, reference, key, *,
          source=None, destination=None, reference_type="INBOUND_SUPPLIER",
          transfer_header_id=None, notes=None):
    return {
        "product_variant_id": variant_id, "batch_id": batch_id,
        "quantity": Decimal("1"), "movement_kind": "PHYSICAL",
        "reference_type": reference_type, "reference_id": reference,
        "idempotency_key": key,
        "source_location_id": source, "destination_location_id": destination,
        "source_stock_status": "AVAILABLE" if source is not None else None,
        "destination_stock_status": "AVAILABLE" if destination is not None else None,
        "transfer_header_id": transfer_header_id,
        "notes": notes,
    }


@pytest.mark.asyncio
async def test_817_supplier_51_lines_one_document_real_bearer_cursor_security(pg):
    ref = "SUP817-" + uuid4().hex[:18]
    repeat_ref = "SAME-DISPLAY-" + uuid4().hex[:12]
    receipt_uuid, collided_a, collided_b = uuid4(), uuid4(), uuid4()
    async with AsyncSession(pg.admin_engine, expire_on_commit=False) as seed:
        await seed.execute(text("SELECT set_config('app.current_tenant',:c,true)"),
                           {"c": str(pg.a.company_id)})
        supplier = Supplier(
            company_id=pg.a.company_id, name="Synthetic supplier #817",
            created_by=pg.a.owner.driver_id, updated_by=pg.a.owner.driver_id,
        )
        seed.add(supplier)
        await seed.flush()
        supplier_id = int(supplier.id)
        uom_id = pg.a.uom_id
        variants = []
        for n in range(50):
            product = Product(company_id=pg.a.company_id, code=f"G817-{uuid4().hex[:12]}",
                              name="Group inventory product")
            seed.add(product)
            await seed.flush()
            variant = ProductVariant(
                company_id=pg.a.company_id, product_id=product.id,
                name=f"Searchable group child {n}", sku=f"GROUP817-{uuid4().hex[:10]}",
                base_uom_id=uom_id, quantity_scale=6,
                quantity_step=Decimal("0.000001"), lot_control_mode="REQUIRED",
                expiry_control_mode="OPTIONAL", lifecycle_status="ACTIVE",
                published_at=utc_now(),
            )
            seed.add(variant)
            await seed.flush()
            batch = ProductBatch(
                company_id=pg.a.company_id, product_variant_id=variant.id,
                batch_number=f"G817-LOT-{n}-A",
            )
            seed.add(batch)
            await seed.flush()
            variants.append((int(variant.id), int(batch.id)))
            if n == 0:
                extra = ProductBatch(
                    company_id=pg.a.company_id, product_variant_id=variant.id,
                    batch_number="G817-LOT-0-B",
                )
                seed.add(extra)
                await seed.flush()
                variants.append((int(variant.id), int(extra.id)))
        await seed.commit()

    async with pg.session(pg.a) as db:
        movement_specs = [
            _spec(pg.a, vid, bid, pg.a.locations[0], ref,
                  "G817-RECEIPT-" + uuid4().hex,
                  destination=pg.a.locations[0],
                  notes="Ledger group source proof")
            for vid, bid in variants
        ]
        movements = await apply_inventory_movements_batch(
            db, company_id=pg.a.company_id,
            performed_by=pg.a.owner.driver_id, movements=movement_specs,
        )
        record_supplier_evidence(
            db, company_id=pg.a.company_id,
            movement_ids=[m.id for m in movements],
            supplier=SupplierSnapshot(id=supplier_id, name="Synthetic supplier #817", code=None),
            request_id=receipt_uuid,
        )
        # Equal reference is NEVER sufficient to merge different persisted UUIDs.
        a, b = await apply_inventory_movements_batch(
            db, company_id=pg.a.company_id, performed_by=pg.a.owner.driver_id,
            movements=[
                _spec(pg.a, pg.a.variant_id, pg.a.batch_id, pg.a.locations[0],
                      repeat_ref, "G817-COL-A-" + uuid4().hex,
                      destination=pg.a.locations[0]),
                _spec(pg.a, pg.a.variant_id, pg.a.batch_id, pg.a.locations[0],
                      repeat_ref, "G817-COL-B-" + uuid4().hex,
                      destination=pg.a.locations[0]),
            ],
        )
        db.add_all([
            InventorySupplierEvidence(
                company_id=pg.a.company_id, movement_id=a.id,
                supplier_id=supplier_id, supplier_name="Synthetic supplier #817",
                request_id=collided_a,
            ),
            InventorySupplierEvidence(
                company_id=pg.a.company_id, movement_id=b.id,
                supplier_id=supplier_id, supplier_name="Synthetic supplier #817",
                request_id=collided_b,
            ),
        ])
        await db.commit()

    async with pg.session(pg.a) as db:
        company_code = (await db.get(Company, pg.a.company_id)).company_code
        owner_name = await db.scalar(select(CompanyPrincipal.username).where(
            CompanyPrincipal.company_id == pg.a.company_id,
            CompanyPrincipal.id == pg.a.owner.context.principal_id,
        ))
        limited_name = await db.scalar(select(CompanyPrincipal.username).where(
            CompanyPrincipal.company_id == pg.a.company_id,
            CompanyPrincipal.id == pg.a.ordinary.context.principal_id,
        ))
    async with pg.session(pg.b) as db:
        foreign_company = (await db.get(Company, pg.b.company_id)).company_code
        foreign_name = await db.scalar(select(CompanyPrincipal.username).where(
            CompanyPrincipal.company_id == pg.b.company_id,
            CompanyPrincipal.id == pg.b.owner.context.principal_id,
        ))

    app = FastAPI()
    app.include_router(auth.router)
    app.include_router(ledger.router)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://ledger817.test", timeout=30,
    ) as client:
        async def sign_in(company, username, password):
            r = await client.post("/login", json={
                "company_code": company, "username": username, "password": password,
            })
            assert r.status_code == 200, r.text
            return {"Authorization": "Bearer " + r.json()["token"]}
        owner = await sign_in(company_code, owner_name, "CP10FixturePassword123")
        limited = await sign_in(company_code, limited_name, "SyntheticFixture123")
        foreign = await sign_in(foreign_company, foreign_name, "CP10FixturePassword123")
        path = "/warehouse/ledger/operations/cursor"

        async def page(*, headers=owner, warehouse=None, params=None):
            return await client.get(path, headers=headers, params={
                "location_id": warehouse or pg.a.locations[0], **(params or {}),
            })

        no_auth = await client.get(path, params={"location_id": pg.a.locations[0]})
        assert no_auth.status_code == 401
        assert (await page(headers=foreign)).status_code in (403, 404)
        assert (await page(headers=limited, warehouse=pg.a.locations[1])).status_code == 403
        assert (await page(headers=owner, warehouse=pg.b.locations[0])).status_code == 404

        initial = await page(params={"reference_id": ref, "limit": 20})
        assert initial.status_code == 200, initial.text
        body = initial.json()
        assert body["type_filter_semantics"] == "MATCH_ANY_CHILD_SHOW_ALL_AUTHORIZED"
        assert len(body["items"]) == 1, body
        group = body["items"][0]
        assert group["group_kind"] == "RECEIPT"
        assert (group["movement_count"], group["product_variant_count"],
                group["batch_count"]) == (51, 50, 51)
        assert group["stage_types"] == ["INBOUND_SUPPLIER"]
        assert group["reference"] == ref

        # Only *one* product matches, but the parent still exposes all 51
        # authorized children. The match is marked at the individual child.
        found = await page(params={"search": "Searchable group child 23"})
        assert found.status_code == 200, found.text
        matched_parent = [g for g in found.json()["items"] if g["reference"] == ref]
        assert len(matched_parent) == 1
        assert matched_parent[0]["movement_count"] == 51

        async def detail(key, *, headers=owner, warehouse=None, params=None):
            return await client.get(
                f"/warehouse/ledger/operations/{key}/movements/cursor",
                headers=headers,
                params={"location_id": warehouse or pg.a.locations[0],
                        "reference_id": ref, **(params or {})},
            )

        assert (await detail(group["group_key"], headers=foreign)).status_code in (400, 403, 404)
        assert (await detail(group["group_key"], headers=limited,
                             warehouse=pg.a.locations[1])).status_code == 403
        assert (await detail(group["group_key"], params={"search": "another"})).status_code == 400
        assert (await detail(group["group_key"], params={"reference_type": "TRANSFER_DISPATCH"})).status_code == 400
        tampered = group["group_key"][:-1] + ("A" if group["group_key"][-1] != "A" else "B")
        assert (await detail(tampered)).status_code == 400
        assert (await detail(group["group_key"], params={"cursor": "invalid"})).status_code == 400

        current = None
        seen = []
        for expected in range(4):
            result = await detail(group["group_key"], params={
                "limit": 15, **({"cursor": current} if current else {})
            })
            assert result.status_code == 200, result.text
            state = result.json()
            seen += state["items"]
            current = state["next_cursor"]
            if expected < 3:
                assert state["has_more"] is True
        assert len(seen) == 51 and len({m["id"] for m in seen}) == 51
        assert {m["batch_number"] for m in seen if m["product_name"] == "Searchable group child 0"} == {
            "G817-LOT-0-A", "G817-LOT-0-B",
        }
        assert all(m["movement_kind"] == "PHYSICAL" and
                   m["destination_location_id"] == pg.a.locations[0]
                   and m["matches_filter"] for m in seen)
        assert current is None

        matched_detail = await detail(
            matched_parent[0]["group_key"],
            params={"reference_id": "", "search": "Searchable group child 23", "limit": 70},
        )
        assert matched_detail.status_code == 200, matched_detail.text
        matched_items = matched_detail.json()["items"]
        assert len(matched_items) == 51
        assert sum(bool(m["matches_filter"]) for m in matched_items) == 1

        same_ref = await page(params={"reference_id": repeat_ref})
        assert same_ref.status_code == 200, same_ref.text
        same_rows = same_ref.json()["items"]
        assert len(same_rows) == 2
        assert all(r["movement_count"] == 1 for r in same_rows)
        assert len({r["group_key"] for r in same_rows}) == 2
        print("LEDGER_817_SUPPLIER_50_VARIANTS_51_LOTS_1_PARENT=PASS")
        print("LEDGER_817_COLLISION_TWO_UUIDS_TWO_GROUPS=PASS")
        print("LEDGER_817_REAL_BEARER_RLS_HMAC_MATCH_ANY_CHILD_BOUNDED_DETAIL=PASS")

        # A valid 100-character Arabic supplier reference must not become an
        # internal 500 merely because the signed group token encodes UTF-8.
        # Keyset continuation cursors remain bounded to 512.
        long_reference = "م" * 100
        async with pg.session(pg.a) as db:
            (unicode_movement,) = await apply_inventory_movements_batch(
                db, company_id=pg.a.company_id,
                performed_by=pg.a.owner.driver_id, movements=[
                    _spec(pg.a, pg.a.variant_id, pg.a.batch_id,
                          pg.a.locations[0], long_reference,
                          "G817-UTF8-" + uuid4().hex,
                          destination=pg.a.locations[0]),
                ],
            )
            record_supplier_evidence(
                db, company_id=pg.a.company_id,
                movement_ids=[unicode_movement.id],
                supplier=SupplierSnapshot(
                    id=supplier_id, name="Synthetic supplier #817", code=None,
                ),
                request_id=uuid4(),
            )
            await db.commit()
        utf8_groups = await page(params={"reference_id": long_reference})
        assert utf8_groups.status_code == 200, utf8_groups.text
        assert len(utf8_groups.json()["items"]) == 1
        utf8_key = utf8_groups.json()["items"][0]["group_key"]
        assert 512 < len(utf8_key) <= 1024
        utf8_detail = await detail(
            utf8_key, params={"reference_id": long_reference},
        )
        assert utf8_detail.status_code == 200, utf8_detail.text
        assert [row["id"] for row in utf8_detail.json()["items"]] == [
            int(unicode_movement.id)
        ]
        print("LEDGER_817_LONG_ARABIC_REFERENCE_OPAQUE_GROUP_TOKEN=PASS")


@pytest.mark.asyncio
async def test_817_transfer_stage_keyset_and_new_post_highwater(pg):
    ref = "TR817-" + uuid4().hex[:12]
    async with AsyncSession(pg.admin_engine, expire_on_commit=False) as seed:
        await seed.execute(text("SELECT set_config('app.current_tenant',:c,true)"),
                           {"c": str(pg.a.company_id)})
        transfer = InventoryTransferHeader(
            company_id=pg.a.company_id, reference_number=ref,
            source_location_id=pg.a.locations[0], destination_location_id=pg.a.locations[1],
            workflow_type="DIRECT", status="DRAFT", transfer_purpose="WAREHOUSE_BALANCING",
            commercial_context={"ledger817_test": True},
            dispatched_by=pg.a.owner.driver_id,
        )
        seed.add(transfer)
        await seed.flush()
        transfer_id = int(transfer.id)
        await seed.commit()

    async with pg.session(pg.a) as db:
        posts = await apply_inventory_movements_batch(
            db, company_id=pg.a.company_id, performed_by=pg.a.owner.driver_id,
            movements=[
                _spec(
                    pg.a, pg.a.variant_id, pg.a.batch_id, pg.a.locations[0],
                    ref, "G817-TR-" + uuid4().hex,
                    source=pg.a.locations[0], destination=pg.a.locations[1],
                    reference_type="TRANSFER_DISPATCH", transfer_header_id=transfer_id,
                ),
                _spec(
                    pg.a, pg.a.variant_id, pg.a.batch_id, pg.a.locations[0],
                    ref, "G817-TR-" + uuid4().hex,
                    source=pg.a.locations[0], destination=pg.a.locations[1],
                    reference_type="TRANSFER_DISPATCH", transfer_header_id=transfer_id,
                ),
            ],
        )
        await db.commit()
        ids = [int(m.id) for m in posts]
    async with pg.session(pg.a) as db:
        company_code = (await db.get(Company, pg.a.company_id)).company_code
        username = await db.scalar(select(CompanyPrincipal.username).where(
            CompanyPrincipal.company_id == pg.a.company_id,
            CompanyPrincipal.id == pg.a.owner.context.principal_id,
        ))
    app = FastAPI()
    app.include_router(auth.router)
    app.include_router(ledger.router)
    async with AsyncClient(transport=ASGITransport(app=app),
                           base_url="http://ledger817-transfer.test", timeout=30) as client:
        login = await client.post("/login", json={
            "company_code": company_code, "username": username,
            "password": "CP10FixturePassword123",
        })
        assert login.status_code == 200, login.text
        header = {"Authorization": "Bearer " + login.json()["token"]}
        async def groups(params):
            response = await client.get(
                "/warehouse/ledger/operations/cursor", headers=header,
                params={"location_id": pg.a.locations[0], **params},
            )
            assert response.status_code == 200, response.text
            return response.json()
        first = await groups({"limit": 1})
        assert first["has_more"] and first["next_cursor"]
        assert first["items"][0]["group_kind"] == "TRANSFER"
        assert first["items"][0]["movement_count"] == 2
        assert first["items"][0]["stage_types"] == ["TRANSFER_DISPATCH"]
        older = await groups({"limit": 1, "cursor": first["next_cursor"]})
        assert older["items"][0]["group_key"] != first["items"][0]["group_key"]
        assert older["snapshot_max_movement_id"] == first["snapshot_max_movement_id"]
        assert first["items"][0]["latest_movement_id"] == max(ids)

        # New physical post after the first group page is excluded from this
        # high-watermark across both parent and detail, but appears on refresh.
        async with pg.session(pg.a) as db:
            newly = await apply_inventory_movements_batch(
                db, company_id=pg.a.company_id, performed_by=pg.a.owner.driver_id,
                movements=[_spec(
                    pg.a, pg.a.variant_id, pg.a.batch_id, pg.a.locations[0],
                    "POST817-" + uuid4().hex,
                    "G817-LATER-" + uuid4().hex,
                    destination=pg.a.locations[0],
                    reference_type="UNKNOWN_DOCUMENT",
                )],
            )
            await db.commit()
            new_id = int(newly[0].id)
        page_after = await groups({"limit": 1, "cursor": first["next_cursor"]})
        assert all(item["latest_movement_id"] != new_id for item in page_after["items"])
        refresh = await groups({"limit": 1})
        assert refresh["items"][0]["latest_movement_id"] == new_id
        assert (await client.get(
            "/warehouse/ledger/operations/cursor", headers=header,
            params={"location_id": pg.a.locations[1], "limit": 1,
                    "cursor": first["next_cursor"]},
        )).status_code == 400
        print("LEDGER_817_TRANSFER_SAME_DURABLE_HEADER_AND_HWM_KEYSET=PASS")


@pytest.mark.asyncio
async def test_817_full_stocktake_50_counted_7_posted_variances_grouped(pg):
    """Synthetic *read-only* posted history; no production stocktake writes.

    Canonical posting is separately accepted in CP9. This fixture verifies that
    50 persisted count-attempt lines with 43 unchanged rows never become
    invented Ledger movements: only the seven real persisted movement IDs
    appear in the operation and in its bounded detail.
    """
    ref = "STK-817-" + uuid4().hex[:14]
    company_id, warehouse = pg.a.company_id, pg.a.locations[0]
    now = utc_now()
    async with AsyncSession(pg.admin_engine, expire_on_commit=False) as seed:
        await seed.execute(
            text("SELECT set_config('app.current_tenant',:tenant,true)"),
            {"tenant": str(company_id)},
        )
        product_id = int(await seed.scalar(select(ProductVariant.product_id).where(
            ProductVariant.company_id == company_id,
            ProductVariant.id == pg.a.variant_id,
        )))
        session = StocktakeSession(
            company_id=company_id, location_id=warehouse,
            reference_number=ref, stocktake_type="FULL_COUNT",
            status="POSTED", created_at=now, updated_at=now,
            snapshot_cutoff_at=now,
            started_by=pg.a.owner.driver_id,
            approved_by=pg.a.owner.driver_id,
            approved_at=now, posted_at=now,
        )
        seed.add(session)
        await seed.flush()
        attempt = StocktakeCountAttempt(
            company_id=company_id, stocktake_session_id=session.id,
            attempt_number=1, counted_by=pg.a.owner.driver_id,
            submitted_at=now,
        )
        seed.add(attempt)
        await seed.flush()
        evidence_ids = []
        for index in range(50):
            variant = ProductVariant(
                company_id=company_id, product_id=product_id,
                sku="STK817-" + uuid4().hex,
                name=f"Counted distinct variant {index}",
                base_uom_id=pg.a.uom_id, quantity_scale=6,
                quantity_step=Decimal("0.000001"),
                lot_control_mode="REQUIRED", expiry_control_mode="OPTIONAL",
                lifecycle_status="ACTIVE", published_at=now,
            )
            seed.add(variant)
            await seed.flush()
            batch = ProductBatch(
                company_id=company_id, product_variant_id=variant.id,
                batch_number=f"COUNT817-{index}",
            )
            seed.add(batch)
            await seed.flush()
            line = StocktakeLine(
                company_id=company_id, stocktake_session_id=session.id,
                product_variant_id=variant.id, batch_id=batch.id,
                stock_status="AVAILABLE", expected_quantity=Decimal("1"),
            )
            seed.add(line)
            await seed.flush()
            delta = Decimal("1") if index < 7 else Decimal("0")
            seed.add(StocktakeCountAttemptLine(
                company_id=company_id, stocktake_session_id=session.id,
                count_attempt_id=attempt.id, stocktake_line_id=line.id,
                expected_quantity=Decimal("1"),
                actual_quantity=Decimal("1") + delta,
                variance_quantity=delta,
            ))
            if delta:
                movement = InventoryMovement(
                    company_id=company_id,
                    performed_by=pg.a.owner.driver_id,
                    product_variant_id=variant.id, batch_id=batch.id,
                    quantity=delta, movement_kind="PHYSICAL",
                    reference_type="AUDIT_ADJUSTMENT", reference_id=ref,
                    idempotency_key="STK817-" + uuid4().hex,
                    destination_location_id=warehouse,
                    destination_stock_status="AVAILABLE",
                    stocktake_session_id=session.id,
                    stocktake_count_attempt_id=attempt.id,
                    created_at=now,
                )
                seed.add(movement)
                await seed.flush()
                evidence_ids.append(int(movement.id))
        await seed.commit()

    async with pg.session(pg.a) as db:
        assert await db.scalar(select(func.count(StocktakeLine.id)).where(
            StocktakeLine.company_id == company_id,
            StocktakeLine.stocktake_session_id == session.id,
        )) == 50
        assert await db.scalar(select(func.count(StocktakeCountAttemptLine.id)).where(
            StocktakeCountAttemptLine.company_id == company_id,
            StocktakeCountAttemptLine.stocktake_session_id == session.id,
            StocktakeCountAttemptLine.variance_quantity == 0,
        )) == 43
        company_code = (await db.get(Company, company_id)).company_code
        username = await db.scalar(select(CompanyPrincipal.username).where(
            CompanyPrincipal.company_id == company_id,
            CompanyPrincipal.id == pg.a.owner.context.principal_id,
        ))

    app = FastAPI()
    app.include_router(auth.router)
    app.include_router(ledger.router)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://ledger817-stocktake.test",
        timeout=30,
    ) as client:
        login = await client.post("/login", json={
            "company_code": company_code, "username": username,
            "password": "CP10FixturePassword123",
        })
        assert login.status_code == 200, login.text
        header = {"Authorization": "Bearer " + login.json()["token"]}
        params = {
            "location_id": warehouse,
            "reference_type": "AUDIT_ADJUSTMENT",
            "reference_id": ref,
        }
        parent = await client.get(
            "/warehouse/ledger/operations/cursor", headers=header,
            params=params,
        )
        assert parent.status_code == 200, parent.text
        groups = parent.json()["items"]
        assert len(groups) == 1
        group = groups[0]
        assert group["group_kind"] == "STOCKTAKE"
        assert group["operation_type"] == "AUDIT_ADJUSTMENT"
        assert group["movement_count"] == 7
        assert group["product_variant_count"] == 7
        assert group["batch_count"] == 7
        assert group["count_meaning"] == "POSTED_VARIANCE_MOVEMENTS"
        assert group["stocktake_history"] == {
            "session_id": int(session.id),
            "warehouse_location_id": warehouse,
            "reference": ref,
        }
        children = await client.get(
            "/warehouse/ledger/operations/" + group["group_key"] + "/movements/cursor",
            headers=header, params=params,
        )
        assert children.status_code == 200, children.text
        assert {row["id"] for row in children.json()["items"]} == set(evidence_ids)
        assert all(row["batch_number"] and row["movement_kind"] == "PHYSICAL"
                   and row["matches_filter"] for row in children.json()["items"])
    print("LEDGER_817_POSTED_STOCKTAKE_50_COUNTED_7_TRUE_VARIANCE_ROWS_PASS")


@pytest.mark.asyncio
async def test_817_real_pg16_large_history_bounded_sql_keyset(pg):
    """Synthetic READ-PLAN scale, not business posting evidence.

    1200 persisted transfer documents + 20,000 immutable synthetic movements
    plus one 1000-line document, inserted ONLY in this disposable test DB.
    Functional stock/cost authority is proved by the real canonical tests above.
    """
    seed_id = uuid4().hex[:14]
    company_id = pg.a.company_id
    a, b = pg.a.locations
    async with pg.session(pg.a) as db:
        hdrs = (await db.execute(text("""
            INSERT INTO inventory_transfer_headers (
                company_id, reference_number, source_location_id,
                destination_location_id, workflow_type, status,
                transfer_purpose, commercial_context, dispatched_by,
                created_at, updated_at
            )
            SELECT :c, 'PERF817-' || :tag || '-' || gs::text,
                   :a, :b, 'DIRECT', 'DRAFT',
                   'WAREHOUSE_BALANCING', '{}'::jsonb, :actor,
                   timezone('UTC', now()), timezone('UTC', now())
            FROM generate_series(1,1200) AS gs
            RETURNING id
        """), {"c": company_id, "tag": seed_id, "a": a, "b": b,
               "actor": pg.a.owner.driver_id})).scalars().all()
        assert len(hdrs) == 1200
        await db.execute(text("""
            WITH headers AS (
                SELECT id, reference_number,
                       row_number() OVER (ORDER BY id) AS rn
                FROM inventory_transfer_headers
                WHERE company_id=:c
                  AND reference_number LIKE :prefix
            )
            INSERT INTO inventory_movements (
                company_id, performed_by, destination_location_id,
                destination_stock_status, product_variant_id,
                batch_id, quantity, movement_kind, reference_type,
                reference_id, idempotency_key, transfer_header_id, created_at
            )
            SELECT :c, :actor, :a, 'AVAILABLE', :variant, :batch,
                   1, 'PHYSICAL', 'TRANSFER_DISPATCH',
                   headers.reference_number,
                   'PERF817-' || :tag || '-' || gs::text,
                   headers.id, timezone('UTC', now())
            FROM generate_series(1,20000) AS gs
            JOIN headers ON headers.rn = (gs - 1) % 1200 + 1
        """), {"c": company_id, "actor": pg.a.owner.driver_id, "a": a,
               "variant": pg.a.variant_id, "batch": pg.a.batch_id,
               "tag": seed_id, "prefix": f"PERF817-{seed_id}-%"})
        large_header = InventoryTransferHeader(
            company_id=company_id, reference_number="LARGE817-" + seed_id,
            source_location_id=a, destination_location_id=b,
            workflow_type="DIRECT", status="DRAFT",
            transfer_purpose="WAREHOUSE_BALANCING",
            commercial_context={"ledger817_synthetic_scale": True},
            dispatched_by=pg.a.owner.driver_id,
        )
        db.add(large_header)
        await db.flush()
        large_id = int(large_header.id)
        await db.execute(text("""
            INSERT INTO inventory_movements (
                company_id, performed_by, destination_location_id,
                destination_stock_status, product_variant_id,
                batch_id, quantity, movement_kind, reference_type,
                reference_id, idempotency_key, transfer_header_id, created_at
            )
            SELECT :c, :actor, :a, 'AVAILABLE', :variant, :batch,
                   1, 'PHYSICAL', 'TRANSFER_DISPATCH', :ref,
                   'PERF817-LARGE-' || :tag || '-' || gs::text, :h,
                   timezone('UTC', now())
            FROM generate_series(1,1000) AS gs
        """), {"c": company_id, "actor": pg.a.owner.driver_id, "a": a,
               "variant": pg.a.variant_id, "batch": pg.a.batch_id,
               "tag": seed_id, "h": large_id,
               "ref": "LARGE817-" + seed_id})
        await db.commit()

    traces = []
    def capture(_conn, _cursor, stmt, params, _context, _executemany):
        if stmt.lstrip().upper().startswith("SELECT") and "inventory_movements" in stmt:
            traces.append((stmt, params))
    event.listen(pg.runtime_engine.sync_engine, "before_cursor_execute", capture)
    try:
        async with pg.session(pg.a) as db:
            access = pg.a.owner.access(db)
            began = perf_counter()
            first = await read_operation_groups(
                db, access=access, company_id=company_id, location_id=a,
                cursor=None, limit=20, search=None, movement_type=None,
                reference_id=None,
            )
            duration_ms = round((perf_counter() - began) * 1000)
            # Bounded DB statements regardless of the 20,000+ source records.
            # A 1000-line leading group crosses four indexed 256-row windows;
            # each window uses one raw SELECT and one batched group aggregate.
            assert len(traces) <= 15, f"Unbounded operation reads: {len(traces)}"
            assert len(first["items"]) == 20 and first["has_more"]
            assert first["next_cursor"]
            assert all(g["group_kind"] == "TRANSFER" for g in first["items"])
            assert all(g["movement_count"] > 0 for g in first["items"])
            assert duration_ms < 15_000, f"Full-history operation read too slow: {duration_ms} ms"
            print(f"LEDGER_817_LARGE_HISTORY_DOCS=1201 MOVEMENTS=21000 "
                  f"SQL={len(traces)} FIRST_PAGE_MS={duration_ms} PASS")
            traces.clear()
            began = perf_counter()
            second = await read_operation_groups(
                db, access=access, company_id=company_id, location_id=a,
                cursor=first["next_cursor"], limit=20,
                search=None, movement_type=None, reference_id=None,
            )
            duration_ms_2 = round((perf_counter() - began) * 1000)
            assert len(traces) <= 6, f"Unbounded continuation: {len(traces)}"
            assert len(second["items"]) == 20
            assert not ({item["group_key"] for item in first["items"]} &
                        {item["group_key"] for item in second["items"]})
            assert duration_ms_2 < 15_000
            print(f"LEDGER_817_LARGE_KEYSET_NO_DUP_SQL={len(traces)} "
                  f"CONTINUATION_MS={duration_ms_2} PASS")
            traces.clear()
            grouped = await read_operation_groups(
                db, access=access, company_id=company_id, location_id=a,
                cursor=None, limit=20, search=None,
                movement_type=None, reference_id="LARGE817-" + seed_id,
            )
            assert len(grouped["items"]) == 1
            group = grouped["items"][0]
            assert group["movement_count"] == 1000
            detail = await read_operation_movements(
                db, access=access, company_id=company_id, location_id=a,
                group_token=group["group_key"], cursor=None,
                limit=20, search=None, movement_type=None,
                reference_id="LARGE817-" + seed_id,
            )
            assert len(detail["items"]) == 20 and detail["has_more"]
            assert detail["next_cursor"]
            assert all(i["matches_filter"] for i in detail["items"])
            print("LEDGER_817_LARGE_DOCUMENT_1000_LINES_BOUNDED_20_DETAIL=PASS")
    finally:
        event.remove(pg.runtime_engine.sync_engine, "before_cursor_execute", capture)
