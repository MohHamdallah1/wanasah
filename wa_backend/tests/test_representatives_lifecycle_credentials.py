from __future__ import annotations

import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession


BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault(
    "SECRET_KEY",
    "RepresentativeLifecycleSyntheticSecret123456789012345678901234567890",
)
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://representatives_unit@127.0.0.1:1/representatives_unit",
)
os.environ.setdefault(
    "DATABASE_URL_MIGRATION",
    "postgresql+asyncpg://representatives_admin@127.0.0.1:1/representatives_unit",
)

import domains.representatives.credentials as credentials_module
import domains.representatives.lifecycle as lifecycle_module
from domains.identity.channels import IdentityChannel
from domains.representatives.contracts import (
    RepresentativeError,
    RepresentativeLifecycleCommand,
    ResetRepresentativeCredentialsCommand,
)
from domains.representatives.lifecycle_guards import (
    assert_representative_deactivation_safe,
)
from domains.representatives.repository import guard_representative_request_identity


REQUEST_ID = "3d1a194f-f9a8-4bb2-a128-e4abed0e8101"


def result(*, first=None, all_values=()):
    value = Mock()
    value.scalars.return_value.first.return_value = first
    value.scalars.return_value.all.return_value = list(all_values)
    return value


def db_mock() -> MagicMock:
    db = MagicMock(spec=AsyncSession)
    db.execute = AsyncMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


def sql(statement) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


class RepresentativeLifecycleGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_each_source_proven_blocker_fails_closed(self):
        cases = (
            ("OPEN_WORK_SESSION", [1]),
            ("CURRENT_DISPATCH_ROUTE", [None, 2]),
            ("PENDING_HANDSHAKE_TRANSFER", [None, None, 3]),
            ("UNRECONCILED_WORK_SESSION", [None, None, None, 4]),
            ("UNRESOLVED_VEHICLE_RECON", [None, None, None, None, 5]),
        )
        for expected_blocker, values in cases:
            with self.subTest(blocker=expected_blocker):
                db = db_mock()
                db.execute.side_effect = [result(first=value) for value in values]
                with self.assertRaises(RepresentativeError) as rejected:
                    await assert_representative_deactivation_safe(
                        db,
                        company_id=7,
                        legacy_driver_id=33,
                    )
                self.assertEqual(rejected.exception.status_code, 409)
                self.assertEqual(
                    rejected.exception.code,
                    "REPRESENTATIVE_DEACTIVATION_BLOCKED",
                )
                self.assertEqual(
                    rejected.exception.context,
                    {"blocker": expected_blocker},
                )

    async def test_blocker_queries_preserve_exact_operational_conditions(self):
        db = db_mock()
        db.execute.side_effect = [result(first=None) for _ in range(5)]
        await assert_representative_deactivation_safe(
            db,
            company_id=7,
            legacy_driver_id=33,
        )
        queries = [call.args[0] for call in db.execute.await_args_list]
        self.assertEqual(len(queries), 5)

        open_session_sql = sql(queries[0])
        self.assertIn("work_sessions.company_id = 7", open_session_sql)
        self.assertIn("work_sessions.driver_id = 33", open_session_sql)
        self.assertIn("work_sessions.end_time IS NULL", open_session_sql)

        route_sql = sql(queries[1])
        self.assertIn("dispatch_routes.company_id = 7", route_sql)
        self.assertIn("dispatch_routes.driver_id = 33", route_sql)
        for status in ("'active'", "'waiting'", "'postponed'"):
            self.assertIn(status, route_sql)

        handshake_sql = sql(queries[2])
        self.assertIn("inventory_transfer_headers.company_id = 7", handshake_sql)
        self.assertIn("inventory_transfer_headers.workflow_type = 'HANDSHAKE'", handshake_sql)
        self.assertIn("inventory_transfer_headers.status = 'PENDING'", handshake_sql)
        self.assertIn("inventory_transfer_headers.expected_receiver_id = 33", handshake_sql)

        unreconciled_sql = sql(queries[3])
        self.assertIn("work_sessions.end_time IS NOT NULL", unreconciled_sql)
        self.assertIn("work_sessions.inventory_reconciled_at IS NULL", unreconciled_sql)
        self.assertNotIn("work_sessions.is_settled", unreconciled_sql)

        recon_sql = sql(queries[4])
        self.assertIn("stocktake_sessions.stocktake_type = 'VEHICLE_RECON'", recon_sql)
        for status in (
            "'DRAFT'",
            "'COUNTING'",
            "'PENDING_REVIEW'",
            "'RECOUNT_REQUIRED'",
            "'APPROVED'",
        ):
            self.assertIn(status, recon_sql)
        self.assertIn("work_sessions.company_id = 7", recon_sql)
        self.assertIn("work_sessions.driver_id = 33", recon_sql)

    async def test_inventory_reconciled_but_financially_unsettled_is_not_a_blocker(self):
        db = db_mock()
        db.execute.side_effect = [result(first=None) for _ in range(5)]
        await assert_representative_deactivation_safe(
            db,
            company_id=7,
            legacy_driver_id=33,
        )
        unreconciled_sql = sql(db.execute.await_args_list[3].args[0])
        self.assertIn("inventory_reconciled_at IS NULL", unreconciled_sql)
        self.assertNotIn("is_settled", unreconciled_sql)


class RepresentativeRequestIdentityTests(unittest.IsolatedAsyncioTestCase):
    async def test_same_request_id_cannot_be_reinterpreted_as_another_operation(self):
        db = db_mock()
        db.execute.side_effect = [
            result(),
            result(all_values=["REPRESENTATIVE_DEACTIVATE"]),
        ]
        with self.assertRaises(RepresentativeError) as rejected:
            await guard_representative_request_identity(
                db,
                company_id=7,
                request_id=REQUEST_ID,
                operation="REPRESENTATIVE_REACTIVATE",
            )
        self.assertEqual(rejected.exception.status_code, 409)
        self.assertEqual(
            rejected.exception.code,
            "REPRESENTATIVE_IDEMPOTENCY_CONFLICT",
        )


class RepresentativeLifecycleOrchestrationTests(unittest.IsolatedAsyncioTestCase):
    def _rows(self, *, active: bool, revision: int = 4):
        profile = SimpleNamespace(id=11, company_id=7, principal_id=22)
        principal = SimpleNamespace(
            id=22,
            company_id=7,
            is_active=active,
            auth_revision=revision,
            password_hash="canonical-old",
        )
        bridge = SimpleNamespace(
            company_id=7,
            classification="FIELD_ONLY",
            legacy_driver_id=33,
            field_principal_id=22,
            field_representative_id=11,
        )
        driver = SimpleNamespace(
            id=33,
            company_id=7,
            is_active=True,
            password_hash="legacy-stays",
        )
        return profile, principal, bridge, driver

    async def test_deactivate_bumps_revision_once_revokes_field_sessions_and_preserves_driver_state(self):
        db = db_mock()
        rows = self._rows(active=True)
        idem = object()
        with (
            patch.object(
                lifecycle_module,
                "guard_representative_request_identity",
                new=AsyncMock(return_value=REQUEST_ID),
            ),
            patch.object(
                lifecycle_module,
                "begin_idempotent_operation",
                new=AsyncMock(return_value=(idem, None)),
            ),
            patch.object(
                lifecycle_module,
                "require_operational_compatibility",
                new=AsyncMock(return_value=rows),
            ),
            patch.object(
                lifecycle_module,
                "assert_representative_deactivation_safe",
                new=AsyncMock(),
            ),
            patch.object(
                lifecycle_module,
                "revoke_principal_refresh_sessions",
                new=AsyncMock(return_value=2),
            ) as revoke,
            patch.object(lifecycle_module, "add_representative_audit", new=Mock()) as audit,
            patch.object(lifecycle_module, "complete_idempotent_operation", new=Mock()) as complete,
        ):
            response = await lifecycle_module.deactivate_representative(
                db,
                company_id=7,
                actor_id=90,
                representative_id=11,
                command=RepresentativeLifecycleCommand(request_id=REQUEST_ID),
            )

        profile, principal, bridge, driver = rows
        self.assertFalse(principal.is_active)
        self.assertEqual(principal.auth_revision, 5)
        self.assertTrue(driver.is_active)
        self.assertEqual(driver.id, 33)
        self.assertEqual(bridge.legacy_driver_id, 33)
        self.assertEqual(profile.id, 11)
        revoke.assert_awaited_once_with(
            db,
            company_id=7,
            principal_id=22,
            channel=IdentityChannel.FIELD,
        )
        self.assertEqual(response["state"], "INACTIVE")
        self.assertEqual(response["auth_revision"], 5)
        audit.assert_called_once()
        complete.assert_called_once()
        db.commit.assert_awaited_once_with()
        db.rollback.assert_not_awaited()

    async def test_deactivate_replay_does_not_repeat_revision_audit_or_revocation(self):
        db = db_mock()
        replay = {"representative_id": 11, "state": "INACTIVE", "auth_revision": 5}
        with (
            patch.object(
                lifecycle_module,
                "guard_representative_request_identity",
                new=AsyncMock(return_value=REQUEST_ID),
            ),
            patch.object(
                lifecycle_module,
                "begin_idempotent_operation",
                new=AsyncMock(return_value=(object(), replay)),
            ),
            patch.object(
                lifecycle_module,
                "require_operational_compatibility",
                new=AsyncMock(),
            ) as require_compat,
            patch.object(
                lifecycle_module,
                "revoke_principal_refresh_sessions",
                new=AsyncMock(),
            ) as revoke,
            patch.object(lifecycle_module, "add_representative_audit", new=Mock()) as audit,
        ):
            response = await lifecycle_module.deactivate_representative(
                db,
                company_id=7,
                actor_id=90,
                representative_id=11,
                command=RepresentativeLifecycleCommand(request_id=REQUEST_ID),
            )
        self.assertEqual(response, replay)
        require_compat.assert_not_awaited()
        revoke.assert_not_awaited()
        audit.assert_not_called()
        db.rollback.assert_awaited_once_with()
        db.commit.assert_not_awaited()

    async def test_reactivate_preserves_revision_ids_history_and_driver_active_state(self):
        db = db_mock()
        rows = self._rows(active=False, revision=5)
        with (
            patch.object(
                lifecycle_module,
                "guard_representative_request_identity",
                new=AsyncMock(return_value=REQUEST_ID),
            ),
            patch.object(
                lifecycle_module,
                "begin_idempotent_operation",
                new=AsyncMock(return_value=(object(), None)),
            ),
            patch.object(
                lifecycle_module,
                "require_operational_compatibility",
                new=AsyncMock(return_value=rows),
            ),
            patch.object(lifecycle_module, "add_representative_audit", new=Mock()),
            patch.object(lifecycle_module, "complete_idempotent_operation", new=Mock()),
        ):
            response = await lifecycle_module.reactivate_representative(
                db,
                company_id=7,
                actor_id=90,
                representative_id=11,
                command=RepresentativeLifecycleCommand(request_id=REQUEST_ID),
            )
        profile, principal, bridge, driver = rows
        self.assertTrue(principal.is_active)
        self.assertEqual(principal.auth_revision, 5)
        self.assertEqual((profile.id, principal.id, bridge.legacy_driver_id, driver.id), (11, 22, 33, 33))
        self.assertTrue(driver.is_active)
        self.assertEqual(response["auth_revision"], 5)
        db.commit.assert_awaited_once_with()

    async def test_cross_company_or_missing_target_stays_fail_closed_404(self):
        db = db_mock()
        not_found = RepresentativeError(
            "REPRESENTATIVE_NOT_FOUND",
            "Representative was not found.",
            status_code=404,
        )
        with (
            patch.object(
                lifecycle_module,
                "guard_representative_request_identity",
                new=AsyncMock(return_value=REQUEST_ID),
            ),
            patch.object(
                lifecycle_module,
                "begin_idempotent_operation",
                new=AsyncMock(return_value=(object(), None)),
            ),
            patch.object(
                lifecycle_module,
                "require_operational_compatibility",
                new=AsyncMock(side_effect=not_found),
            ),
        ):
            with self.assertRaises(RepresentativeError) as rejected:
                await lifecycle_module.deactivate_representative(
                    db,
                    company_id=7,
                    actor_id=90,
                    representative_id=999,
                    command=RepresentativeLifecycleCommand(request_id=REQUEST_ID),
                )
        self.assertEqual(rejected.exception.status_code, 404)
        self.assertEqual(rejected.exception.code, "REPRESENTATIVE_NOT_FOUND")
        db.rollback.assert_awaited_once_with()
        db.commit.assert_not_awaited()


class RepresentativeCredentialResetTests(unittest.IsolatedAsyncioTestCase):
    async def test_reset_mutates_only_canonical_password_bumps_once_and_revokes_field_sessions(self):
        db = db_mock()
        profile = SimpleNamespace(id=11, company_id=7, principal_id=22)
        principal = SimpleNamespace(
            id=22,
            company_id=7,
            is_active=True,
            auth_revision=8,
            password_hash="canonical-old",
        )
        bridge = SimpleNamespace(legacy_driver_id=33)
        driver = SimpleNamespace(
            id=33,
            company_id=7,
            is_active=True,
            password_hash="legacy-unchanged",
        )
        with (
            patch.object(
                credentials_module,
                "fingerprint_reset_password",
                new=Mock(return_value="f" * 64),
            ),
            patch.object(
                credentials_module,
                "guard_representative_request_identity",
                new=AsyncMock(return_value=REQUEST_ID),
            ),
            patch.object(
                credentials_module,
                "begin_idempotent_operation",
                new=AsyncMock(return_value=(object(), None)),
            ),
            patch.object(
                credentials_module,
                "load_management_row",
                new=AsyncMock(return_value=(profile, principal, bridge, driver)),
            ),
            patch.object(
                credentials_module,
                "_hash_reset_password",
                new=AsyncMock(return_value="canonical-new"),
            ) as hasher,
            patch.object(
                credentials_module,
                "revoke_principal_refresh_sessions",
                new=AsyncMock(return_value=3),
            ) as revoke,
            patch.object(credentials_module, "add_representative_audit", new=Mock()) as audit,
            patch.object(credentials_module, "complete_idempotent_operation", new=Mock()),
        ):
            response = await credentials_module.reset_representative_credentials(
                db,
                company_id=7,
                actor_id=90,
                representative_id=11,
                command=ResetRepresentativeCredentialsCommand(
                    request_id=REQUEST_ID,
                    new_password="NewPassword123",
                ),
            )
        hasher.assert_awaited_once_with("NewPassword123")
        self.assertEqual(principal.password_hash, "canonical-new")
        self.assertEqual(principal.auth_revision, 9)
        self.assertEqual(driver.password_hash, "legacy-unchanged")
        self.assertTrue(driver.is_active)
        revoke.assert_awaited_once_with(
            db,
            company_id=7,
            principal_id=22,
            channel=IdentityChannel.FIELD,
        )
        audit_payload = audit.call_args.kwargs
        self.assertNotIn("password", repr(audit_payload).lower())
        self.assertNotIn("canonical-new", repr(audit_payload))
        self.assertEqual(response["auth_revision"], 9)
        db.commit.assert_awaited_once_with()

    async def test_reset_replay_does_not_hash_bump_revoke_or_audit_again(self):
        db = db_mock()
        replay = {"representative_id": 11, "auth_revision": 9}
        with (
            patch.object(
                credentials_module,
                "fingerprint_reset_password",
                new=Mock(return_value="f" * 64),
            ),
            patch.object(
                credentials_module,
                "guard_representative_request_identity",
                new=AsyncMock(return_value=REQUEST_ID),
            ),
            patch.object(
                credentials_module,
                "begin_idempotent_operation",
                new=AsyncMock(return_value=(object(), replay)),
            ),
            patch.object(
                credentials_module,
                "load_management_row",
                new=AsyncMock(),
            ) as loader,
            patch.object(
                credentials_module,
                "_hash_reset_password",
                new=AsyncMock(),
            ) as hasher,
            patch.object(
                credentials_module,
                "revoke_principal_refresh_sessions",
                new=AsyncMock(),
            ) as revoke,
            patch.object(credentials_module, "add_representative_audit", new=Mock()) as audit,
        ):
            response = await credentials_module.reset_representative_credentials(
                db,
                company_id=7,
                actor_id=90,
                representative_id=11,
                command=ResetRepresentativeCredentialsCommand(
                    request_id=REQUEST_ID,
                    new_password="NewPassword123",
                ),
            )
        self.assertEqual(response, replay)
        loader.assert_not_awaited()
        hasher.assert_not_awaited()
        revoke.assert_not_awaited()
        audit.assert_not_called()
        db.rollback.assert_awaited_once_with()
        db.commit.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
