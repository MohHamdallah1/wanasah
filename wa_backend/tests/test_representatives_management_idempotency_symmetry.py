from __future__ import annotations

from decimal import Decimal
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from sqlalchemy.ext.asyncio import AsyncSession


BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault(
    "SECRET_KEY",
    "RepresentativeManagementSyntheticSecret123456789012345678901234567890",
)
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://representatives_unit@127.0.0.1:1/representatives_unit",
)
os.environ.setdefault(
    "DATABASE_URL_MIGRATION",
    "postgresql+asyncpg://representatives_admin@127.0.0.1:1/representatives_unit",
)

import domains.representatives.management as management_module
from domains.representatives.contracts import (
    CreateRepresentativeCommand,
    RepresentativeError,
    UpdateRepresentativeCommand,
)
from domains.representatives.repository import guard_representative_request_identity


REQUEST_ID = "3d1a194f-f9a8-4bb2-a128-e4abed0e8101"
CANONICAL_REQUEST_ID = "3d1a194f-f9a8-4bb2-a128-e4abed0e8101"


def result(*, all_values=()):
    value = Mock()
    value.scalars.return_value.all.return_value = list(all_values)
    return value


def db_mock() -> MagicMock:
    db = MagicMock(spec=AsyncSession)
    db.execute = AsyncMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


class RepresentativeManagementIdempotencySymmetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_existing_representative_operation_blocks_cross_operation_reuse(self):
        cases = (
            ("REPRESENTATIVE_DEACTIVATE", "REPRESENTATIVE_CREATE"),
            ("REPRESENTATIVE_CREDENTIAL_RESET", "REPRESENTATIVE_UPDATE"),
            ("REPRESENTATIVE_CREATE", "REPRESENTATIVE_DEACTIVATE"),
        )
        for existing_operation, requested_operation in cases:
            with self.subTest(
                existing_operation=existing_operation,
                requested_operation=requested_operation,
            ):
                db = db_mock()
                db.execute.side_effect = [
                    result(),
                    result(all_values=[existing_operation]),
                ]
                with self.assertRaises(RepresentativeError) as rejected:
                    await guard_representative_request_identity(
                        db,
                        company_id=7,
                        request_id=REQUEST_ID,
                        operation=requested_operation,
                    )
                self.assertEqual(rejected.exception.status_code, 409)
                self.assertEqual(
                    rejected.exception.code,
                    "REPRESENTATIVE_IDEMPOTENCY_CONFLICT",
                )

    async def test_create_uses_family_guard_and_preserves_same_operation_replay(self):
        db = db_mock()
        replay = {
            "id": 11,
            "full_name": "Rep",
            "username": "rep",
            "phone_number": None,
            "is_active": True,
            "can_allow_debt": False,
            "max_debt_limit": "0.000",
        }
        command = CreateRepresentativeCommand(
            request_id=REQUEST_ID,
            full_name="Rep",
            username="rep",
            password="Password123",
            phone_number="0790000000",
            can_allow_debt=False,
            max_debt_limit=Decimal("0.000"),
        )
        guard = AsyncMock(return_value=CANONICAL_REQUEST_ID)
        begin = AsyncMock(return_value=(object(), replay))
        with (
            patch.object(
                management_module,
                "_create_request_hash",
                new=Mock(return_value="a" * 64),
            ),
            patch.object(
                management_module,
                "guard_representative_request_identity",
                new=guard,
            ),
            patch.object(
                management_module,
                "begin_idempotent_operation",
                new=begin,
            ),
            patch.object(
                management_module,
                "username_exists",
                new=AsyncMock(),
            ) as username_exists,
            patch.object(
                management_module,
                "create_representative_persistence",
                new=AsyncMock(),
            ) as persist,
        ):
            response = await management_module.create_representative(
                db,
                company_id=7,
                actor_id=90,
                command=command,
            )

        self.assertEqual(response, replay)
        guard.assert_awaited_once_with(
            db,
            company_id=7,
            request_id=REQUEST_ID,
            operation="REPRESENTATIVE_CREATE",
        )
        self.assertEqual(begin.await_args.kwargs["request_id"], CANONICAL_REQUEST_ID)
        self.assertEqual(begin.await_args.kwargs["operation"], "REPRESENTATIVE_CREATE")
        username_exists.assert_not_awaited()
        persist.assert_not_awaited()
        db.rollback.assert_awaited_once_with()
        db.commit.assert_not_awaited()

    async def test_update_uses_family_guard_and_preserves_same_operation_replay(self):
        db = db_mock()
        replay = {
            "id": 11,
            "full_name": "Updated Rep",
            "username": "rep",
            "phone_number": None,
            "is_active": True,
            "can_allow_debt": False,
            "max_debt_limit": "0.000",
        }
        command = UpdateRepresentativeCommand(
            request_id=REQUEST_ID,
            fields={"full_name": "Updated Rep"},
        )
        guard = AsyncMock(return_value=CANONICAL_REQUEST_ID)
        begin = AsyncMock(return_value=(object(), replay))
        with (
            patch.object(
                management_module,
                "guard_representative_request_identity",
                new=guard,
            ),
            patch.object(
                management_module,
                "begin_idempotent_operation",
                new=begin,
            ),
            patch.object(
                management_module,
                "require_operational_compatibility",
                new=AsyncMock(),
            ) as require_compat,
        ):
            response = await management_module.update_representative(
                db,
                company_id=7,
                actor_id=90,
                representative_id=11,
                command=command,
            )

        self.assertEqual(response, replay)
        guard.assert_awaited_once_with(
            db,
            company_id=7,
            request_id=REQUEST_ID,
            operation="REPRESENTATIVE_UPDATE",
        )
        self.assertEqual(begin.await_args.kwargs["request_id"], CANONICAL_REQUEST_ID)
        self.assertEqual(begin.await_args.kwargs["operation"], "REPRESENTATIVE_UPDATE")
        require_compat.assert_not_awaited()
        db.rollback.assert_awaited_once_with()
        db.commit.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
