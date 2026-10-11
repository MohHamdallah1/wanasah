from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient

from api.authentication.legacy_backoffice_transport import (
    get_legacy_transport_backoffice_capability_access,
    get_legacy_transport_backoffice_context,
    require_legacy_transport_backoffice_capability,
)
from api.dependencies import get_current_driver
from database import get_db
from domains.authorization.backoffice_access import (
    BackofficeCapabilityAccess,
    BackofficeCapabilityAccessRejected,
)
from domains.authorization.backoffice_subject import BackofficeAuthorizationSubject


ROOT = Path(__file__).resolve().parents[1]
MODULE = "api.authentication.legacy_backoffice_transport"


class _NoAuthorityDriver:
    def __init__(self, *, company_id: int = 77, driver_id: int = 903, is_admin=False):
        self.company_id = company_id
        self.id = driver_id
        self._is_admin = is_admin

    @property
    def is_admin(self):
        raise AssertionError("legacy Driver.is_admin must never be read")


class _FakeDB:
    def __init__(self, *rows):
        self.scalar = AsyncMock(side_effect=rows)


def _bridge(*, company_id=77, driver_id=903, principal_id=101, user_id=202):
    return SimpleNamespace(
        company_id=company_id,
        legacy_driver_id=driver_id,
        backoffice_principal_id=principal_id,
        backoffice_user_id=user_id,
        classification="FIELD_REPRESENTATIVE",
    )


def _principal(*, company_id=77, principal_id=101, active=True, principal_type="BACKOFFICE"):
    return SimpleNamespace(
        company_id=company_id,
        id=principal_id,
        principal_type=principal_type,
        is_active=active,
        auth_revision=4,
    )


def _profile(*, company_id=77, user_id=202, principal_id=101, principal_type="BACKOFFICE"):
    return SimpleNamespace(
        company_id=company_id,
        id=user_id,
        principal_id=principal_id,
        principal_type=principal_type,
    )


def _owner(*, company_id=77, user_id=202):
    return SimpleNamespace(company_id=company_id, backoffice_user_id=user_id)


class LegacyBackofficeTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_live_legacy_transport_resolves_independent_canonical_ids(self):
        driver = _NoAuthorityDriver(driver_id=903)
        db = _FakeDB(_bridge(), _principal(), _profile(), _owner())

        context = await get_legacy_transport_backoffice_context(driver, db)

        self.assertEqual(context.company_id, 77)
        self.assertEqual(context.principal_id, 101)
        self.assertEqual(context.backoffice_user_id, 202)
        self.assertEqual(context.auth_revision, 4)
        self.assertTrue(context.is_company_owner)
        self.assertEqual(driver.id, 903)
        self.assertEqual(len({driver.id, context.principal_id, context.backoffice_user_id}), 3)

    async def test_driver_is_admin_true_and_false_have_zero_effect(self):
        contexts = []
        for legacy_value in (False, True):
            driver = _NoAuthorityDriver(is_admin=legacy_value)
            db = _FakeDB(_bridge(), _principal(), _profile(), None)
            contexts.append(await get_legacy_transport_backoffice_context(driver, db))

        self.assertEqual(contexts[0], contexts[1])
        self.assertFalse(contexts[0].is_company_owner)

    async def test_company_owner_comes_only_from_persisted_company_owner(self):
        driver = _NoAuthorityDriver(is_admin=True)
        without_owner = await get_legacy_transport_backoffice_context(
            driver,
            _FakeDB(_bridge(), _principal(), _profile(), None),
        )
        with_other_owner = await get_legacy_transport_backoffice_context(
            driver,
            _FakeDB(_bridge(), _principal(), _profile(), _owner(user_id=999)),
        )
        with_exact_owner = await get_legacy_transport_backoffice_context(
            driver,
            _FakeDB(_bridge(), _principal(), _profile(), _owner()),
        )

        self.assertFalse(without_owner.is_company_owner)
        self.assertFalse(with_other_owner.is_company_owner)
        self.assertTrue(with_exact_owner.is_company_owner)

    async def test_missing_or_malformed_bridge_fails_closed_401(self):
        cases = [
            _FakeDB(None),
            _FakeDB(_bridge(company_id=88)),
            _FakeDB(_bridge(principal_id=None)),
            _FakeDB(_bridge(user_id=None)),
        ]
        for db in cases:
            with self.subTest(db=db):
                with self.assertRaises(HTTPException) as caught:
                    await get_legacy_transport_backoffice_context(
                        _NoAuthorityDriver(), db
                    )
                self.assertEqual(caught.exception.status_code, 401)

    async def test_inactive_or_wrong_type_principal_fails_closed_401(self):
        for principal in (
            _principal(active=False),
            _principal(principal_type="FIELD_REPRESENTATIVE"),
            _principal(company_id=88),
        ):
            with self.subTest(principal=principal):
                db = _FakeDB(_bridge(), principal)
                with self.assertRaises(HTTPException) as caught:
                    await get_legacy_transport_backoffice_context(
                        _NoAuthorityDriver(), db
                    )
                self.assertEqual(caught.exception.status_code, 401)

    async def test_profile_must_exactly_match_company_principal_and_backoffice_type(self):
        for profile in (
            _profile(company_id=88),
            _profile(principal_id=999),
            _profile(principal_type="FIELD_REPRESENTATIVE"),
        ):
            with self.subTest(profile=profile):
                db = _FakeDB(_bridge(), _principal(), profile)
                with self.assertRaises(HTTPException) as caught:
                    await get_legacy_transport_backoffice_context(
                        _NoAuthorityDriver(), db
                    )
                self.assertEqual(caught.exception.status_code, 401)

    async def test_capability_access_reuses_canonical_subject_resolver(self):
        db = object()
        current = object()
        subject = BackofficeAuthorizationSubject(
            principal_id=101,
            backoffice_user_id=202,
            company_id=77,
            is_company_owner=False,
            legacy_grant_driver_id=903,
        )
        resolver = AsyncMock(return_value=subject)

        with patch(f"{MODULE}.resolve_backoffice_authorization_subject", resolver):
            access = await get_legacy_transport_backoffice_capability_access(
                current=current,
                db=db,
            )

        resolver.assert_awaited_once_with(db, current)
        self.assertIsInstance(access, BackofficeCapabilityAccess)
        self.assertIs(access.db, db)
        self.assertIs(access.subject, subject)

    async def test_factory_validates_permission_and_maps_capability_rejection_to_403(self):
        with self.assertRaises(ValueError):
            require_legacy_transport_backoffice_capability("admin.anything")

        dependency = require_legacy_transport_backoffice_capability(
            "inventory.minimum_stock.manage"
        )
        access = AsyncMock(spec=BackofficeCapabilityAccess)
        access.require.side_effect = BackofficeCapabilityAccessRejected

        with self.assertRaises(HTTPException) as caught:
            await dependency(access=access)

        self.assertEqual(caught.exception.status_code, 403)
        self.assertEqual(caught.exception.detail, "Authorization denied.")
        access.require.assert_awaited_once_with("inventory.minimum_stock.manage")

    def test_fastapi_cache_executes_legacy_driver_transport_once(self):
        app = FastAPI()
        capability = require_legacy_transport_backoffice_capability(
            "inventory.minimum_stock.manage"
        )
        calls = {"driver": 0}
        driver = _NoAuthorityDriver()
        db = _FakeDB(_bridge(), _principal(), _profile(), _owner())

        async def counted_driver():
            calls["driver"] += 1
            return driver

        async def fake_db():
            yield db

        @app.get("/probe")
        async def probe(
            access: BackofficeCapabilityAccess = Depends(capability),
            legacy_actor=Depends(get_current_driver),
        ):
            return {
                "company_id": access.company_id,
                "actor_id": legacy_actor.id,
            }

        app.dependency_overrides[get_current_driver] = counted_driver
        app.dependency_overrides[get_db] = fake_db

        response = TestClient(app).get("/probe")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"company_id": 77, "actor_id": 903})
        self.assertEqual(calls["driver"], 1)

        context_driver = inspect.signature(
            get_legacy_transport_backoffice_context
        ).parameters["current_driver"].default
        self.assertIs(context_driver.dependency, get_current_driver)
        self.assertTrue(context_driver.use_cache)

    def test_source_has_no_legacy_authority_or_duplicate_token_decode(self):
        source = (ROOT / "api" / "authentication" / "legacy_backoffice_transport.py").read_text(
            encoding="utf-8"
        )

        self.assertNotIn(".is_admin", source)
        self.assertNotIn("classification", source)
        self.assertNotIn("jwt.decode", source)
        self.assertNotIn("token role", source.lower())
        self.assertNotIn("role ==", source)
        self.assertEqual(source.count("current_driver.company_id"), 1)
        self.assertEqual(source.count("current_driver.id"), 1)
        self.assertIn("resolve_backoffice_authorization_subject", source)
        self.assertIn(
            "IdentityLegacyDriverMap.company_id == transport_company_id",
            source,
        )
        self.assertIn("IdentityLegacyDriverMap.legacy_driver_id == legacy_driver_id", source)
        self.assertIn("company_id = bridge.company_id", source)
        self.assertIn("company_id=principal.company_id", source)
        self.assertIn("CompanyOwner.company_id == company_id", source)


if __name__ == "__main__":
    unittest.main()
