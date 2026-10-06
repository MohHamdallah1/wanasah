from decimal import Decimal
import os
from types import SimpleNamespace

os.environ.setdefault("SECRET_KEY", "TerminalProvenanceTestSecretKeyAa1234567890")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")

import pytest

from domains.inventory_terminal_provenance import (
    allocate_terminal_origin_quantity,
    read_terminal_origin_availability_for_batches,
)
from services import InventoryRuleError


class _Rows:
    def __init__(self, rows): self.rows=list(rows)
    def all(self): return list(self.rows)


class _Db:
    def __init__(self, rows):
        self.rows=list(rows)
        self.execute_count = 0
    async def execute(self, _stmt):
        self.execute_count += 1
        if not self.rows: raise AssertionError("unexpected execute")
        return _Rows(self.rows.pop(0))


@pytest.mark.asyncio
async def test_provenance_allocates_only_unconsumed_posted_staging_capacity():
    origins=[
        SimpleNamespace(header_id=10, reference_number="A", quantity=Decimal("5")),
        SimpleNamespace(header_id=11, reference_number="B", quantity=Decimal("4")),
    ]
    consumed=[SimpleNamespace(transfer_header_id=10, quantity=Decimal("3"))]
    db=_Db([[], origins, consumed])
    result=await allocate_terminal_origin_quantity(
        db, company_id=2, transfer_purpose="DISPOSAL",
        destination_location_id=7, product_variant_id=8, batch_id=9,
        terminal_reference_type="FINAL_DISPOSAL", requested_quantity=Decimal("5"),
    )
    assert [(row.transfer_header_id,row.quantity) for row in result] == [
        (10,Decimal("2")),(11,Decimal("3"))
    ]


@pytest.mark.asyncio
async def test_provenance_rejects_quantity_beyond_remaining_staging_evidence():
    origins=[SimpleNamespace(header_id=10, reference_number="A", quantity=Decimal("5"))]
    consumed=[SimpleNamespace(transfer_header_id=10, quantity=Decimal("4"))]
    db=_Db([[], origins, consumed])
    with pytest.raises(InventoryRuleError) as exc:
        await allocate_terminal_origin_quantity(
            db, company_id=2, transfer_purpose="DISPOSAL",
            destination_location_id=7, product_variant_id=8, batch_id=9,
            terminal_reference_type="FINAL_DISPOSAL", requested_quantity=Decimal("2"),
        )
    assert exc.value.code == "TERMINAL_STAGING_EVIDENCE_SHORTAGE"


@pytest.mark.asyncio
async def test_page_availability_is_set_based_for_multiple_batches_and_sources():
    origins = [
        SimpleNamespace(header_id=10, workflow_type="TRANSIT", source_location_id=1, destination_location_id=7, transfer_purpose="DISPOSAL", batch_id=9, quantity=Decimal("5")),
        SimpleNamespace(header_id=11, workflow_type="TRANSIT", source_location_id=1, destination_location_id=7, transfer_purpose="DISPOSAL", batch_id=10, quantity=Decimal("4")),
        SimpleNamespace(header_id=12, workflow_type="DIRECT", source_location_id=8, destination_location_id=99, transfer_purpose="RETURN_TO_VENDOR", batch_id=9, quantity=Decimal("3")),
    ]
    consumed = [
        SimpleNamespace(transfer_header_id=10, batch_id=9, source_location_id=7, reference_type="FINAL_DISPOSAL", quantity=Decimal("2")),
    ]
    db = _Db([origins, consumed])
    result = await read_terminal_origin_availability_for_batches(
        db,
        company_id=2,
        destination_location_ids=[7, 8],
        product_variant_id=8,
        batch_ids=[9, 10],
    )
    assert db.execute_count == 2
    assert result == {
        ("DISPOSAL", 9, 7): Decimal("3"),
        ("DISPOSAL", 10, 7): Decimal("4"),
        ("RETURN_TO_VENDOR", 9, 8): Decimal("3"),
    }
