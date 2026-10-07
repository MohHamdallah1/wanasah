import os
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

os.environ.setdefault("SECRET_KEY", "WholeProductTerminalCompletionSecret123456789")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")

import pytest

import product_lifecycle
from api.warehouse.whole_product_quality import WholeProductQualityResolveRequest
from product_lifecycle import ProductLifecycleTransitionError


class _Db:
    async def flush(self):
        return None


@pytest.mark.asyncio
async def test_terminal_resolution_closes_recall_atomically(monkeypatch):
    row = SimpleNamespace(
        id=17,
        company_id=3,
        product_id=9,
        sku="SKU-17",
        name="Safe product",
        lifecycle_status="ACTIVE",
        operational_hold="RECALL",
        lifecycle_revision=4,
        version=8,
        published_at=None,
        retired_at=None,
        archived_at=None,
        updated_at=None,
    )
    events = []

    async def _no_blockers(*_args, **_kwargs):
        return []

    monkeypatch.setattr(product_lifecycle, "recall_completion_blockers", _no_blockers)
    monkeypatch.setattr(
        product_lifecycle,
        "record_domain_event",
        lambda *_args, **kwargs: events.append(kwargs),
    )

    await product_lifecycle.close_recall_after_terminal_resolution(
        _Db(),
        row=row,
        company_id=3,
        actor_id=5,
        request_id=UUID("00000000-0000-0000-0000-000000000017"),
        reason="terminal handling completed",
    )

    assert row.operational_hold == "NONE"
    assert row.lifecycle_revision == 5
    assert row.version == 9
    assert events[0]["event_type"] == "ProductRecallClosed"
    assert events[0]["before"]["operational_hold"] == "RECALL"
    assert events[0]["after"]["operational_hold"] == "NONE"


@pytest.mark.asyncio
async def test_terminal_resolution_refuses_to_close_with_remaining_blockers(monkeypatch):
    row = SimpleNamespace(
        id=18,
        company_id=3,
        product_id=9,
        sku="SKU-18",
        name="Blocked product",
        lifecycle_status="ACTIVE",
        operational_hold="RECALL",
        lifecycle_revision=2,
        version=3,
        published_at=None,
        retired_at=None,
        archived_at=None,
        updated_at=None,
    )

    async def _blocked(*_args, **_kwargs):
        return [{"code": "OPEN_TRANSFER", "count": 1, "sample_id": 44}]

    monkeypatch.setattr(product_lifecycle, "recall_completion_blockers", _blocked)

    with pytest.raises(ProductLifecycleTransitionError) as exc:
        await product_lifecycle.close_recall_after_terminal_resolution(
            _Db(),
            row=row,
            company_id=3,
            actor_id=5,
            request_id=UUID("00000000-0000-0000-0000-000000000018"),
            reason="terminal handling completed",
        )

    assert exc.value.code == "PRODUCT_RECALL_COMPLETION_REQUIRED"
    assert exc.value.context["blockers"][0]["code"] == "OPEN_TRANSFER"
    assert row.operational_hold == "RECALL"
    assert row.lifecycle_revision == 2
    assert row.version == 3


def test_supervisor_password_length_is_bounded():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        WholeProductQualityResolveRequest(
            request_id=UUID("00000000-0000-0000-0000-000000000020"),
            action="DISPOSE",
            reason="confirmed safety issue",
            confirmation_password="x" * 300,
        )


def test_supervisor_password_is_secret_and_not_semantic_idempotency_data():
    payload = WholeProductQualityResolveRequest(
        request_id=UUID("00000000-0000-0000-0000-000000000019"),
        action="DISPOSE",
        reason="confirmed safety issue",
        confirmation_password="super-secret-password",
    )
    assert payload.confirmation_password.get_secret_value() == "super-secret-password"
    assert "super-secret-password" not in payload.model_dump_json()


def test_false_alarm_guard_covers_every_real_terminal_path():
    source = Path(product_lifecycle.__file__).read_text(encoding="utf-8")
    assert '"RECALL_RETURN", "DISPOSAL", "RETURN_TO_VENDOR"' in source
    assert "recall_has_terminal_activity" in source


def test_whole_product_endpoint_verifies_then_closes_before_commit():
    source = Path(__file__).resolve().parents[1].joinpath(
        "api", "warehouse", "whole_product_quality.py"
    ).read_text(encoding="utf-8")
    assert source.index("verify_actor_password") < source.index("begin_idempotent_operation")
    assert source.index("close_recall_after_terminal_resolution(") > source.index("confirm_final_disposal(")
    assert source.index("close_recall_after_terminal_resolution(") > source.index("confirm_vendor_handover(")
    assert source.index("close_recall_after_terminal_resolution(") < source.index("complete_idempotent_operation(idem")
    assert "quality_issue=CLOSED" in source


@pytest.mark.asyncio
async def test_terminal_resolution_can_keep_product_stopped_after_handling(monkeypatch):
    row = SimpleNamespace(
        id=21,
        company_id=3,
        product_id=9,
        sku="SKU-21",
        name="Keep stopped",
        lifecycle_status="ACTIVE",
        operational_hold="RECALL",
        lifecycle_revision=6,
        version=10,
        published_at=None,
        retired_at=None,
        archived_at=None,
        updated_at=None,
    )

    async def _no_blockers(*_args, **_kwargs):
        return []

    monkeypatch.setattr(product_lifecycle, "recall_completion_blockers", _no_blockers)
    monkeypatch.setattr(product_lifecycle, "record_domain_event", lambda *_args, **_kwargs: None)

    await product_lifecycle.close_recall_after_terminal_resolution(
        _Db(),
        row=row,
        company_id=3,
        actor_id=5,
        request_id=UUID("00000000-0000-0000-0000-000000000021"),
        reason="terminal handling completed",
        target_hold="SALES_HOLD",
    )

    assert row.operational_hold == "SALES_HOLD"
    assert row.lifecycle_revision == 7
    assert row.version == 11


def test_whole_product_request_keeps_post_resolution_choice_explicit():
    payload = WholeProductQualityResolveRequest(
        request_id=UUID("00000000-0000-0000-0000-000000000022"),
        action="DISPOSE",
        reason="confirmed safety issue",
        confirmation_password="super-secret-password",
        post_resolution_hold="SALES_HOLD",
    )
    assert payload.post_resolution_hold == "SALES_HOLD"


def test_whole_product_recall_requires_positive_stock_before_opening_hold():
    catalog_source = Path(__file__).resolve().parents[1].joinpath("api", "catalog.py").read_text(encoding="utf-8")
    start = catalog_source.index('elif command == "recall":')
    end = catalog_source.index('elif command == "cancel-recall":', start)
    recall_block = catalog_source[start:end]
    assert "InventoryBalance.on_hand_quantity > 0" in recall_block
    assert "PRODUCT_RECALL_NO_STOCK" in recall_block
    assert recall_block.index("PRODUCT_RECALL_NO_STOCK") < recall_block.index('row.operational_hold = "RECALL"')


def test_whole_product_endpoint_applies_post_resolution_choice_atomically():
    source = Path(__file__).resolve().parents[1].joinpath(
        "api", "warehouse", "whole_product_quality.py"
    ).read_text(encoding="utf-8")
    assert "post_resolution_hold" in source
    assert "target_hold=payload.post_resolution_hold" in source
    assert source.index("target_hold=payload.post_resolution_hold") < source.index("complete_idempotent_operation(idem")


def test_supplier_integration_preserves_pre_post_resolution_replay_compatibility():
    identity_source = Path(__file__).resolve().parents[1].joinpath(
        "api", "warehouse", "whole_product_quality_identity.py"
    ).read_text(encoding="utf-8")
    endpoint_source = Path(__file__).resolve().parents[1].joinpath(
        "api", "warehouse", "whole_product_quality.py"
    ).read_text(encoding="utf-8")
    assert '"post_resolution_hold"' in identity_source
    assert 'replay_payload.setdefault("post_resolution_hold", "NONE")' in endpoint_source
