"""Phase 1: reuse the actual stock-sources read and existing synthetic fixture.

No application startup, mutation workflow, production database or terminal
command implementation. PostgreSQL RLS runtime acceptance remains separate.
"""
import pytest
from fastapi import HTTPException

from models import InventoryLocation
from tests.test_batch_reservation_owner_contract import actor, balance, grant, read, store  # noqa: F401


@pytest.mark.asyncio
@pytest.mark.parametrize("locations", [(1,), (1, 3), (1, 2), (2,)])
async def test_batch_identity_resolves_all_readable_sources_without_warehouse_anchor(store, locations):
    store.insert(InventoryLocation, id=3, company_id=1, name="Second warehouse", location_type="WAREHOUSE", is_active=True)
    for location in locations:
        balance(store, reserved="0", location=location)
    response = await read(store)
    assert response["batch_id"] == 11 and response["product_variant_id"] == 101
    assert {source["location_id"] for source in response["sources"]} == set(locations)
    assert all(source["statuses"][0]["on_hand_quantity"] == "100" for source in response["sources"])
    assert len(store.db.statements) == 4  # constant for one/multiple warehouse/vehicle sources


@pytest.mark.asyncio
async def test_hidden_source_identity_name_count_and_quantity_are_not_projected(store):
    grant(store, "inventory.read", 1)
    balance(store, reserved="0")
    balance(store, reserved="0", location=2)
    response = await read(store, actor(admin=False))
    assert len(response["sources"]) == 1
    assert response["sources"][0]["location_id"] == 1
    assert response["sources"][0]["location_name"] == "Warehouse"
    assert "Vehicle" not in str(response) and "total_sources" not in response
    assert response["sources"][0]["statuses"][0]["on_hand_quantity"] == "100"


@pytest.mark.asyncio
async def test_unreadable_batch_and_foreign_tenant_keep_existing_denials(store):
    grant(store, "inventory.read", 1)
    balance(store, reserved="0", location=2)
    with pytest.raises(HTTPException) as hidden:
        await read(store, actor(admin=False))
    assert hidden.value.status_code == 404
    with pytest.raises(HTTPException) as foreign:
        await read(store, actor(company=2))
    assert foreign.value.status_code == 404
