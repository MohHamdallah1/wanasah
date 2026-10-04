import ast
import pytest
from pathlib import Path

from product_lifecycle import RETURN_DISPOSAL, evaluate_product_capability


def authority():
    path = Path(__file__).parents[1] / "services.py"
    node = next(
        n for n in ast.parse(path.read_text(encoding="utf-8")).body
        if isinstance(n, ast.FunctionDef)
        and n.name == "allowed_special_transfer_purposes"
    )
    namespace = {
        "evaluate_product_capability": evaluate_product_capability,
        "RETURN_DISPOSAL": RETURN_DISPOSAL,
        "_BATCH_DISPOSITIONS": {"RELEASED", "QUARANTINED", "BLOCKED", "RECALLED"},
        "_INVENTORY_STOCK_STATUSES": {
            "AVAILABLE", "QUARANTINED", "BLOCKED", "RECALLED", "DAMAGED", "DISPOSAL_PENDING"
        },
    }
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), namespace)
    return namespace["allowed_special_transfer_purposes"]


def test_healthy_available_stock_offers_no_quality_transfer():
    assert authority()(
        lifecycle_status="ACTIVE",
        operational_hold="NONE",
        batch_disposition="RELEASED",
        source_status="AVAILABLE",
        metadata_sellable=True,
    ) == ()


def test_confirmed_product_issue_offers_only_recall_safe_paths():
    assert authority()(
        lifecycle_status="ACTIVE",
        operational_hold="RECALL",
        batch_disposition="RELEASED",
        source_status="AVAILABLE",
        metadata_sellable=True,
    ) == ("RECALL_RETURN", "QUARANTINE", "DISPOSAL")


def test_blocked_batch_cannot_be_downgraded_to_quarantine():
    assert authority()(
        lifecycle_status="ACTIVE",
        operational_hold="NONE",
        batch_disposition="BLOCKED",
        source_status="AVAILABLE",
        metadata_sellable=False,
    ) == ("RETURN_TO_VENDOR", "DISPOSAL")


def test_expiry_restriction_enables_quality_paths_without_changing_batch_state():
    assert authority()(
        lifecycle_status="ACTIVE",
        operational_hold="NONE",
        batch_disposition="RELEASED",
        source_status="AVAILABLE",
        metadata_sellable=False,
    ) == ("QUARANTINE", "RETURN_TO_VENDOR", "DISPOSAL")


def test_archived_product_offers_no_new_physical_action():
    assert authority()(
        lifecycle_status="ARCHIVED",
        operational_hold="NONE",
        batch_disposition="QUARANTINED",
        source_status="QUARANTINED",
        metadata_sellable=False,
    ) == ()


class FakeInventoryRuleError(Exception):
    pass


def destination_reader(*, published, normalized=None, raises=False):
    path = Path(__file__).parents[1] / "services.py"
    node = next(
        n for n in ast.parse(path.read_text(encoding="utf-8")).body
        if isinstance(n, ast.AsyncFunctionDef)
        and n.name == "read_special_transfer_destinations"
    )

    async def get_state(_db, *, company_id):
        assert company_id == 7
        return None, published

    async def validate(_db, *, company_id, payload, lock_locations):
        assert company_id == 7
        assert lock_locations is False
        if raises:
            raise FakeInventoryRuleError()
        return normalized or payload

    namespace = {
        "AsyncSession": object,
        "get_transfer_destination_policy_state": get_state,
        "validate_transfer_destination_policy_payload": validate,
        "InventoryRuleError": FakeInventoryRuleError,
        "TRANSFER_DESTINATION_POLICY_SCHEMA_VERSION": 1,
        "SPECIAL_TRANSFER_DESTINATION_POLICY_KEY": {
            "RETURN_TO_VENDOR": "vendor_return_staging_location_id",
            "QUARANTINE": "quarantine_location_id",
            "RECALL_RETURN": "quarantine_location_id",
            "DISPOSAL": "disposal_location_id",
        },
    }
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), namespace)
    return namespace["read_special_transfer_destinations"]


@pytest.mark.asyncio
async def test_read_destination_snapshot_is_lock_free_and_server_derived():
    from types import SimpleNamespace

    published = SimpleNamespace(
        schema_version=1,
        validated_payload={
            "quarantine_location_id": 20,
            "disposal_location_id": 30,
            "vendor_return_staging_location_id": 40,
            "allow_retiring_warehouse_balancing": False,
        },
    )
    read = destination_reader(published=published)
    assert await read(object(), company_id=7) == {
        "RETURN_TO_VENDOR": 40,
        "QUARANTINE": 20,
        "RECALL_RETURN": 20,
        "DISPOSAL": 30,
    }


@pytest.mark.asyncio
async def test_read_destination_snapshot_fails_closed_on_missing_or_stale_policy():
    from types import SimpleNamespace

    assert await destination_reader(published=None)(object(), company_id=7) == {}
    stale = SimpleNamespace(schema_version=2, validated_payload={})
    assert await destination_reader(published=stale)(object(), company_id=7) == {}
    invalid = SimpleNamespace(schema_version=1, validated_payload={})
    assert await destination_reader(published=invalid, raises=True)(object(), company_id=7) == {}
