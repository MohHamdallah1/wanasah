from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from api.catalog import _assert_recall_cancel_has_no_return_activity


@pytest.mark.asyncio
async def test_false_alarm_cancel_is_allowed_before_recall_return_activity():
    db = AsyncMock()
    db.scalar.return_value = None

    await _assert_recall_cancel_has_no_return_activity(
        db,
        company_id=38,
        variant_id=118,
        lifecycle_revision=7,
    )

    db.scalar.assert_awaited_once()


@pytest.mark.asyncio
async def test_false_alarm_cancel_is_blocked_after_recall_return_activity():
    db = AsyncMock()
    db.scalar.return_value = 501

    with pytest.raises(HTTPException) as exc_info:
        await _assert_recall_cancel_has_no_return_activity(
            db,
            company_id=38,
            variant_id=118,
            lifecycle_revision=7,
        )

    error = exc_info.value
    assert error.status_code == 409
    assert error.detail["code"] == "PRODUCT_RECALL_CANCEL_AFTER_ACTIVITY"
    assert error.detail["context"]["variant_id"] == 118
