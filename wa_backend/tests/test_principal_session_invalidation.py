from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from domains.auth_sessions.invalidation import (
    PrincipalSessionInvalidationRejected,
    PrincipalSessionInvalidationTransactionRequired,
    revoke_principal_refresh_sessions,
)
from domains.identity.channels import IdentityChannel


class _ScalarRows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class _FakeDB:
    def __init__(self, *, rows=None, tenant=None, in_transaction=True):
        self.rows = list(rows or [])
        self.tenant = tenant
        self._in_transaction = in_transaction
        self.flush_count = 0
        self.commit_count = 0
        self.rollback_count = 0
        self.events = []
        self.last_statement = None

    def in_transaction(self):
        return self._in_transaction

    async def scalar(self, statement):
        self.events.append("tenant_read")
        return self.tenant

    async def execute(self, statement, params=None):
        self.events.append("tenant_set")
        self.tenant = int(params["tenant"])
        return None

    async def scalars(self, statement):
        self.events.append("session_lock")
        self.last_statement = statement
        params = statement.compile().params

        company_id = next(
            value for key, value in params.items() if key.startswith("company_id")
        )
        principal_id = next(
            value for key, value in params.items() if key.startswith("principal_id")
        )
        channel_values = None
        for key, value in params.items():
            if key.startswith("channel"):
                channel_values = value if isinstance(value, (list, tuple)) else [value]
                break

        selected = [
            row
            for row in self.rows
            if row.company_id == company_id
            and row.principal_id == principal_id
            and (channel_values is None or row.channel in channel_values)
        ]
        return _ScalarRows(selected)

    async def flush(self):
        self.flush_count += 1

    async def commit(self):
        self.commit_count += 1

    async def rollback(self):
        self.rollback_count += 1


def _principal(company_id=7, principal_id=11, *, active=True):
    return SimpleNamespace(
        company_id=company_id,
        id=principal_id,
        is_active=active,
    )


def _session(
    session_id,
    *,
    company_id=7,
    principal_id=11,
    channel="DASHBOARD",
    revoked=False,
    replaced_by_id=None,
):
    return SimpleNamespace(
        id=session_id,
        company_id=company_id,
        principal_id=principal_id,
        channel=channel,
        is_revoked=revoked,
        replaced_by_id=replaced_by_id,
    )


class PrincipalSessionInvalidationTests(unittest.IsolatedAsyncioTestCase):
    async def _call(
        self,
        db,
        *,
        principal=None,
        channel=None,
        company_id=7,
        principal_id=11,
    ):
        resolved_principal = (
            _principal(company_id, principal_id) if principal is None else principal
        )
        with patch(
            "domains.auth_sessions.invalidation.load_principal_by_id",
            return_value=resolved_principal,
        ):
            return await revoke_principal_refresh_sessions(
                db,
                company_id=company_id,
                principal_id=principal_id,
                channel=channel,
            )

    async def test_revoke_all_sessions_for_principal(self):
        rows = [
            _session(1, channel="DASHBOARD"),
            _session(2, channel="FIELD"),
        ]
        db = _FakeDB(rows=rows)

        changed = await self._call(db)

        self.assertEqual(changed, 2)
        self.assertTrue(all(row.is_revoked for row in rows))
        self.assertEqual(db.flush_count, 1)

    async def test_channel_specific_revoke(self):
        dashboard = _session(1, channel="DASHBOARD")
        field = _session(2, channel="FIELD")
        db = _FakeDB(rows=[dashboard, field])

        changed = await self._call(db, channel=IdentityChannel.FIELD)

        self.assertEqual(changed, 1)
        self.assertFalse(dashboard.is_revoked)
        self.assertTrue(field.is_revoked)

    async def test_other_principal_untouched(self):
        target = _session(1)
        other = _session(2, principal_id=99)
        db = _FakeDB(rows=[target, other])

        changed = await self._call(db)

        self.assertEqual(changed, 1)
        self.assertTrue(target.is_revoked)
        self.assertFalse(other.is_revoked)

    async def test_other_company_untouched(self):
        target = _session(1)
        other = _session(2, company_id=8)
        db = _FakeDB(rows=[target, other])

        changed = await self._call(db)

        self.assertEqual(changed, 1)
        self.assertTrue(target.is_revoked)
        self.assertFalse(other.is_revoked)

    async def test_revoked_rows_become_grace_dead(self):
        predecessor = _session(1, revoked=True, replaced_by_id=2)
        successor = _session(2, revoked=False)
        db = _FakeDB(rows=[predecessor, successor])

        changed = await self._call(db)

        self.assertEqual(changed, 2)
        self.assertIsNone(predecessor.replaced_by_id)
        self.assertTrue(successor.is_revoked)

    async def test_already_revoked_repeat_returns_zero(self):
        row = _session(1, revoked=True, replaced_by_id=None)
        db = _FakeDB(rows=[row])

        first = await self._call(db)
        second = await self._call(db)

        self.assertEqual(first, 0)
        self.assertEqual(second, 0)
        self.assertEqual(db.flush_count, 0)

    async def test_inactive_principal_still_supported(self):
        row = _session(1)
        db = _FakeDB(rows=[row])

        changed = await self._call(db, principal=_principal(active=False))

        self.assertEqual(changed, 1)
        self.assertTrue(row.is_revoked)

    async def test_missing_or_wrong_principal_rejected(self):
        db = _FakeDB()

        with patch(
            "domains.auth_sessions.invalidation.load_principal_by_id",
            return_value=None,
        ):
            with self.assertRaises(PrincipalSessionInvalidationRejected):
                await revoke_principal_refresh_sessions(
                    db, company_id=7, principal_id=11
                )

        for wrong in (
            _principal(company_id=8, principal_id=11),
            _principal(company_id=7, principal_id=12),
        ):
            with self.subTest(wrong=wrong):
                with patch(
                    "domains.auth_sessions.invalidation.load_principal_by_id",
                    return_value=wrong,
                ):
                    with self.assertRaises(PrincipalSessionInvalidationRejected):
                        await revoke_principal_refresh_sessions(
                            db, company_id=7, principal_id=11
                        )

    async def test_wrong_tenant_rejected(self):
        db = _FakeDB(tenant=8)
        with self.assertRaises(PrincipalSessionInvalidationRejected):
            await self._call(db)
        self.assertNotIn("session_lock", db.events)

    async def test_invalid_channel_rejected(self):
        db = _FakeDB()
        with self.assertRaises(PrincipalSessionInvalidationRejected):
            await self._call(db, channel="ADMIN")
        self.assertEqual(db.events, [])

    async def test_transaction_ownership_enforced(self):
        db = _FakeDB(in_transaction=False)
        with self.assertRaises(PrincipalSessionInvalidationTransactionRequired):
            await self._call(db)
        self.assertEqual(db.events, [])

    async def test_no_commit_or_rollback(self):
        row = _session(1)
        db = _FakeDB(rows=[row])

        changed = await self._call(db)

        self.assertEqual(changed, 1)
        self.assertEqual(db.commit_count, 0)
        self.assertEqual(db.rollback_count, 0)


if __name__ == "__main__":
    unittest.main()
