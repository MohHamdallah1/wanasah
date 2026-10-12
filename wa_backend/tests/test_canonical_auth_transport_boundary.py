"""Executable boundary proofs for the bounded public login and operational locator."""
from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

from test_canonical_auth_core_boundary import (
    BACKEND, identity_namespace, immediate, production_definitions,
)


class Payload:
    """A transport stand-in; real Pydantic validation is tested by the HTTP gate."""
    def __init__(self, **values):
        self.values = {}
        for parent in reversed(type(self).__mro__):
            for name in getattr(parent, "__annotations__", {}):
                if name in vars(parent):
                    self.values[name] = vars(parent)[name]
        self.values.update(values)

    def model_dump(self):
        return dict(self.values)


class DriverProvenance:
    id = 303

    @property
    def company_id(self):
        raise AssertionError("The public adapter must not derive tenant authority from Driver")

    @property
    def full_name(self):
        raise AssertionError("Display data must come from the canonical principal")

    @property
    def is_admin(self):
        raise AssertionError("Driver flags must never determine login authority/presentation")


class Rejection(Exception):
    def __init__(self, status_code, detail, **kwargs):
        self.status_code = status_code
        self.detail = detail


class CanonicalAuthTransportBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.ns = identity_namespace()
        self.ns.update(
            DashboardPrincipalLoginResponse=Payload, FieldPrincipalLoginResponse=Payload,
            PositiveId=int, AsyncSession=object, PrincipalLoginRejected=type("PrincipalLoginRejected", (Exception,), {}),
        )
        # Use the exact context-construction definitions from canonical orchestration.
        parsed = ast.parse((BACKEND / "api/authentication/login_orchestration.py").read_text(encoding="utf-8"))
        selected = [node for node in parsed.body if isinstance(node, ast.FunctionDef)
                    and node.name in {"_dashboard_context", "_field_context"}]
        selected.insert(0, ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0))
        ast.fix_missing_locations(selected[0])
        exec(compile(ast.Module(body=selected, type_ignores=[]), "login_contexts", "exec", dont_inherit=True), self.ns)
        self.ns.update(
            get_current_backoffice_legacy_driver=AsyncMock(return_value=DriverProvenance()),
            get_current_field_legacy_driver=AsyncMock(return_value=DriverProvenance()),
        )
        production_definitions("api/authentication/login_transport.py", self.ns)

    def dashboard_identity(self, owner=False):
        return self.ns["DashboardAuthenticationResult"](
            principal_id=101, company_id=7, backoffice_user_id=202, username="canonical",
            full_name="Canonical display", auth_revision=3, is_company_owner=owner,
        )

    def field_identity(self):
        return self.ns["FieldAuthenticationResult"](
            principal_id=101, company_id=7, representative_id=404, username="field",
            full_name="Field display", auth_revision=3,
        )

    @immediate
    async def test_public_dashboard_fields_have_exact_locator_and_canonical_owner(self):
        for owner in (False, True):
            identity = self.dashboard_identity(owner)
            adapt = await self.ns["prepare_dashboard_transport"](object(), identity)
            response = adapt(Payload(principal_id=101, backoffice_user_id=202, company_id=7,
                                     channel="DASHBOARD", is_company_owner=owner,
                                     token="synthetic-access", refresh_token="synthetic-refresh",
                                     company_code="WN", dashboard_access=True)).model_dump()
            self.assertEqual((response["principal_id"], response["backoffice_user_id"],
                              response["driver_id"], response["legacy_driver_id"]), (101, 202, 303, 303))
            self.assertEqual(response["company_id"], 7)
            self.assertIs(response["is_admin"], owner)
            self.assertEqual(response["display_name"], response["driver_name"])
            self.assertEqual(response["driver_name"], "Canonical display")
            self.assertEqual(response["principal_type"], "BACKOFFICE")

    @immediate
    async def test_public_field_legacy_id_preserves_offline_identity(self):
        adapt = await self.ns["prepare_field_transport"](object(), self.field_identity())
        response = adapt(Payload(principal_id=101, representative_id=404, company_id=7,
                                 channel="FIELD", token="synthetic-access", refresh_token="synthetic-refresh",
                                 company_code="WN")).model_dump()
        self.assertEqual((response["principal_id"], response["representative_id"], response["driver_id"]),
                         (101, 404, 303))
        self.assertFalse(response["is_admin"])
        self.assertFalse(response["dashboard_access"])
        self.assertEqual(response["driver_name"], "Field display")

    @immediate
    async def test_missing_or_invalid_mapping_fails_without_fabricated_identity(self):
        for helper, prepare, identity in (
            ("get_current_backoffice_legacy_driver", "prepare_dashboard_transport", self.dashboard_identity()),
            ("get_current_field_legacy_driver", "prepare_field_transport", self.field_identity()),
        ):
            for invalid in (None, SimpleNamespace(id=0), SimpleNamespace(id=True)):
                self.ns[helper].return_value = invalid
                with self.subTest(helper=helper, invalid=invalid), self.assertRaises(self.ns["PrincipalLoginRejected"]):
                    await self.ns[prepare](object(), identity)

    @immediate
    async def test_generic_compatibility_dispatches_only_by_trusted_context(self):
        ns = identity_namespace()
        ns.update(Depends=lambda dependency: dependency, get_db=object(),
                  HTTPException=Rejection, status=SimpleNamespace(HTTP_403_FORBIDDEN=403),
                  get_current_principal_context=object(), _authentication_rejected=lambda: Rejection(401, "opaque"),
                  get_current_backoffice_legacy_driver=AsyncMock(return_value=DriverProvenance()),
                  get_current_field_legacy_driver=AsyncMock(return_value=DriverProvenance()))
        # Only retired/compatibility definitions execute; canonical imports are audited below.
        parsed = ast.parse((BACKEND / "api/dependencies.py").read_text(encoding="utf-8"))
        selected = [node for node in parsed.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    or isinstance(node, ast.ImportFrom) and node.module == "__future__"]
        exec(compile(ast.Module(body=selected, type_ignores=[]), "core_dependencies", "exec", dont_inherit=True), ns)
        db = object()
        for context, helper in (
            (ns["DashboardRequestContext"](101, 7, 202, 3, False), "get_current_backoffice_legacy_driver"),
            (ns["FieldRequestContext"](101, 7, 404, 3), "get_current_field_legacy_driver"),
        ):
            result = await ns["get_current_driver"](current=context, db=db)
            self.assertEqual(result.id, 303)
            ns[helper].assert_awaited_once_with(current=context, db=db)
        with self.assertRaises(Rejection) as denied:
            await ns["get_current_driver"](current=object(), db=db)
        self.assertEqual(denied.exception.status_code, 401)
        for helper, args in (("get_current_admin", {}), ("get_current_driver_owned", {"driver_id": 303})):
            with self.assertRaises(Rejection) as rejected:
                await ns[helper](**args)
            self.assertEqual(rejected.exception.status_code, 403)
            self.assertEqual(rejected.exception.detail, "Authorization denied.")

    def test_legacy_decoder_rejects_coincident_ids_and_partial_canonical_markers(self):
        spec = importlib.util.spec_from_file_location("retired_identity_decoder", BACKEND / "token_identity.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        legacy = dict(type="access", sub="101", company_id=7, role="Admin", is_admin=True)
        self.assertEqual(module.access_token_identity(legacy), (101, 7))
        for marker, value in (("channel", "DASHBOARD"), ("principal_type", "BACKOFFICE"), ("auth_revision", 3)):
            for invalid in (value, None, ""):
                with self.subTest(marker=marker, value=invalid), self.assertRaises(ValueError):
                    module.access_token_identity({**legacy, marker: invalid})
        with self.assertRaises(ValueError):
            module.access_token_identity({**legacy, "type": "refresh"})
        for invalid in (True, 0, -1, "01", "1.5", 2147483648):
            with self.subTest(sub=invalid), self.assertRaises(ValueError):
                module.access_token_identity({**legacy, "sub": invalid})

    def test_no_driver_credentials_flags_jwt_or_transaction_in_compatibility_adapter(self):
        for path in ("api/dependencies.py", "api/authentication/login_transport.py"):
            parsed = ast.parse((BACKEND / path).read_text(encoding="utf-8"))
            attrs = {node.attr for node in ast.walk(parsed) if isinstance(node, ast.Attribute)}
            self.assertTrue({"is_admin", "company_id", "password_hash", "decode", "begin", "commit", "rollback"}.isdisjoint(attrs),
                            (path, attrs))
        parsed = ast.parse((BACKEND / "api/auth.py").read_text(encoding="utf-8"))
        self.assertFalse(any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) for node in parsed.body))



class LoginPrecommitBoundaryTests(unittest.TestCase):
    def namespace(self, identity):
        ns = identity_namespace()
        ns["DashboardAuthenticationResult" if identity.channel.value == "DASHBOARD" else "FieldAuthenticationResult"] = type(identity)
        ns.update(TypedDict=__import__("typing").TypedDict)
        production_definitions("api/authentication/login.py", ns)
        ns.update(
            DashboardPrincipalLoginResponse=Payload, FieldPrincipalLoginResponse=Payload,
            LoginAttemptRateLimited=type("LoginAttemptRateLimited", (Exception,), {}),
            DashboardAdmissionRejected=type("DashboardAdmissionRejected", (Exception,), {}),
            RefreshSessionRejected=type("RefreshSessionRejected", (Exception,), {}),
            RefreshSessionTransactionRequired=type("RefreshSessionTransactionRequired", (Exception,), {}),
        )
        production_definitions("api/authentication/login_orchestration.py", ns)
        ns.update(
            enforce_company_login_attempt_limit=AsyncMock(),
            prepare_login_company=AsyncMock(return_value=ns["LoginCompanyContext"](7, "WN")),
            authenticate_identity=AsyncMock(return_value=identity),
            require_dashboard_admission=AsyncMock(return_value=identity),
            create_refresh_session=AsyncMock(return_value=SimpleNamespace(refresh_token="synthetic-refresh")),
            issue_access_token=Mock(return_value="synthetic-access"),
            record_login_attempt=Mock(),
        )
        return ns

    def identities(self):
        ns = identity_namespace()
        return (
            ns["DashboardAuthenticationResult"](101, 7, 202, "backoffice", "Name", 3, False),
            ns["FieldAuthenticationResult"](101, 7, 404, "field", "Name", 3),
        )

    @immediate
    async def test_mapping_failure_records_failed_attempt_and_never_issues_session(self):
        for name, identity in zip(("login_dashboard_principal", "login_field_principal"), self.identities()):
            ns = self.namespace(identity)
            db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
            preparation = AsyncMock(side_effect=ns["PrincipalLoginRejected"])
            with self.subTest(channel=name), self.assertRaises(ns["PrincipalLoginRejected"]):
                await ns[name](db, company_code="WN", username="user", password="secret",
                               ip_address="127.0.0.1", secret="synthetic", prepare_response=preparation)
            preparation.assert_awaited_once_with(db, identity)
            ns["create_refresh_session"].assert_not_awaited()
            ns["issue_access_token"].assert_not_called()
            db.commit.assert_awaited_once()
            db.rollback.assert_not_awaited()
            self.assertFalse(ns["record_login_attempt"].call_args.kwargs["successful"])

    @immediate
    async def test_response_preparation_precedes_atomic_session_attempt_commit(self):
        for name, identity in zip(("login_dashboard_principal", "login_field_principal"), self.identities()):
            ns = self.namespace(identity)
            events = []
            async def preparation(db, received):
                self.assertIs(received, identity)
                events.append("preflight")
                def adapt(response):
                    events.append("adapt")
                    return Payload(**response.model_dump(), driver_id=303)
                return adapt
            async def refresh(db, context, **kwargs):
                self.assertEqual(context.principal_id, 101)
                events.append("refresh")
                return SimpleNamespace(refresh_token="synthetic-refresh")
            def access(**kwargs):
                self.assertEqual(kwargs["principal_id"], 101)
                events.append("access")
                return "synthetic-access"
            async def commit():
                events.append("commit")
            ns.update(create_refresh_session=AsyncMock(side_effect=refresh),
                      issue_access_token=Mock(side_effect=access),
                      record_login_attempt=Mock(side_effect=lambda *args, **kwargs: events.append("attempt")))
            db = SimpleNamespace(commit=commit, rollback=AsyncMock())
            result = await ns[name](db, company_code="WN", username="user", password="secret",
                                    ip_address="127.0.0.1", secret="synthetic", prepare_response=preparation)
            self.assertEqual(result.model_dump()["driver_id"], 303)
            self.assertEqual(events, ["preflight", "refresh", "access", "adapt", "attempt", "commit"])
            db.rollback.assert_not_awaited()

    @immediate
    async def test_final_transport_failure_rolls_back_uncommitted_session(self):
        ns = self.namespace(self.identities()[0])
        async def preparation(*args):
            def invalid_response(response):
                raise ValueError("synthetic schema failure")
            return invalid_response
        db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
        with self.assertRaises(ValueError):
            await ns["login_dashboard_principal"](db, company_code="WN", username="user", password="secret",
                                                 ip_address="127.0.0.1", secret="synthetic",
                                                 prepare_response=preparation)
        ns["create_refresh_session"].assert_awaited_once()
        db.commit.assert_not_awaited()
        db.rollback.assert_awaited_once()

    @immediate
    async def test_unadapted_internal_response_remains_strict_canonical_shape(self):
        for name, identity, expected in (
            ("login_dashboard_principal", self.identities()[0],
             {"token", "refresh_token", "principal_id", "backoffice_user_id", "channel",
              "is_company_owner", "company_id", "company_code", "dashboard_access"}),
            ("login_field_principal", self.identities()[1],
             {"token", "refresh_token", "principal_id", "representative_id", "channel", "company_id", "company_code"}),
        ):
            ns = self.namespace(identity)
            db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
            result = await ns[name](db, company_code="WN", username="user", password="secret",
                                    ip_address="127.0.0.1", secret="synthetic")
            self.assertEqual(set(result.model_dump()), expected)
            self.assertTrue(ns["record_login_attempt"].call_args.kwargs["successful"])


if __name__ == "__main__":
    unittest.main()
