from unittest.mock import AsyncMock

import pytest

from product_lifecycle import recall_has_terminal_activity


@pytest.mark.asyncio
async def test_false_alarm_cancel_is_allowed_before_any_terminal_activity():
    db = AsyncMock()
    db.scalar.return_value = None

    active = await recall_has_terminal_activity(
        db,
        company_id=38,
        variant_id=118,
        lifecycle_revision=7,
    )

    assert active is False
    db.scalar.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("row_id", [501, 777])
async def test_false_alarm_cancel_is_blocked_after_terminal_activity(row_id):
    db = AsyncMock()
    db.scalar.return_value = row_id

    active = await recall_has_terminal_activity(
        db,
        company_id=38,
        variant_id=118,
        lifecycle_revision=7,
    )

    assert active is True
    db.scalar.assert_awaited_once()
