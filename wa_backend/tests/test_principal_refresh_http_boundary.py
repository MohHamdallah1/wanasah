from __future__ import annotations

import inspect
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from api.authentication import refresh as http_refresh
from api.authentication.schemas import PrincipalTokenPairResponse
from domains.auth_sessions.codec import decode_company_token
from domains.auth_sessions.refresh_sessions import (
    RefreshSessionRejected,
    RefreshSessionResult,
)
from domains.identity.channels import IdentityChannel
from domains.identity.types import PrincipalType


SECRET = "Aa1234567890Bb1234567890Cc1234567890Dd"


class _Transaction:
    def __init__(self, db: "_FakeDB") -> None:
        self.db = db

    async def __aenter__(self):
        self.db.in_tx = True
        self.db.begins += 1
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.db.in_tx = False
        if exc_type is None:
            self.db.commits += 1
        else:
            self.db.rollbacks += 1
        return False


class _FakeDB:
    def __init__(self) -> None:
        self.in_tx = False
        self.begins = 0
        self.commits = 0
        self.rollbacks = 0

    def begin(self) -> _Transaction:
        return _Transaction(self)


def _result(
    *,
    refresh_token: str = "successor-refresh",
    principal_id: int = 41,
    company_id: int = 7,
    channel: IdentityChannel = IdentityChannel.DASHBOARD,
    principal_type: PrincipalType = PrincipalType.BACKOFFICE,
    auth_revision: int = 9,
) -> RefreshSessionResult:
    return RefreshSessionResult(
        principal_id=principal_id,
        company_id=company_id,
        channel=channel,
        principal_type=principal_type,
        auth_revision=auth_revision,
        refresh_token=refresh_token,
    )


class PrincipalRefreshHTTPBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_successful_rotation(self):
        db = _FakeDB()
        rotated = _result()
        rotate = AsyncMock(return_value=rotated)

        with patch.object(http_refresh, "rotate_refresh_session", rotate):
            response = await http_refresh.refresh_principal_session(
                db, refresh_token="predecessor-refresh", secret=SECRET
            )

        self.assertIsInstance(response, PrincipalTokenPairResponse)
        self.assertEqual(response.refresh_token, "successor-refresh")
        rotate.assert_awaited_once_with(
            db, "predecessor-refresh", secret=SECRET
        )
        self.assertEqual((db.begins, db.commits, db.rollbacks), (1, 1, 0))

    async def test_grace_replay_returns_same_recent_successor_refresh(self):
        db = _FakeDB()
        rotated = _result(refresh_token="same-successor")
        rotate = AsyncMock(side_effect=[rotated, rotated])

        with patch.object(http_refresh, "rotate_refresh_session", rotate):
            first = await http_refresh.refresh_principal_session(
                db, refresh_token="replayed-predecessor", secret=SECRET
            )
            second = await http_refresh.refresh_principal_session(
                db, refresh_token="replayed-predecessor", secret=SECRET
            )

        self.assertEqual(first.refresh_token, "same-successor")
        self.assertEqual(second.refresh_token, "same-successor")
        self.assertEqual((db.begins, db.commits, db.rollbacks), (2, 2, 0))

    async def test_invalid_refresh_fails_closed(self):
        db = _FakeDB()
        with patch.object(
            http_refresh,
            "rotate_refresh_session",
            AsyncMock(side_effect=RefreshSessionRejected()),
        ):
            with self.assertRaises(HTTPException) as caught:
                await http_refresh.refresh_principal_session(
                    db, refresh_token="invalid", secret=SECRET
                )

        self.assertEqual(caught.exception.status_code, 401)
        self.assertEqual(caught.exception.detail, "Authentication failed.")
        self.assertEqual((db.commits, db.rollbacks), (0, 1))

    async def test_expired_refresh_fails_closed(self):
        db = _FakeDB()
        with patch.object(
            http_refresh,
            "rotate_refresh_session",
            AsyncMock(side_effect=RefreshSessionRejected()),
        ):
            with self.assertRaises(HTTPException) as caught:
                await http_refresh.refresh_principal_session(
                    db, refresh_token="expired", secret=SECRET
                )

        self.assertEqual(caught.exception.status_code, 401)
        self.assertNotIn("expired", str(caught.exception.detail).lower())
        self.assertEqual(db.rollbacks, 1)

    async def test_identity_or_channel_mismatch_rejection_is_generic(self):
        db = _FakeDB()
        rotate = AsyncMock(side_effect=RefreshSessionRejected())
        with patch.object(http_refresh, "rotate_refresh_session", rotate):
            with self.assertRaises(HTTPException) as caught:
                await http_refresh.refresh_principal_session(
                    db, refresh_token="mismatched", secret=SECRET
                )

        self.assertEqual(caught.exception.status_code, 401)
        self.assertEqual(caught.exception.detail, "Authentication failed.")
        self.assertEqual(db.rollbacks, 1)

    async def test_access_token_claims_match_exact_rotated_identity(self):
        db = _FakeDB()
        rotated = _result(
            principal_id=812,
            company_id=33,
            channel=IdentityChannel.FIELD,
            principal_type=PrincipalType.FIELD_REPRESENTATIVE,
            auth_revision=14,
            refresh_token="field-successor",
        )
        with patch.object(
            http_refresh, "rotate_refresh_session", AsyncMock(return_value=rotated)
        ):
            response = await http_refresh.refresh_principal_session(
                db, refresh_token="field-predecessor", secret=SECRET
            )

        claims = decode_company_token(
            response.token, secret=SECRET, expected_type="access"
        )
        self.assertEqual(claims.principal_id, rotated.principal_id)
        self.assertEqual(claims.company_id, rotated.company_id)
        self.assertEqual(claims.channel, rotated.channel.value)
        self.assertEqual(claims.principal_type, rotated.principal_type.value)
        self.assertEqual(claims.auth_revision, rotated.auth_revision)
        self.assertEqual(response.refresh_token, rotated.refresh_token)

    async def test_transaction_commits_on_success(self):
        db = _FakeDB()
        with patch.object(
            http_refresh,
            "rotate_refresh_session",
            AsyncMock(return_value=_result()),
        ):
            await http_refresh.refresh_principal_session(
                db, refresh_token="old", secret=SECRET
            )

        self.assertEqual(db.begins, 1)
        self.assertEqual(db.commits, 1)
        self.assertEqual(db.rollbacks, 0)

    async def test_transaction_rolls_back_on_failure(self):
        db = _FakeDB()
        with patch.object(
            http_refresh,
            "rotate_refresh_session",
            AsyncMock(side_effect=RefreshSessionRejected()),
        ):
            with self.assertRaises(HTTPException):
                await http_refresh.refresh_principal_session(
                    db, refresh_token="bad", secret=SECRET
                )

        self.assertEqual(db.begins, 1)
        self.assertEqual(db.commits, 0)
        self.assertEqual(db.rollbacks, 1)

    async def test_response_conforms_to_principal_token_pair_response(self):
        db = _FakeDB()
        with patch.object(
            http_refresh,
            "rotate_refresh_session",
            AsyncMock(return_value=_result(refresh_token="next")),
        ):
            response = await http_refresh.refresh_principal_session(
                db, refresh_token="old", secret=SECRET
            )

        self.assertEqual(
            set(response.model_dump()),
            {"token", "refresh_token"},
        )
        self.assertTrue(response.token)
        self.assertEqual(response.refresh_token, "next")

    def test_boundary_has_no_legacy_identity_or_authority_dependencies(self):
        source = inspect.getsource(http_refresh)
        self.assertNotIn("Driver", source)
        self.assertNotIn("RefreshToken", source)
        self.assertNotIn("is_admin", source)
        self.assertNotIn("role", source.lower())
        self.assertNotIn("logger", source.lower())


if __name__ == "__main__":
    unittest.main()
