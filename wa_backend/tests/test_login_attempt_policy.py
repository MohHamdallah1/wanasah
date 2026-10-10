from __future__ import annotations

from datetime import datetime, timezone
import unittest

from domains.auth_sessions.login_attempts import (
    LOGIN_ATTEMPT_WINDOW,
    MAX_FAILED_ATTEMPTS,
    LoginAttemptRateLimited,
    LoginAttemptState,
    enforce_company_login_attempt_limit,
    read_login_attempt_state,
    record_login_attempt,
)


class _FakeDB:
    def __init__(self, scalar_value=0):
        self.scalar_value = scalar_value
        self.statements = []
        self.added = []

    async def scalar(self, statement):
        self.statements.append(statement)
        return self.scalar_value

    def add(self, value):
        self.added.append(value)


class LoginAttemptPolicyTests(unittest.IsolatedAsyncioTestCase):
    async def test_reads_exact_legacy_window_and_non_platform_failures(self):
        db = _FakeDB(3)
        now = datetime(2026, 10, 10, 9, 0, tzinfo=timezone.utc)

        state = await read_login_attempt_state(
            db,
            ip_address="203.0.113.9",
            now=now,
        )

        self.assertEqual(state.failed_count, 3)
        self.assertEqual(LOGIN_ATTEMPT_WINDOW.total_seconds(), 15 * 60)
        sql = str(db.statements[0])
        self.assertIn("company_code_attempted", sql)
        self.assertIn("is_successful IS false", sql)
        self.assertIn("created_at >=", sql)

    async def test_limit_allows_four_and_blocks_five(self):
        allowed = await enforce_company_login_attempt_limit(
            _FakeDB(MAX_FAILED_ATTEMPTS - 1),
            ip_address="203.0.113.10",
        )
        self.assertEqual(allowed.failed_count, 4)

        with self.assertRaises(LoginAttemptRateLimited):
            await enforce_company_login_attempt_limit(
                _FakeDB(MAX_FAILED_ATTEMPTS),
                ip_address="203.0.113.10",
            )

    def test_remaining_count_matches_legacy_failure_message(self):
        self.assertEqual(LoginAttemptState(0).remaining_after_next_failure, 4)
        self.assertEqual(LoginAttemptState(3).remaining_after_next_failure, 1)
        self.assertEqual(LoginAttemptState(4).remaining_after_next_failure, 0)
        self.assertEqual(LoginAttemptState(99).remaining_after_next_failure, 0)

    def test_record_attaches_to_caller_transaction_without_secret_fields(self):
        db = _FakeDB()
        attempt = record_login_attempt(
            db,
            ip_address="203.0.113.11",
            username="operator",
            company_code="WNS-01",
            successful=False,
        )

        self.assertEqual(db.added, [attempt])
        self.assertEqual(attempt.ip_address, "203.0.113.11")
        self.assertEqual(attempt.username_attempted, "operator")
        self.assertEqual(attempt.company_code_attempted, "WNS-01")
        self.assertFalse(attempt.is_successful)
        self.assertFalse(hasattr(attempt, "password"))
        self.assertFalse(hasattr(attempt, "token"))


if __name__ == "__main__":
    unittest.main()
