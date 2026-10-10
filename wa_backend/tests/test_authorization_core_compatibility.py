from pathlib import Path
from types import SimpleNamespace

import pytest

import inventory_access as legacy_access
from domains.authorization import (
    COMPANY_ONLY,
    PERMISSIONS,
    InventoryAccess,
    inventory_actor,
    require_inbound_adjustment,
    require_stocktake,
    require_transfer,
    transfer_filter,
)
from domains.authorization.subject import subject_from_legacy_driver


ROOT = Path(__file__).resolve().parents[1]


def test_legacy_inventory_access_module_is_a_thin_reexport_facade():
    assert legacy_access.PERMISSIONS is PERMISSIONS
    assert legacy_access.COMPANY_ONLY is COMPANY_ONLY
    assert legacy_access.InventoryAccess is InventoryAccess
    assert legacy_access.inventory_actor is inventory_actor
    assert legacy_access.require_stocktake is require_stocktake
    assert legacy_access.transfer_filter is transfer_filter
    assert legacy_access.require_transfer is require_transfer
    assert legacy_access.require_inbound_adjustment is require_inbound_adjustment


def test_legacy_driver_authority_enters_only_through_subject_adapter():
    actor = SimpleNamespace(id=17, company_id=4, is_admin=True)
    subject = subject_from_legacy_driver(actor)

    assert subject.principal_id == 17
    assert subject.actor_id == 17
    assert subject.company_id == 4
    assert subject.legacy_full_authority is True

    domain_root = ROOT / "domains" / "authorization"
    for path in domain_root.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        if path.name == "subject.py":
            assert source.count(".is_admin") == 1
        else:
            assert ".is_admin" not in source
    assert ".is_admin" not in (ROOT / "inventory_access.py").read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_legacy_full_authority_behavior_and_validation_are_preserved_without_db_reads():
    actor = SimpleNamespace(id=17, company_id=4, is_admin=True)
    access = InventoryAccess(None, actor)

    assert str(access.allows("inventory.read")).lower() == "true"
    assert await access.codes() == sorted(PERMISSIONS)
    await access.require_all(("inventory.read", "catalog.read"))

    with pytest.raises(ValueError, match="Unknown inventory permission"):
        access.allows("admin.anything")
    with pytest.raises(ValueError, match="Unknown inventory permission"):
        await access.require_all(("inventory.read", "admin.anything"))


def test_capability_catalog_keeps_location_scoped_terminal_permissions_and_no_generic_admin_family():
    assert "inventory.disposal.confirm" in PERMISSIONS
    assert "inventory.vendor_return.confirm" in PERMISSIONS
    assert "inventory.disposal.confirm" not in COMPANY_ONLY
    assert "inventory.vendor_return.confirm" not in COMPANY_ONLY
    assert not any(code.startswith("admin.") for code in PERMISSIONS)
