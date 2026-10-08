from __future__ import annotations

"""Business provenance fixtures for the Live Stock benchmark dataset.

Kept separate from the scale seeder so Supplier/Cost evidence does not turn the
benchmark orchestration script into another domain implementation file.
"""

from uuid import uuid4

from sqlalchemy import text

HOT_PRODUCT_CODE = "__PERF_LIVE_STOCK_SCALE__"
HOT_SUPPLIER_CODE = "__PERF_LIVE_SUPPLIER__"
HOT_SUPPLIER_NAME = "Live Stock Benchmark Supplier"
HOT_INBOUND_KEY_PREFIX = "PERF-LIVE-INBOUND:"


async def scalar(session, sql: str, params: dict | None = None):
    return await session.scalar(text(sql), params or {})


async def execute(session, sql: str, params: dict | None = None):
    return await session.execute(text(sql), params or {})


async def cleanup_hot_business_provenance(
    session, *, company_id: int, product_id: int
) -> None:
    params = {
        "company_id": company_id,
        "product_id": product_id,
        "key_prefix": HOT_INBOUND_KEY_PREFIX,
    }
    await execute(
        session,
        """
        DELETE FROM inventory_cost_layers l
        USING inventory_cost_events e, inventory_movements m
        WHERE l.company_id=:company_id
          AND e.company_id=l.company_id AND e.id=l.source_cost_event_id
          AND m.company_id=e.company_id AND m.id=e.inventory_movement_id
          AND m.idempotency_key LIKE :key_prefix || '%'
        """,
        params,
    )
    await execute(
        session,
        """
        DELETE FROM inventory_cost_events e
        USING inventory_movements m
        WHERE e.company_id=:company_id
          AND m.company_id=e.company_id AND m.id=e.inventory_movement_id
          AND m.idempotency_key LIKE :key_prefix || '%'
        """,
        params,
    )
    # Production evidence is immutable. The explicit benchmark cleanup runs as
    # the migration owner and disables the guard only around reserved PERF rows.
    await execute(
        session,
        "ALTER TABLE inventory_supplier_evidence DISABLE TRIGGER inventory_supplier_evidence_immutable",
    )
    await execute(
        session,
        """
        DELETE FROM inventory_supplier_evidence e
        USING inventory_movements m
        WHERE e.company_id=:company_id
          AND m.company_id=e.company_id AND m.id=e.movement_id
          AND m.idempotency_key LIKE :key_prefix || '%'
        """,
        params,
    )
    await execute(
        session,
        "ALTER TABLE inventory_supplier_evidence ENABLE TRIGGER inventory_supplier_evidence_immutable",
    )
    await execute(
        session,
        "DELETE FROM inventory_movements WHERE company_id=:company_id AND idempotency_key LIKE :key_prefix || '%'",
        params,
    )


async def seed_hot_business_provenance(
    session,
    *,
    company_id: int,
    location_id: int,
    actor_id: int,
    each_id: int,
) -> None:
    product_id = await scalar(
        session,
        "SELECT id FROM products WHERE company_id=:company_id AND code=:code",
        {"company_id": company_id, "code": HOT_PRODUCT_CODE},
    )
    if product_id is None:
        raise RuntimeError("Scale benchmark product does not exist; seed it before provenance repair.")

    supplier_id = await scalar(
        session,
        """
        INSERT INTO suppliers (
            company_id, name, code, phone, address, is_active,
            version, created_by, updated_by, created_at, updated_at
        )
        VALUES (
            :company_id, :supplier_name, :supplier_code,
            '0000000000', 'Benchmark fixture', TRUE,
            1, :actor_id, :actor_id, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        )
        ON CONFLICT (company_id, code) DO UPDATE SET
            name=EXCLUDED.name,
            phone=EXCLUDED.phone,
            address=EXCLUDED.address,
            is_active=TRUE,
            updated_by=EXCLUDED.updated_by,
            updated_at=CURRENT_TIMESTAMP
        RETURNING id
        """,
        {
            "company_id": company_id,
            "supplier_name": HOT_SUPPLIER_NAME,
            "supplier_code": HOT_SUPPLIER_CODE,
            "actor_id": actor_id,
        },
    )
    supplier_id = int(supplier_id)
    request_id = uuid4()
    params = {
        "company_id": company_id,
        "location_id": location_id,
        "product_id": int(product_id),
        "actor_id": actor_id,
        "each_id": each_id,
        "supplier_id": supplier_id,
        "supplier_name": HOT_SUPPLIER_NAME,
        "supplier_code": HOT_SUPPLIER_CODE,
        "request_id": request_id,
        "key_prefix": HOT_INBOUND_KEY_PREFIX,
    }

    # One immutable external acquisition movement per live batch. These rows are
    # provenance only: balances were already seeded set-wise above.
    await execute(
        session,
        """
        WITH batch_totals AS (
            SELECT b.product_variant_id, b.batch_id, SUM(b.on_hand_quantity) AS quantity
            FROM inventory_balances b
            JOIN product_variants v
              ON v.company_id=b.company_id AND v.id=b.product_variant_id
            WHERE b.company_id=:company_id
              AND v.product_id=:product_id
              AND b.on_hand_quantity > 0
            GROUP BY b.product_variant_id, b.batch_id
        )
        INSERT INTO inventory_movements (
            company_id, performed_by,
            source_location_id, destination_location_id,
            source_stock_status, destination_stock_status,
            product_variant_id, batch_id,
            movement_kind, reservation_action, quantity,
            reference_type, reference_id, idempotency_key,
            notes, created_at
        )
        SELECT
            :company_id, :actor_id,
            NULL, :location_id,
            NULL, 'AVAILABLE',
            bt.product_variant_id, bt.batch_id,
            'PHYSICAL', NULL, bt.quantity,
            'INBOUND_SUPPLIER',
            :key_prefix || bt.product_variant_id::text || ':' || bt.batch_id::text,
            :key_prefix || bt.product_variant_id::text || ':' || bt.batch_id::text,
            'Benchmark Supplier provenance', CURRENT_TIMESTAMP
        FROM batch_totals bt
        ON CONFLICT (company_id, idempotency_key) DO NOTHING
        """,
        params,
    )

    await execute(
        session,
        """
        INSERT INTO inventory_supplier_evidence (
            company_id, movement_id, supplier_id,
            supplier_name, supplier_code, request_id
        )
        SELECT
            :company_id, m.id, :supplier_id,
            :supplier_name, :supplier_code, :request_id
        FROM inventory_movements m
        JOIN product_variants v
          ON v.company_id=m.company_id AND v.id=m.product_variant_id
        WHERE m.company_id=:company_id
          AND v.product_id=:product_id
          AND m.idempotency_key LIKE :key_prefix || '%'
        ON CONFLICT (company_id, movement_id) DO NOTHING
        """,
        params,
    )

    # Seed a real cost-event chain only when the company has an active costing
    # method. FIFO gets live layers; Moving Average uses the state below.
    await execute(
        session,
        """
        WITH batch_totals AS (
            SELECT
                b.product_variant_id,
                b.batch_id,
                SUM(b.on_hand_quantity) AS quantity
            FROM inventory_balances b
            JOIN product_variants v
              ON v.company_id=b.company_id AND v.id=b.product_variant_id
            WHERE b.company_id=:company_id
              AND v.product_id=:product_id
              AND b.on_hand_quantity > 0
            GROUP BY b.product_variant_id, b.batch_id
        ), ranked AS (
            SELECT
                bt.*,
                COALESCE(
                    SUM(bt.quantity) OVER (
                        PARTITION BY bt.product_variant_id
                        ORDER BY bt.batch_id
                        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                    ), 0
                ) AS quantity_before
            FROM batch_totals bt
        )
        INSERT INTO inventory_cost_events (
            company_id, inventory_movement_id, product_variant_id, batch_id,
            method, event_type, cost_basis,
            quantity, unit_cost, total_cost,
            quantity_before, quantity_after,
            value_before, value_after,
            input_uom_id, input_quantity, input_unit_cost,
            reversal_of_cost_event_id, created_at
        )
        SELECT
            :company_id, m.id, r.product_variant_id, r.batch_id,
            cp.method, 'PURCHASE_IN', 'PURCHASE_ACTUAL',
            r.quantity, 0.1, r.quantity * 0.1,
            r.quantity_before, r.quantity_before + r.quantity,
            r.quantity_before * 0.1, (r.quantity_before + r.quantity) * 0.1,
            :each_id, r.quantity, 0.1,
            NULL, m.created_at
        FROM ranked r
        JOIN inventory_movements m
          ON m.company_id=:company_id
         AND m.idempotency_key=:key_prefix || r.product_variant_id::text || ':' || r.batch_id::text
        JOIN inventory_cost_policies cp
          ON cp.company_id=:company_id AND cp.is_active IS TRUE
        ON CONFLICT (company_id, inventory_movement_id) DO NOTHING
        """,
        params,
    )

    await execute(
        session,
        """
        INSERT INTO inventory_cost_layers (
            company_id, product_variant_id, batch_id, source_cost_event_id,
            original_quantity, remaining_quantity, unit_cost,
            original_value, remaining_value, version, created_at, updated_at
        )
        SELECT
            e.company_id, e.product_variant_id, e.batch_id, e.id,
            e.quantity, e.quantity, e.unit_cost,
            e.total_cost, e.total_cost, 1, e.created_at, CURRENT_TIMESTAMP
        FROM inventory_cost_events e
        JOIN product_variants v
          ON v.company_id=e.company_id AND v.id=e.product_variant_id
        WHERE e.company_id=:company_id
          AND v.product_id=:product_id
          AND e.method='FIFO'
          AND e.event_type='PURCHASE_IN'
          AND e.inventory_movement_id IN (
              SELECT id FROM inventory_movements
              WHERE company_id=:company_id
                AND idempotency_key LIKE :key_prefix || '%'
          )
        ON CONFLICT (company_id, source_cost_event_id) DO NOTHING
        """,
        params,
    )

    await execute(
        session,
        """
        WITH totals AS (
            SELECT b.product_variant_id, SUM(b.on_hand_quantity) AS quantity
            FROM inventory_balances b
            JOIN product_variants v
              ON v.company_id=b.company_id AND v.id=b.product_variant_id
            WHERE b.company_id=:company_id AND v.product_id=:product_id
            GROUP BY b.product_variant_id
        )
        INSERT INTO inventory_cost_states (
            company_id, product_variant_id, quantity,
            inventory_value, average_unit_cost, version,
            created_at, updated_at
        )
        SELECT
            :company_id, t.product_variant_id, t.quantity,
            t.quantity * 0.1,
            CASE WHEN t.quantity > 0 THEN 0.1 ELSE 0 END, 1,
            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        FROM totals t
        ON CONFLICT (company_id, product_variant_id) DO UPDATE SET
            quantity=EXCLUDED.quantity,
            inventory_value=EXCLUDED.inventory_value,
            average_unit_cost=EXCLUDED.average_unit_cost,
            version=inventory_cost_states.version + 1,
            updated_at=CURRENT_TIMESTAMP
        """,
        params,
    )
