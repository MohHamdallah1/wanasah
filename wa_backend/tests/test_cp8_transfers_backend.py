"""Focused executable CP8 security/order regressions without a database."""
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from api.warehouse import transfers, transfer_policy
from domains.authorization.backoffice_access import BackofficeCapabilityAccessRejected
from schemas import TransferDestinationPolicySaveRequest


@pytest.mark.asyncio
async def test_override_candidates_require_send_and_exact_override_before_queries():
    db = NS(execute=AsyncMock(), scalar=AsyncMock(return_value=7))
    async def require(code, location_id=None, **kwargs):
        if code == "transfer.send": raise BackofficeCapabilityAccessRejected()
    access = NS(require=require, company_id=1, db=db)
    with pytest.raises(HTTPException) as denied:
        await transfers.get_unified_transfer_override_options(7, 11, db, access)
    assert denied.value.status_code == 403
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_policy_read_checks_reference_visibility_before_serializing():
    db = NS(execute=AsyncMock(), scalar=AsyncMock(return_value=7))
    async def require(code, location_id=None, **kwargs):
        if code == "location.read": raise BackofficeCapabilityAccessRejected()
    access = NS(require=require, company_id=1, db=db)
    policy = NS(validated_payload=dict(quarantine_location_id=7, disposal_location_id=8, vendor_return_staging_location_id=9))
    with patch.object(transfer_policy, "get_transfer_destination_policy_state", AsyncMock(return_value=(None, policy))):
        with pytest.raises(HTTPException) as denied:
            await transfer_policy.get_transfer_destination_policy(db, access)
    assert denied.value.status_code == 403


@pytest.mark.asyncio
async def test_draft_reference_permission_precedes_idempotency_or_mutation():
    db = NS(execute=AsyncMock(), scalar=AsyncMock(return_value=7), rollback=AsyncMock())
    async def require(code, location_id=None, **kwargs):
        if code == "location.read": raise BackofficeCapabilityAccessRejected()
    access = NS(require=require, company_id=1, db=db)
    payload = TransferDestinationPolicySaveRequest(request_id=uuid4(), payload=dict(
        quarantine_location_id=7, disposal_location_id=8, vendor_return_staging_location_id=9))
    with patch.object(transfer_policy, "begin_idempotent_operation", AsyncMock()) as begin:
        with pytest.raises(HTTPException) as denied:
            await transfer_policy.save_transfer_destination_policy(payload, db, access, NS(id=123))
        begin.assert_not_awaited()
    assert denied.value.status_code == 403
    db.rollback.assert_awaited_once()
