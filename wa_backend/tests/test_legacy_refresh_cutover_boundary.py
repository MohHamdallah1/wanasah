from __future__ import annotations

import unittest

from sqlalchemy.sql.dml import Update
from sqlalchemy.sql.selectable import Select

from domains.auth_sessions.legacy_cutover import (
    LegacyRefreshCutoverRejected,
    invalidate_legacy_refresh_sessions,
    legacy_refresh_session_counts,
)


class _FakeDB:
    def __init__(self, scalar_values: list[int]):
        self.scalar_values = list(scalar_values)
        self.statements = []
        self.commit_calls = 0
        self.rollback_calls = 0

    async def scalar(self, statement):
        self.statements.append(statement)
        if not self.scalar_values:
            raise AssertionError("unexpected scalar call")
        return self.scalar_values.pop(0)

    async def execute(self, statement):
        self.statements.append(statement)
        return object()

    async def commit(self):
        self.commit_calls += 1
        raise AssertionError("domain service must not commit")

    async def rollback(self):
        self.rollback_calls += 1
        raise AssertionError("domain service must not rollback")


class LegacyRefreshCutoverBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_counts_are_company_scoped(self):
        db = _FakeDB([8, 2])
        result = await legacy_refresh_session_counts(db, company_id=7)

        self.assertEqual(result.company_id, 7)
        self.assertEqual(result.total_sessions, 8)
        self.assertEqual(result.active_sessions, 2)
        self.assertEqual(len(db.statements), 2)
        sql = "\n".join(str(stmt) for stmt in db.statements)
        self.assertIn("refresh_tokens", sql)
        self.assertIn("drivers.company_id", sql)
        self.assertIn("refresh_tokens.is_revoked", sql)

    async def test_invalidation_locks_updates_and_verifies_zero_active(self):
        # before(total, active), after(total, active)
        db = _FakeDB([8, 2, 8, 0])
        result = await invalidate_legacy_refresh_sessions(db, company_id=7)

        self.assertEqual(result.company_id, 7)
        self.assertEqual(result.total_sessions, 8)
        self.assertEqual(result.newly_revoked, 2)
        self.assertEqual(result.remaining_active, 0)

        self.assertEqual(len(db.statements), 6)
        self.assertIsInstance(db.statements[2], Select)
        self.assertIsInstance(db.statements[3], Update)
        self.assertIn("FOR UPDATE", str(db.statements[2]))
        self.assertIn("is_revoked", str(db.statements[3]))
        self.assertEqual(db.commit_calls, 0)
        self.assertEqual(db.rollback_calls, 0)

    async def test_idempotent_rerun_when_everything_is_already_revoked(self):
        db = _FakeDB([8, 0, 8, 0])
        result = await invalidate_legacy_refresh_sessions(db, company_id=7)
        self.assertEqual(result.newly_revoked, 0)
        self.assertEqual(result.remaining_active, 0)

    async def test_fail_closed_if_active_legacy_session_remains(self):
        db = _FakeDB([8, 2, 8, 1])
        with self.assertRaises(LegacyRefreshCutoverRejected) as failure:
            await invalidate_legacy_refresh_sessions(db, company_id=7)
        self.assertEqual(str(failure.exception), "")
        self.assertEqual(db.commit_calls, 0)
        self.assertEqual(db.rollback_calls, 0)

    async def test_invalid_company_id_rejected_before_database_use(self):
        for invalid in (0, -1, True, None, "7"):
            with self.subTest(invalid=invalid):
                db = _FakeDB([])
                with self.assertRaises(LegacyRefreshCutoverRejected):
                    await invalidate_legacy_refresh_sessions(db, company_id=invalid)  # type: ignore[arg-type]
                self.assertEqual(db.statements, [])

    async def test_result_contains_no_token_or_credential_material(self):
        db = _FakeDB([3, 1, 3, 0])
        result = await invalidate_legacy_refresh_sessions(db, company_id=5)
        forbidden = {"token", "refresh_token", "password", "password_hash", "username"}
        self.assertTrue(forbidden.isdisjoint(vars(result)))


if __name__ == "__main__":
    unittest.main()
