"""Focused FIELD provenance, signed transport and mutation revalidation."""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock, Mock, patch
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from domains.auth_sessions.context import FieldRequestContext
from domains.field_operations import returns
from domains.field_operations.contracts import FieldContractError, ReturnResolutionRequest
from domains.field_operations.tokens import owner_binding, seal_reference
from domains.sales_calculation.driver_sale import DriverSaleUomContract
from schemas import VisitReturnInput, VisitUpdateRequest

CTX = FieldRequestContext(101, 7, 202, 1)
DRIVER, VISIT, SHOP, SESSION, SKU = 303, 11, 22, 33, 44


def batch(key=1, lot="LOT-A", expiry=None):
    return NS(id=key, company_id=7, product_variant_id=SKU, batch_number=lot,
              production_date=None, expiry_date=expiry)


def variant(mode="REQUIRED"):
    return NS(id=SKU, lot_control_mode=mode, expiry_control_mode="OPTIONAL")


def candidate(key=1, lot="LOT-A", quantity="10", expiry=None, dates=()):
    return returns.ReturnCandidate(batch(key, lot, expiry), Decimal(quantity), frozenset(dates))


def request(**changes):
    return ReturnResolutionRequest(product_variant_id=SKU, packs_quantity=2, **changes)


def proof(*, chosen=None, mode="REQUIRED", **changes):
    selected = chosen or batch()
    return {
        **owner_binding(CTX, DRIVER), "visit": VISIT, "shop": SHOP, "session": SESSION,
        "batch": selected.id, "request": request().model_dump(mode="json"),
        "evidence": returns._batch_evidence(selected, variant(mode)), **changes,
    }


def payload(token, **changes):
    return VisitUpdateRequest(request_id=uuid4(), outcome="NoSale", returns=[{
        "product_variant_id": SKU, "packs_quantity": 2,
        "resolution_token": token, **changes,
    }])


def result(value=None, *, rows=()):
    out = Mock()
    out.scalar_one_or_none.return_value = value
    out.scalars.return_value.all.return_value = list(rows)
    out.all.return_value = list(rows)
    return out


@pytest.mark.parametrize("mode,lot", [("REQUIRED", "LOT-A"), ("NONE", "__WANASAH_NOLOT__:R1:P-:E-")])
def test_single_delivered_batch_is_deterministic_without_operator_id(mode, lot):
    item = candidate(lot=lot)
    assert returns.choose_batch([item], variant=variant(mode), request=request()) is item


def test_tracked_ambiguity_requests_only_human_lot_evidence():
    with pytest.raises(FieldContractError) as failure:
        returns.choose_batch([candidate(), candidate(2, "LOT-B")],
                             variant=variant(), request=request())
    assert failure.value.code == "FIELD_RETURN_EVIDENCE_REQUIRED"
    assert failure.value.context == {
        "required_evidence": ["lot_number"],
        "choices": [{"lot_number": "LOT-A"}, {"lot_number": "LOT-B"}],
    }
    assert "batch" not in str(failure.value.context).lower()


def test_no_lot_receipts_do_not_collapse_and_expiry_can_discriminate():
    items = [candidate(1, "__WANASAH_NOLOT__:R1", expiry=date(2027, 1, 1)),
             candidate(2, "__WANASAH_NOLOT__:R2", expiry=date(2027, 2, 1))]
    with pytest.raises(FieldContractError) as failure:
        returns.choose_batch(items, variant=variant("NONE"), request=request())
    assert failure.value.context["required_evidence"] == ["expiry_date"]
    assert "__WANASAH" not in str(failure.value.context)


def test_anonymous_ambiguity_asks_delivery_date_then_fails_closed():
    items = [candidate(1, "__WANASAH_NOLOT__:R1"), candidate(2, "__WANASAH_NOLOT__:R2")]
    with pytest.raises(FieldContractError) as first:
        returns.choose_batch(items, variant=variant("NONE"), request=request())
    assert first.value.context == {"required_evidence": ["delivery_date"]}
    with pytest.raises(FieldContractError) as second:
        returns.choose_batch(items, variant=variant("NONE"), request=request(delivery_date=date(2026, 1, 1)))
    assert second.value.code == "FIELD_RETURN_PROVENANCE_REVIEW_REQUIRED"


@pytest.mark.parametrize("reason", ["Damaged", "Expired", "Factory_Defect"])
def test_signed_transport_preserves_all_return_types_and_canonical_hash_shape(reason):
    evidence = proof()
    evidence["request"]["return_type"] = reason
    token = seal_reference("FIELD_RETURN_RESOLUTION", evidence)
    wire = payload(token, return_type=reason)
    canonical, proofs = returns.canonicalize_returns(wire, context=CTX, driver_id=DRIVER, visit_id=VISIT)
    assert canonical.returns[0].batch_id == 1
    assert canonical.returns[0].return_type == reason
    legacy = VisitUpdateRequest(
        request_id=wire.request_id, outcome="NoSale",
        returns=[{"product_variant_id": SKU, "batch_id": 1, "packs_quantity": 2, "return_type": reason}],
    )
    assert canonical.model_dump(mode="json") == legacy.model_dump(mode="json")
    assert proofs[0]["shop"] == SHOP
    with pytest.raises(ValidationError):
        VisitReturnInput(product_variant_id=SKU, packs_quantity=2)


@pytest.mark.parametrize("change", [
    {"company": 8}, {"principal": 999}, {"representative": 999}, {"driver": 999}, {"visit": 999},
])
def test_cross_owner_or_visit_reference_is_rejected(change):
    token = seal_reference("FIELD_RETURN_RESOLUTION", proof(**change))
    with pytest.raises(FieldContractError) as failure:
        returns.canonicalize_returns(payload(token), context=CTX, driver_id=DRIVER, visit_id=VISIT)
    assert failure.value.code == "FIELD_REFERENCE_SCOPE_MISMATCH"


def test_tampering_wrong_purpose_and_changed_quantity_are_rejected():
    token = seal_reference("FIELD_RETURN_RESOLUTION", proof())
    for bad in (token[:-10] + "tamperedXX", seal_reference("OTHER_PURPOSE", proof())):
        with pytest.raises(FieldContractError):
            returns.canonicalize_returns(payload(bad), context=CTX, driver_id=DRIVER, visit_id=VISIT)
    with pytest.raises(FieldContractError) as failure:
        returns.canonicalize_returns(payload(token, packs_quantity=3), context=CTX, driver_id=DRIVER, visit_id=VISIT)
    assert failure.value.code == "FIELD_RETURN_RESOLUTION_MISMATCH"


@pytest.mark.asyncio
async def test_quantity_does_not_silently_choose_one_of_several_possible_batches():
    db = NS(execute=AsyncMock(return_value=result(rows=[variant()])))
    items = [candidate(1, "LOT-A", quantity="1"), candidate(2, "LOT-B", quantity="10")]
    contracts = {SKU: DriverSaleUomContract(SKU, 1, 2, 50, 0, Decimal("1"))}
    with patch.object(returns, "resolve_driver_mobile_uom_contracts", AsyncMock(return_value=contracts)), \
         patch.object(returns, "_candidate_batches", AsyncMock(return_value={SKU: items})):
        with pytest.raises(FieldContractError) as failure:
            await returns._resolve_many(db, company_id=7, shop_id=SHOP, requests=[request()])
    assert failure.value.code == "FIELD_RETURN_EVIDENCE_REQUIRED"


@pytest.mark.asyncio
async def test_candidates_use_tenant_shop_net_movements_and_are_bounded():
    db = NS(execute=AsyncMock(return_value=result(rows=[])))
    assert await returns._candidate_batches(db, company_id=7, shop_id=SHOP, requests=[request()]) == {}
    statement = db.execute.await_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    for fragment in ("product_batches.company_id = 7", "inventory_movements.company_id = 7",
                     "visits.company_id = 7", "visits.shop_id = 22", "VISIT_REVERSAL",
                     "VISIT_RETURN_IN", "LIMIT 1001"):
        assert fragment in sql
    assert "HAVING sum" in sql
    assert " >= 2" not in sql  # Quantity must never select the only large lot.


@pytest.mark.asyncio
async def test_resolution_result_is_opaque_and_mutation_rechecks_current_provenance():
    selected = batch()
    evidence = proof()
    with patch.object(returns, "assigned_visit", AsyncMock(return_value=(
            NS(id=VISIT), NS(id=SHOP), NS(session=NS(id=SESSION))))), \
         patch.object(returns, "_resolve_many", AsyncMock(return_value=[(selected, variant())])):
        resolved = await returns.resolve_return(
            None, context=CTX, driver_id=DRIVER, visit_id=VISIT, request=request())
    assert set(resolved) == {"status", "resolution_token", "evidence"}
    assert "batch_id" not in resolved["evidence"]
    with patch.object(returns, "_resolve_many", AsyncMock(return_value=[(batch(2), variant())])):
        with pytest.raises(FieldContractError) as failure:
            await returns.revalidate_provenance(
                None, context=CTX, driver_id=DRIVER, visit=NS(id=VISIT, shop_id=SHOP),
                session=NS(id=SESSION), proofs=[evidence])
    assert failure.value.code == "FIELD_RETURN_RESOLUTION_CHANGED"


@pytest.mark.asyncio
async def test_empty_proofs_preserve_legacy_path_without_queries():
    db = NS(execute=AsyncMock())
    await returns.revalidate_provenance(
        db, context=CTX, driver_id=DRIVER, visit=NS(), session=NS(), proofs=())
    await returns.revalidate_batch_metadata(db, company_id=7, proofs=())
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_final_batch_metadata_is_locked_and_cannot_cross_company_or_change_lot():
    db = NS(execute=AsyncMock(return_value=result(rows=[(batch(lot="CHANGED"), variant())])))
    with pytest.raises(FieldContractError) as failure:
        await returns.revalidate_batch_metadata(db, company_id=7, proofs=[proof()])
    assert failure.value.code == "FIELD_RETURN_RESOLUTION_CHANGED"
    sql = str(db.execute.await_args.args[0].compile(
        dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "product_batches.company_id = 7" in sql and "FOR SHARE OF product_batches" in sql
    db.execute.return_value = result(rows=[])
    with pytest.raises(FieldContractError):
        await returns.revalidate_batch_metadata(db, company_id=7, proofs=[proof()])
