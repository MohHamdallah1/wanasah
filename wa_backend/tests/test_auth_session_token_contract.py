from datetime import datetime, timezone
import unittest

import jwt

from domains.auth_sessions import (
    TokenContractError,
    decode_company_token,
    issue_access_token,
    issue_refresh_token,
)

SECRET = "test-secret-that-is-longer-than-32-bytes"


class CompanyTokenContractTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)

    def test_dashboard_access_token_has_only_canonical_identity_claims(self):
        token = issue_access_token(
            principal_id=11,
            company_id=7,
            channel="DASHBOARD",
            principal_type="BACKOFFICE",
            auth_revision=3,
            secret=SECRET,
            now=self.now,
        )
        payload = jwt.decode(
            token,
            SECRET,
            algorithms=["HS256"],
            options={"verify_exp": False},
        )
        self.assertEqual(payload["sub"], "11")
        self.assertEqual(payload["channel"], "DASHBOARD")
        self.assertEqual(payload["principal_type"], "BACKOFFICE")
        self.assertEqual(payload["auth_revision"], 3)
        self.assertNotIn("role", payload)
        self.assertNotIn("is_admin", payload)
        self.assertNotIn("username", payload)

    def test_field_refresh_round_trips_with_same_identity_channel(self):
        token = issue_refresh_token(
            principal_id=22,
            company_id=7,
            channel="FIELD",
            principal_type="FIELD_REPRESENTATIVE",
            auth_revision=4,
            secret=SECRET,
            now=self.now,
        )
        claims = decode_company_token(
            token, secret=SECRET, expected_type="refresh"
        )
        self.assertEqual(claims.principal_id, 22)
        self.assertEqual(claims.company_id, 7)
        self.assertEqual(claims.channel, "FIELD")
        self.assertEqual(claims.principal_type, "FIELD_REPRESENTATIVE")
        self.assertEqual(claims.auth_revision, 4)

    def test_wrong_channel_principal_pair_fails_before_signing(self):
        with self.assertRaises(TokenContractError):
            issue_access_token(
                principal_id=11,
                company_id=7,
                channel="DASHBOARD",
                principal_type="FIELD_REPRESENTATIVE",
                auth_revision=1,
                secret=SECRET,
                now=self.now,
            )

    def test_expected_type_cannot_be_switched(self):
        token = issue_refresh_token(
            principal_id=22,
            company_id=7,
            channel="FIELD",
            principal_type="FIELD_REPRESENTATIVE",
            auth_revision=1,
            secret=SECRET,
            now=self.now,
        )
        with self.assertRaises(TokenContractError):
            decode_company_token(token, secret=SECRET, expected_type="access")

    def test_missing_required_claim_is_rejected(self):
        token = jwt.encode(
            {
                "type": "access",
                "sub": "1",
                "company_id": 1,
                "channel": "DASHBOARD",
                "principal_type": "BACKOFFICE",
                "jti": "x",
                "exp": 4102444800,
            },
            SECRET,
            algorithm="HS256",
        )
        with self.assertRaises(jwt.MissingRequiredClaimError):
            decode_company_token(token, secret=SECRET)


if __name__ == "__main__":
    unittest.main()
