from __future__ import annotations

import inspect
import unittest

from domains.auth_sessions.access_revocation import (
    AccessRevocationRejected,
    blacklist_authenticated_access_token,
)
import domains.auth_sessions.access_revocation as revocation_module
from domains.auth_sessions.claims import CompanyTokenClaims


class FakeDB:
    def __init__(self, *, existing_id=None):
        self.existing_id = existing_id
        self.added = []
        self.scalar_calls = 0
        self.commits = 0
        self.rollbacks = 0

    async def scalar(self, statement):
        self.scalar_calls += 1
        compiled = statement.compile()
        self.params = dict(compiled.params)
        return self.existing_id

    def add(self, value):
        self.added.append(value)

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


def access_claims() -> CompanyTokenClaims:
    return CompanyTokenClaims(
        token_type="access",
        principal_id=11,
        company_id=7,
        channel="DASHBOARD",
        principal_type="BACKOFFICE",
        auth_revision=3,
        jti="access-jti",
        exp=9999999999,
    )


def refresh_claims() -> CompanyTokenClaims:
    return CompanyTokenClaims(
        token_type="refresh",
        principal_id=11,
        company_id=7,
        channel="DASHBOARD",
        principal_type="BACKOFFICE",
        auth_revision=3,
        jti="refresh-jti",
        exp=9999999999,
    )


class CanonicalAccessRevocationTests(unittest.IsolatedAsyncioTestCase):
    async def test_new_exact_token_is_queued_once(self):
        db = FakeDB()
        token = "signed-access-token"

        created = await blacklist_authenticated_access_token(
            db, token=token, claims=access_claims()
        )

        self.assertTrue(created)
        self.assertEqual(len(db.added), 1)
        self.assertEqual(db.added[0].token, token)
        self.assertIn(token, db.params.values())

    async def test_existing_blacklist_row_is_idempotent(self):
        db = FakeDB(existing_id=91)

        created = await blacklist_authenticated_access_token(
            db, token="signed-access-token", claims=access_claims()
        )

        self.assertFalse(created)
        self.assertEqual(db.added, [])

    async def test_refresh_claims_are_rejected(self):
        db = FakeDB()
        with self.assertRaises(AccessRevocationRejected):
            await blacklist_authenticated_access_token(
                db, token="signed-refresh-token", claims=refresh_claims()
            )
        self.assertEqual(db.scalar_calls, 0)
        self.assertEqual(db.added, [])

    async def test_empty_or_oversized_token_rejected_before_database(self):
        for token in ("", "x" * 501):
            db = FakeDB()
            with self.assertRaises(AccessRevocationRejected):
                await blacklist_authenticated_access_token(
                    db, token=token, claims=access_claims()
                )
            self.assertEqual(db.scalar_calls, 0)
            self.assertEqual(db.added, [])

    async def test_transaction_ownership_stays_with_caller(self):
        db = FakeDB()
        await blacklist_authenticated_access_token(
            db, token="signed-access-token", claims=access_claims()
        )
        self.assertEqual(db.commits, 0)
        self.assertEqual(db.rollbacks, 0)

    def test_module_has_no_refresh_driver_or_legacy_authority(self):
        source = inspect.getsource(revocation_module)
        self.assertNotIn("RefreshToken", source)
        self.assertNotIn("Driver", source)
        self.assertNotIn("is_admin", source)
        self.assertNotIn("commit(", source)
        self.assertNotIn("rollback(", source)


if __name__ == "__main__":
    unittest.main()
