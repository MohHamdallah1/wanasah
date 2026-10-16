from __future__ import annotations

from decimal import Decimal
import os
from uuid import uuid4

import pytest

from domains.ledger import inbound_adjustment as adjustment_domain
from domains.ledger.inbound_adjustment import LedgerAdjustmentError
from models import ProductBatch
from tests.test_cp10_ledger_postgres import _seed_movement, pg


pytestmark = [
    pytest.mark.skipif(
        os.getenv("WANASAH_CP10_PG_GATE") != "1",
        reason="Explicit disposable CP10 PostgreSQL gate only",
    ),
    pytest.mark.asyncio(loop_scope="function"),
]


async def test_same_reference_same_product_multiple_batches_is_rejected_before_correction(pg):
    async with pg.session(pg.a) as db:
        second_batch = ProductBatch(
            company_id=pg.a.company_id,
            product_variant_id=pg.a.variant_id,
            batch_number="LOT-OVERLAP-SECOND",
        )
        db.add(second_batch)
        await db.flush()
        await _seed_movement(
            db,
            pg.a,
            location_id=pg.a.locations[0],
            reference_type="INBOUND_SUPPLIER",
            reference="INV-OVERLAP",
            quantity="1",
            batch_id=second_batch.id,
        )
        await db.commit()

    async with pg.session(pg.a) as db:
        with pytest.raises(LedgerAdjustmentError) as caught:
            await adjustment_domain.apply_inbound_adjustment(
                db,
                company_id=pg.a.company_id,
                entry_id=pg.a.a1_inbound,
                actor_id=pg.a.ordinary.driver_id,
                new_total_quantity=Decimal("12"),
                uom_id=pg.a.uom_id,
                notes=f"multi-batch-{uuid4().hex}",
            )
        assert caught.value.code == "LEDGER_ADJUSTMENT_MULTIPLE_BATCHES"
