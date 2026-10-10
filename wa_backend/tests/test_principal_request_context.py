from __future__ import annotations

from dataclasses import fields
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from domains.auth_sessions.claims import CompanyTokenClaims
from domains.auth_sessions import context as request_context
from domains.auth_sessions.context import (
    DashboardRequestContext,
    FieldRequestContext,
    RequestContextRejected,
    resolve_access_context,
)
from domains.identity.channels import IdentityChannel
from domains.identity.repository import IdentityRecordNotFound
from domains.identity.types import PrincipalType


class PrincipalRequestContextTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.db = object()

    def _claims(
        self,
        *,
        company_id: int = 3,
        principal_id: int = 7,
        channel: str = "DASHBOARD",
        principal_type: str = "BACKOFFICE",
        auth_revision: int = 4,
        token_type: str = "access",
    ) -> CompanyTokenClaims:
        return CompanyTokenClaims(
            token_type=token_type,  # type: ignore[arg-type]
            principal_id=principal_id,
            company_id=company_id,
            channel=channel,  # type: ignore[arg-type]
            principal_type=principal_type,  # type: ignore[arg-type]
            auth_revision=auth_revision,
            jti="test-jti",
            exp=4_102_444_800,
        )

    def _reads(
        self,
        *,
        company_id: int = 3,
        principal_id: int = 7,
        principal_type: str = "BACKOFFICE",
        auth_revision: int = 4,
        active: bool = True,
        backoffice_id: int = 101,
        representative_id: int = 202,
        owner_backoffice_id: int | None = None,
    ) -> dict[str, AsyncMock]:
        owner = (
            None
            if owner_backoffice_id is None
            else SimpleNamespace(
                company_id=company_id,
                backoffice_user_id=owner_backoffice_id,
            )
        )
        return {
            "require_active_company": AsyncMock(
                return_value=SimpleNamespace(id=company_id, is_active=True)
            ),
            "load_principal_by_id": AsyncMock(
                return_value=SimpleNamespace(
                    id=principal_id,
                    company_id=company_id,
                    principal_type=principal_type,
                    auth_revision=auth_revision,
                    is_active=active,
                    password_hash="must-not-escape",
                )
            ),
            "require_backoffice_profile": AsyncMock(
                return_value=SimpleNamespace(
                    id=backoffice_id,
                    company_id=company_id,
                    principal_id=principal_id,
                    principal_type="BACKOFFICE",
                )
            ),
            "require_field_representative_profile": AsyncMock(
                return_value=SimpleNamespace(
                    id=representative_id,
                    company_id=company_id,
                    principal_id=principal_id,
                    principal_type="FIELD_REPRESENTATIVE",
                )
            ),
            "load_company_owner": AsyncMock(return_value=owner),
        }

    async def _resolve(
        self,
        claims: CompanyTokenClaims,
        reads: dict[str, AsyncMock],
    ):
        with patch.multiple(request_context, **reads):
            return await resolve_access_context(self.db, claims)

    async def test_valid_dashboard_context(self) -> None:
        claims = self._claims()
        reads = self._reads(owner_backoffice_id=101)

        result = await self._resolve(claims, reads)

        self.assertEqual(
            result,
            DashboardRequestContext(
                principal_id=7,
                company_id=3,
                backoffice_user_id=101,
                auth_revision=4,
                is_company_owner=True,
            ),
        )
        self.assertIs(result.channel, IdentityChannel.DASHBOARD)
        self.assertIs(result.principal_type, PrincipalType.BACKOFFICE)

    async def test_valid_field_context(self) -> None:
        claims = self._claims(
            channel="FIELD",
            principal_type="FIELD_REPRESENTATIVE",
        )
        reads = self._reads(principal_type="FIELD_REPRESENTATIVE")

        result = await self._resolve(claims, reads)

        self.assertEqual(
            result,
            FieldRequestContext(
                principal_id=7,
                company_id=3,
                representative_id=202,
                auth_revision=4,
            ),
        )
        self.assertIs(result.channel, IdentityChannel.FIELD)
        self.assertIs(result.principal_type, PrincipalType.FIELD_REPRESENTATIVE)

    async def test_inactive_company_fails_closed(self) -> None:
        claims = self._claims()
        reads = self._reads()
        reads["require_active_company"].side_effect = IdentityRecordNotFound

        with self.assertRaises(RequestContextRejected) as failure:
            await self._resolve(claims, reads)
        self.assertEqual(str(failure.exception), "")

    async def test_missing_and_inactive_principal_fail_closed(self) -> None:
        claims = self._claims()

        for principal in (None, SimpleNamespace(
            id=7,
            company_id=3,
            principal_type="BACKOFFICE",
            auth_revision=4,
            is_active=False,
        )):
            with self.subTest(principal=principal):
                reads = self._reads()
                reads["load_principal_by_id"].return_value = principal
                with self.assertRaises(RequestContextRejected):
                    await self._resolve(claims, reads)

    async def test_wrong_tenant_fails_closed(self) -> None:
        claims = self._claims(company_id=9)
        reads = self._reads(company_id=9)
        reads["load_principal_by_id"].return_value = SimpleNamespace(
            id=7,
            company_id=3,
            principal_type="BACKOFFICE",
            auth_revision=4,
            is_active=True,
        )

        with self.assertRaises(RequestContextRejected):
            await self._resolve(claims, reads)
        reads["load_principal_by_id"].assert_awaited_once_with(
            self.db,
            company_id=9,
            principal_id=7,
        )

    async def test_revision_mismatch_fails_closed(self) -> None:
        claims = self._claims(auth_revision=5)
        reads = self._reads(auth_revision=4)

        with self.assertRaises(RequestContextRejected):
            await self._resolve(claims, reads)

    async def test_claim_and_persisted_type_mismatch_fails_closed(self) -> None:
        claims = self._claims()
        reads = self._reads(principal_type="FIELD_REPRESENTATIVE")

        with self.assertRaises(RequestContextRejected):
            await self._resolve(claims, reads)

    async def test_wrong_channel_or_missing_required_profile_fails_closed(self) -> None:
        invalid_pair = self._claims(
            channel="FIELD",
            principal_type="BACKOFFICE",
        )
        reads = self._reads()
        with self.assertRaises(RequestContextRejected):
            await self._resolve(invalid_pair, reads)
        reads["require_active_company"].assert_not_awaited()

        field_claims = self._claims(
            channel="FIELD",
            principal_type="FIELD_REPRESENTATIVE",
        )
        reads = self._reads(principal_type="FIELD_REPRESENTATIVE")
        reads["require_field_representative_profile"].side_effect = (
            IdentityRecordNotFound
        )
        with self.assertRaises(RequestContextRejected):
            await self._resolve(field_claims, reads)

    async def test_company_owner_true_and_false(self) -> None:
        claims = self._claims()

        owner_reads = self._reads(owner_backoffice_id=101)
        owner_result = await self._resolve(claims, owner_reads)
        self.assertTrue(owner_result.is_company_owner)

        non_owner_reads = self._reads(owner_backoffice_id=999)
        non_owner_result = await self._resolve(claims, non_owner_reads)
        self.assertFalse(non_owner_result.is_company_owner)

    async def test_result_contains_no_credential_material(self) -> None:
        dashboard = await self._resolve(
            self._claims(),
            self._reads(owner_backoffice_id=101),
        )
        field = await self._resolve(
            self._claims(
                channel="FIELD",
                principal_type="FIELD_REPRESENTATIVE",
            ),
            self._reads(principal_type="FIELD_REPRESENTATIVE"),
        )

        forbidden = {"password_hash", "password", "username", "full_name"}
        for result in (dashboard, field):
            with self.subTest(result=type(result).__name__):
                self.assertTrue(forbidden.isdisjoint({item.name for item in fields(result)}))
                self.assertTrue(forbidden.isdisjoint(vars(result)))

    async def test_refresh_claims_are_not_accepted_as_access_context(self) -> None:
        claims = self._claims(token_type="refresh")
        reads = self._reads()

        with self.assertRaises(RequestContextRejected):
            await self._resolve(claims, reads)
        reads["require_active_company"].assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
