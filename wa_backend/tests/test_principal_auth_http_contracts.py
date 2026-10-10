from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

from pydantic import ValidationError


_MODULE_PATH = Path(__file__).resolve().parents[1] / "api" / "authentication" / "schemas.py"
_SPEC = importlib.util.spec_from_file_location("principal_auth_http_schemas", _MODULE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_HTTP_SCHEMAS = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_HTTP_SCHEMAS)

DashboardPrincipalLoginResponse = _HTTP_SCHEMAS.DashboardPrincipalLoginResponse
FieldPrincipalLoginResponse = _HTTP_SCHEMAS.FieldPrincipalLoginResponse
PrincipalLogoutResponse = _HTTP_SCHEMAS.PrincipalLogoutResponse
PrincipalTokenPairResponse = _HTTP_SCHEMAS.PrincipalTokenPairResponse


class PrincipalAuthHTTPContractsTests(unittest.TestCase):
    def dashboard_payload(self, **overrides):
        payload = {
            "token": "dashboard.access.jwt",
            "refresh_token": "dashboard.refresh.jwt",
            "principal_id": 101,
            "backoffice_user_id": 202,
            "channel": "DASHBOARD",
            "is_company_owner": False,
            "company_id": 303,
            "company_code": "WNS-01",
            "driver_id": 404,
            "driver_name": "Legacy Dashboard User",
            "is_admin": True,
            "dashboard_access": True,
        }
        payload.update(overrides)
        return payload

    def field_payload(self, **overrides):
        payload = {
            "token": "field.access.jwt",
            "refresh_token": "field.refresh.jwt",
            "principal_id": 111,
            "representative_id": 222,
            "channel": "FIELD",
            "company_id": 333,
            "company_code": "WNS-02",
            "driver_id": 444,
            "driver_name": "Legacy Field User",
            "is_admin": False,
        }
        payload.update(overrides)
        return payload

    def test_valid_dashboard_response(self):
        response = DashboardPrincipalLoginResponse(**self.dashboard_payload())
        self.assertEqual(response.channel, "DASHBOARD")
        self.assertEqual(response.principal_id, 101)
        self.assertEqual(response.backoffice_user_id, 202)
        self.assertEqual(response.driver_id, 404)
        self.assertTrue(response.dashboard_access)
        self.assertNotIn("representative_id", response.model_dump())

    def test_valid_field_response(self):
        response = FieldPrincipalLoginResponse(**self.field_payload())
        self.assertEqual(response.channel, "FIELD")
        self.assertEqual(response.principal_id, 111)
        self.assertEqual(response.representative_id, 222)
        self.assertEqual(response.driver_id, 444)
        self.assertNotIn("backoffice_user_id", response.model_dump())

    def test_wrong_channel_rejected(self):
        with self.assertRaises(ValidationError):
            DashboardPrincipalLoginResponse(**self.dashboard_payload(channel="FIELD"))
        with self.assertRaises(ValidationError):
            FieldPrincipalLoginResponse(**self.field_payload(channel="DASHBOARD"))

    def test_required_compatibility_fields_enforced(self):
        for field in ("driver_id", "driver_name", "is_admin", "dashboard_access"):
            payload = self.dashboard_payload()
            payload.pop(field)
            with self.subTest(model="dashboard", field=field):
                with self.assertRaises(ValidationError):
                    DashboardPrincipalLoginResponse(**payload)

        for field in ("driver_id", "driver_name", "is_admin"):
            payload = self.field_payload()
            payload.pop(field)
            with self.subTest(model="field", field=field):
                with self.assertRaises(ValidationError):
                    FieldPrincipalLoginResponse(**payload)

    def test_dashboard_and_field_identity_shapes_cannot_cross(self):
        dashboard = self.dashboard_payload(representative_id=999)
        with self.assertRaises(ValidationError):
            DashboardPrincipalLoginResponse(**dashboard)

        field = self.field_payload(backoffice_user_id=999)
        with self.assertRaises(ValidationError):
            FieldPrincipalLoginResponse(**field)

    def test_missing_canonical_ids_rejected(self):
        for field in ("principal_id", "backoffice_user_id", "company_id"):
            payload = self.dashboard_payload()
            payload.pop(field)
            with self.subTest(model="dashboard", field=field):
                with self.assertRaises(ValidationError):
                    DashboardPrincipalLoginResponse(**payload)

        for field in ("principal_id", "representative_id", "company_id"):
            payload = self.field_payload()
            payload.pop(field)
            with self.subTest(model="field", field=field):
                with self.assertRaises(ValidationError):
                    FieldPrincipalLoginResponse(**payload)

    def test_non_positive_canonical_ids_rejected(self):
        dashboard_cases = (
            {"principal_id": 0},
            {"backoffice_user_id": -1},
            {"company_id": 0},
        )
        for override in dashboard_cases:
            with self.subTest(model="dashboard", override=override):
                with self.assertRaises(ValidationError):
                    DashboardPrincipalLoginResponse(**self.dashboard_payload(**override))

        field_cases = (
            {"principal_id": 0},
            {"representative_id": -1},
            {"company_id": 0},
        )
        for override in field_cases:
            with self.subTest(model="field", override=override):
                with self.assertRaises(ValidationError):
                    FieldPrincipalLoginResponse(**self.field_payload(**override))

    def test_credentials_role_and_capabilities_rejected_as_extras(self):
        forbidden = {
            "password": "secret",
            "password_hash": "bcrypt-hash",
            "role": "Admin",
            "capabilities": ["inventory.read"],
        }
        for name, value in forbidden.items():
            with self.subTest(model="dashboard", field=name):
                with self.assertRaises(ValidationError):
                    DashboardPrincipalLoginResponse(
                        **self.dashboard_payload(**{name: value})
                    )
            with self.subTest(model="field", field=name):
                with self.assertRaises(ValidationError):
                    FieldPrincipalLoginResponse(**self.field_payload(**{name: value}))

    def test_identity_ids_are_independent_even_when_numbers_coincide(self):
        dashboard = DashboardPrincipalLoginResponse(
            **self.dashboard_payload(
                principal_id=7,
                backoffice_user_id=7,
                driver_id=7,
            )
        )
        self.assertEqual(dashboard.principal_id, 7)
        self.assertEqual(dashboard.backoffice_user_id, 7)
        self.assertEqual(dashboard.driver_id, 7)

        field = FieldPrincipalLoginResponse(
            **self.field_payload(
                principal_id=8,
                representative_id=8,
                driver_id=8,
            )
        )
        self.assertEqual(field.principal_id, 8)
        self.assertEqual(field.representative_id, 8)
        self.assertEqual(field.driver_id, 8)

    def test_non_empty_tokens_and_company_code_enforced(self):
        with self.assertRaises(ValidationError):
            DashboardPrincipalLoginResponse(**self.dashboard_payload(token=""))
        with self.assertRaises(ValidationError):
            FieldPrincipalLoginResponse(**self.field_payload(refresh_token=""))
        with self.assertRaises(ValidationError):
            DashboardPrincipalLoginResponse(**self.dashboard_payload(company_code="X"))

    def test_token_pair_contract(self):
        pair = PrincipalTokenPairResponse(token="access", refresh_token="refresh")
        self.assertEqual(
            pair.model_dump(),
            {"token": "access", "refresh_token": "refresh"},
        )
        with self.assertRaises(ValidationError):
            PrincipalTokenPairResponse(token="", refresh_token="refresh")
        with self.assertRaises(ValidationError):
            PrincipalTokenPairResponse(token="access", refresh_token="refresh", role="Admin")

    def test_logout_contract(self):
        response = PrincipalLogoutResponse(message="Logged out")
        self.assertEqual(response.model_dump(), {"message": "Logged out"})
        with self.assertRaises(ValidationError):
            PrincipalLogoutResponse(message="")
        with self.assertRaises(ValidationError):
            PrincipalLogoutResponse(message="Logged out", token="unexpected")

    def test_existing_legacy_login_response_remains_untouched(self):
        from schemas import LoginResponse as LegacyLoginResponse

        self.assertEqual(
            set(LegacyLoginResponse.model_fields),
            {
                "message",
                "token",
                "refresh_token",
                "driver_id",
                "driver_name",
                "is_admin",
                "dashboard_access",
                "company_id",
                "company_code",
            },
        )
        self.assertIs(LegacyLoginResponse.model_fields["dashboard_access"].default, False)


if __name__ == "__main__":
    unittest.main()
