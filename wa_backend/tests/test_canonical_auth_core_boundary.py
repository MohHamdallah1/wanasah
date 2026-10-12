"""Focused executable proofs over exact canonical production definitions.

External I/O collaborators are mocked; SQL compilation, FastAPI and cryptographic
integration are covered by the existing principal runtime gates. These checks run
without installing backend packages and must not be reported as HTTP/DB tests.
"""
from __future__ import annotations

import ast
from functools import wraps
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal, Mapping, TypeAlias
import unittest
from unittest.mock import AsyncMock

BACKEND = Path(__file__).resolve().parents[1]


def production_definitions(path, namespace):
    parsed = ast.parse((BACKEND / path).read_text(encoding="utf-8"))
    selected = [
        node for node in parsed.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef,
                             ast.Assign, ast.AnnAssign))
        or isinstance(node, ast.ImportFrom) and node.module == "__future__"
    ]
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(BACKEND / path),
                 "exec", dont_inherit=True), namespace)
    return namespace


def identity_namespace():
    namespace = dict(globals())
    production_definitions("domains/identity/types.py", namespace)
    production_definitions("domains/identity/channels.py", namespace)
    production_definitions("domains/identity/contracts.py", namespace)
    claims_namespace = production_definitions("domains/auth_sessions/claims.py", dict(globals()))
    namespace.update({name: claims_namespace[name] for name in ("CompanyTokenClaims", "TokenContractError")})
    namespace["IdentityRecordNotFound"] = type("IdentityRecordNotFound", (Exception,), {})
    production_definitions("domains/auth_sessions/context.py", namespace)
    return namespace


class NoLegacyFlags(SimpleNamespace):
    @property
    def is_admin(self):
        raise AssertionError("Driver flags must not be authentication authority")


def immediate(method):
    """Run mocked, non-suspending coroutines without opening an OS event loop."""
    @wraps(method)
    def run(self):
        operation = method(self)
        try:
            operation.send(None)
        except StopIteration:
            return
        finally:
            operation.close()
        self.fail("Boundary collaborator unexpectedly performed asynchronous I/O")
    return run


class CanonicalAuthCoreBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.ns = identity_namespace()
        self.claims = self.ns["CompanyTokenClaims"](
            token_type="access", principal_id=101, company_id=7, channel="DASHBOARD",
            principal_type="BACKOFFICE", auth_revision=3, jti="synthetic", exp=4102444800,
        )
        self.principal = NoLegacyFlags(
            id=101, company_id=7, is_active=True, principal_type="BACKOFFICE", auth_revision=3,
        )
        self.backoffice = NoLegacyFlags(
            id=202, company_id=7, principal_id=101, principal_type="BACKOFFICE",
        )
        self.field = NoLegacyFlags(
            id=404, company_id=7, principal_id=101, principal_type="FIELD_REPRESENTATIVE",
        )
        self.ns.update(
            require_active_company=AsyncMock(return_value=SimpleNamespace(id=7, is_active=True)),
            load_principal_by_id=AsyncMock(return_value=self.principal),
            require_backoffice_profile=AsyncMock(return_value=self.backoffice),
            require_field_representative_profile=AsyncMock(return_value=self.field),
            load_company_owner=AsyncMock(return_value=SimpleNamespace(company_id=7, backoffice_user_id=202)),
        )

    async def resolve(self):
        return await self.ns["resolve_access_context"](object(), self.claims)

    @immediate
    async def test_owner_is_persisted_profile_relation_with_independent_ids(self):
        result = await self.resolve()
        self.assertEqual((result.principal_id, result.backoffice_user_id, result.company_id), (101, 202, 7))
        self.assertTrue(result.is_company_owner)
        self.ns["load_company_owner"].assert_awaited_once_with(unittest.mock.ANY, company_id=7)
        self.ns["require_field_representative_profile"].assert_not_awaited()
        self.assertFalse(hasattr(result, "driver_id"))

    @immediate
    async def test_owner_membership_never_comes_from_principal_or_driver_number(self):
        self.ns["load_company_owner"].return_value = SimpleNamespace(company_id=7, backoffice_user_id=101)
        result = await self.resolve()
        self.assertFalse(result.is_company_owner)
        self.ns["load_company_owner"].return_value = None
        self.assertFalse((await self.resolve()).is_company_owner)

    @immediate
    async def test_cross_company_principal_profile_and_owner_fail_closed(self):
        for row in (self.principal, self.backoffice, self.ns["load_company_owner"].return_value):
            original = row.company_id
            row.company_id = 8
            with self.subTest(row=row), self.assertRaises(self.ns["RequestContextRejected"]):
                await self.resolve()
            row.company_id = original

    @immediate
    async def test_inactive_principal_company_and_missing_profile_fail_closed(self):
        self.principal.is_active = False
        with self.assertRaises(self.ns["RequestContextRejected"]):
            await self.resolve()
        self.principal.is_active = True
        self.ns["require_active_company"].side_effect = self.ns["IdentityRecordNotFound"]
        with self.assertRaises(self.ns["RequestContextRejected"]):
            await self.resolve()
        self.ns["require_active_company"].side_effect = None
        self.ns["require_backoffice_profile"].side_effect = self.ns["IdentityRecordNotFound"]
        with self.assertRaises(self.ns["RequestContextRejected"]):
            await self.resolve()

    @immediate
    async def test_persisted_revision_and_type_are_authoritative(self):
        self.principal.auth_revision = 4
        with self.assertRaises(self.ns["RequestContextRejected"]):
            await self.resolve()
        self.principal.auth_revision = 3
        self.principal.principal_type = "FIELD_REPRESENTATIVE"
        with self.assertRaises(self.ns["RequestContextRejected"]):
            await self.resolve()

    @immediate
    async def test_field_channel_returns_only_field_profile_and_no_owner_read(self):
        self.claims = self.ns["CompanyTokenClaims"](
            token_type="access", principal_id=101, company_id=7, channel="FIELD",
            principal_type="FIELD_REPRESENTATIVE", auth_revision=3, jti="synthetic", exp=4102444800,
        )
        self.principal.principal_type = "FIELD_REPRESENTATIVE"
        result = await self.resolve()
        self.assertEqual((result.principal_id, result.representative_id), (101, 404))
        self.ns["require_backoffice_profile"].assert_not_awaited()
        self.ns["load_company_owner"].assert_not_awaited()
        self.assertFalse(hasattr(result, "backoffice_user_id"))

    @immediate
    async def test_wrong_channel_pair_and_refresh_rejected_before_persistence(self):
        for kind, channel, principal_type in (
            ("access", "FIELD", "BACKOFFICE"),
            ("access", "DASHBOARD", "FIELD_REPRESENTATIVE"),
            ("access", "PLATFORM", "BACKOFFICE"),
            ("refresh", "DASHBOARD", "BACKOFFICE"),
        ):
            self.claims = SimpleNamespace(token_type=kind, channel=channel, principal_type=principal_type)
            with self.subTest(kind=kind, channel=channel, principal_type=principal_type), \
                 self.assertRaises(self.ns["RequestContextRejected"]):
                await self.resolve()
        self.ns["require_active_company"].assert_not_awaited()

    def test_legacy_and_platform_tokens_cannot_be_reclassified_from_roles(self):
        parser = self.ns["CompanyTokenClaims"].from_payload
        legacy = dict(type="access", sub="303", company_id=7, role="Admin", is_admin=True,
                      exp=4102444800, jti="legacy")
        with self.assertRaises(self.ns["TokenContractError"]):
            parser(legacy, expected_type="access")
        payload = self.claims.to_payload()
        payload.update(role="Admin", is_admin=True, capabilities=["all"])
        parsed = parser(payload, expected_type="access")
        self.assertEqual(parsed, self.claims)
        self.assertTrue({"role", "is_admin", "capabilities"}.isdisjoint(vars(parsed)))
        payload.update(channel="PLATFORM", principal_type="BACKOFFICE")
        with self.assertRaises(self.ns["TokenContractError"]):
            parser(payload, expected_type="access")

    @immediate
    async def test_refresh_rotation_revalidates_before_writing_and_links_atomically(self):
        ns = dict(self.ns)
        production_definitions("domains/auth_sessions/refresh_sessions.py", ns)
        refresh_claims = self.ns["CompanyTokenClaims"](
            token_type="refresh", principal_id=101, company_id=7, channel="FIELD",
            principal_type="FIELD_REPRESENTATIVE", auth_revision=3, jti="synthetic", exp=4102444800,
        )
        predecessor = SimpleNamespace(is_revoked=False, replaced_by_id=None)
        successor = SimpleNamespace(id=606, token="synthetic-successor")
        events = []
        async def tenant(*args):
            events.append("tenant")
        async def exact(*args):
            events.append("locked-row")
            return predecessor
        async def persisted(*args):
            events.append("persisted")
        async def insert(*args):
            events.append("insert")
            self.assertIs(args[1], refresh_claims)
            return successor
        async def flush():
            events.append("flush")
            self.assertTrue(predecessor.is_revoked)
            self.assertEqual(predecessor.replaced_by_id, 606)
        ns.update(_decode=lambda *args: refresh_claims, _tenant=tenant, _exact=exact,
                  _persisted_identity=persisted, _match=lambda *args: None, _insert=insert)
        db = SimpleNamespace(in_transaction=lambda: True, flush=flush)
        result = await ns["rotate_refresh_session"](db, "synthetic-predecessor", secret="synthetic")
        self.assertEqual(events, ["tenant", "locked-row", "persisted", "insert", "flush"])
        self.assertEqual((result.principal_id, result.company_id, result.channel.value,
                          result.principal_type.value, result.auth_revision, result.refresh_token),
                         (101, 7, "FIELD", "FIELD_REPRESENTATIVE", 3, "synthetic-successor"))
        # An invalid persisted identity cannot create a successor or mutate the predecessor.
        predecessor.is_revoked = False
        predecessor.replaced_by_id = None
        ns["_persisted_identity"] = AsyncMock(side_effect=ns["RefreshSessionRejected"])
        ns["_insert"] = AsyncMock()
        with self.assertRaises(ns["RefreshSessionRejected"]):
            await ns["rotate_refresh_session"](db, "synthetic-predecessor", secret="synthetic")
        ns["_insert"].assert_not_awaited()
        self.assertFalse(predecessor.is_revoked)
        self.assertIsNone(predecessor.replaced_by_id)

    def test_exact_refresh_row_rejects_any_identity_switch_or_expiry(self):
        ns = dict(self.ns)
        production_definitions("domains/auth_sessions/refresh_sessions.py", ns)
        now = datetime.now(timezone.utc)
        row = SimpleNamespace(company_id=7, principal_id=101, channel="DASHBOARD", auth_revision=3,
                              expires_at=now + timedelta(minutes=5))
        ns["_match"](row, self.claims, now)
        for attr, invalid in (("company_id", 8), ("principal_id", 202), ("channel", "FIELD"),
                              ("auth_revision", 4), ("expires_at", now - timedelta(seconds=1))):
            old = getattr(row, attr)
            setattr(row, attr, invalid)
            with self.subTest(attr=attr), self.assertRaises(ns["RefreshSessionRejected"]):
                ns["_match"](row, self.claims, now)
            setattr(row, attr, old)


if __name__ == "__main__":
    unittest.main()
