from decimal import Decimal
import os
from types import SimpleNamespace

os.environ.setdefault("SECRET_KEY", "TerminalProvenanceTestSecretKeyAa1234567890")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")

import pytest

from domains.inventory_terminal_provenance import allocate_terminal_origin_quantity
from services import InventoryRuleError


class _Rows:
    def __init__(self, rows): self.rows=list(rows)
    def all(self): return list(self.rows)


class _Db:
    def __init__(self, rows): self.rows=list(rows)
    async def execute(self, _stmt):
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
