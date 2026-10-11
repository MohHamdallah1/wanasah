from __future__ import annotations

import inspect
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient

from api.authentication.backoffice_authorization import (
    get_current_backoffice_capability_access,
    require_backoffice_capabilities,
    require_backoffice_capability,
)
from api.authentication.dependencies import get_current_backoffice_context
from database import get_db
from domains.auth_sessions.context import DashboardRequestContext
from domains.authorization.backoffice_access import (
    BackofficeCapabilityAccess,
    BackofficeCapabilityAccessRejected,
)
from domains.authorization.backoffice_subject import (
    BackofficeAuthorizationSubject,
    BackofficeAuthorizationSubjectRejected,
)
from domains.authorization.capabilities import PERMISSIONS


ROOT = Path(__file__).resolve().parents[1]
MODULE = "api.authentication.backoffice_authorization"


def _subject(*, owner: bool = False) -> BackofficeAuthorizationSubject:
    return BackofficeAuthorizationSubject(
        principal_id=101,
        backoffice_user_id=202,
        company_id=77,
        is_company_owner=owner,
        legacy_grant_driver_id=None if owner else 903,
    )


class _FakeAccess:
    def __init__(self, *, reject_one: bool = False, reject_all: bool = False):
        self.reject_one = reject_one
        self.reject_all = reject_all
        self.require_calls: list[str] = []
        self.require_all_calls: list[tuple[str, ...]] = []

    async def require(self, code: str) -> None:
        self.require_calls.append(code)
        if self.reject_one:
            raise BackofficeCapabilityAccessRejected

    async def require_all(self, codes: tuple[str, ...]) -> None:
        self.require_all_calls.append(tuple(codes))
        if self.reject_all:
            raise BackofficeCapabilityAccessRejected


class CanonicalBackofficeAuthorizationDependencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_context_resolves_subject_once_and_returns_exact_access(self):
        current = object()
        db = object()
        subject = _subject()
        resolver = AsyncMock(return_value=subject)

        with patch(
            f"{MODULE}.resolve_backoffice_authorization_subject",
            resolver,
        ):
            access = await get_current_backoffice_capability_access(
                current=current,
                db=db,
            )

        resolver.assert_awaited_once_with(db, current)
        self.assertIsInstance(access, BackofficeCapabilityAccess)
        self.assertIs(access.db, db)
        self.assertIs(access.subject, subject)

    async def test_owner_path_uses_canonical_context_without_dependency_layer_legacy_lookup(self):
        class NoGrantDB:
            def __getattr__(self, name):
                raise AssertionError(
                    f"Owner dependency unexpectedly queried legacy authority: {name}"
                )

        current = DashboardRequestContext(
            principal_id=101,
            company_id=77,
            backoffice_user_id=202,
            auth_revision=1,
            is_company_owner=True,
        )
        db = NoGrantDB()

        access = await get_current_backoffice_capability_access(
            current=current,
            db=db,
        )

        self.assertIs(access.db, db)
        self.assertTrue(access.subject.is_company_owner)
        self.assertIsNone(access.subject.legacy_grant_driver_id)

    async def test_ordinary_backoffice_uses_subject_resolver(self):
        current = object()
        db = object()
        subject = _subject(owner=False)
        resolver = AsyncMock(return_value=subject)

        with patch(
            f"{MODULE}.resolve_backoffice_authorization_subject",
            resolver,
        ):
            access = await get_current_backoffice_capability_access(
                current=current,
                db=db,
            )

        resolver.assert_awaited_once_with(db, current)
        self.assertIs(access.subject, subject)
        self.assertEqual(access.subject.legacy_grant_driver_id, 903)

    async def test_capability_success_returns_same_access_object(self):
        access = _FakeAccess()
        dependency = require_backoffice_capability("inventory.read")

        result = await dependency(access=access)

        self.assertIs(result, access)
        self.assertEqual(access.require_calls, ["inventory.read"])

    async def test_missing_capability_maps_to_opaque_403(self):
        access = _FakeAccess(reject_one=True)
        dependency = require_backoffice_capability("inventory.read")

        with self.assertRaises(HTTPException) as caught:
            await dependency(access=access)

        self.assertEqual(caught.exception.status_code, 403)
        self.assertEqual(caught.exception.detail, "Authorization denied.")
        self.assertNotIn("903", str(caught.exception.detail))
        self.assertNotIn("inventory.read", str(caught.exception.detail))

    async def test_require_all_preserves_all_semantics_and_returns_same_access(self):
        codes = ("inventory.read", "catalog.read")
        access = _FakeAccess()
        dependency = require_backoffice_capabilities(codes)

        result = await dependency(access=access)

        self.assertIs(result, access)
        self.assertEqual(access.require_all_calls, [codes])

    async def test_subject_failure_maps_to_opaque_403(self):
        resolver = AsyncMock(side_effect=BackofficeAuthorizationSubjectRejected)

        with patch(
            f"{MODULE}.resolve_backoffice_authorization_subject",
            resolver,
        ):
            with self.assertRaises(HTTPException) as caught:
                await get_current_backoffice_capability_access(
                    current=object(),
                    db=object(),
                )

        self.assertEqual(caught.exception.status_code, 403)
        self.assertEqual(caught.exception.detail, "Authorization denied.")

    def test_unknown_static_capabilities_fail_at_factory_creation(self):
        with self.assertRaises(ValueError):
            require_backoffice_capability("admin.anything")
        with self.assertRaises(ValueError):
            require_backoffice_capabilities(())
        with self.assertRaises(ValueError):
            require_backoffice_capabilities(
                ("inventory.read", "admin.anything")
            )

    def test_authentication_401_is_not_transformed_to_403(self):
        app = FastAPI()

        @app.get("/probe")
        async def probe(
            access: BackofficeCapabilityAccess = Depends(
                get_current_backoffice_capability_access
            ),
        ):
            return {"authorized": access is not None}

        async def reject_authentication():
            raise HTTPException(
                status_code=401,
                detail="upstream authentication sentinel",
            )

        async def fake_db():
            yield object()

        app.dependency_overrides[
            get_current_backoffice_context
        ] = reject_authentication
        app.dependency_overrides[get_db] = fake_db

        response = TestClient(app).get("/probe")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.json()["detail"],
            "upstream authentication sentinel",
        )

    def test_fastapi_request_cache_reuses_one_access_construction(self):
        app = FastAPI()
        dependency_a = require_backoffice_capability("inventory.read")
        dependency_b = require_backoffice_capability("catalog.read")
        resolver = AsyncMock(return_value=_subject(owner=True))

        @app.get("/probe")
        async def probe(
            first: BackofficeCapabilityAccess = Depends(dependency_a),
            second: BackofficeCapabilityAccess = Depends(dependency_b),
        ):
            return {"same_access": first is second}

        async def fake_current():
            return object()

        db = object()

        async def fake_db():
            yield db

        app.dependency_overrides[get_current_backoffice_context] = fake_current
        app.dependency_overrides[get_db] = fake_db

        with patch(
            f"{MODULE}.resolve_backoffice_authorization_subject",
            resolver,
        ):
            response = TestClient(app).get("/probe")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["same_access"])
        self.assertEqual(resolver.await_count, 1)

        for dependency in (dependency_a, dependency_b):
            access_depends = inspect.signature(
                dependency
            ).parameters["access"].default
            self.assertIs(
                access_depends.dependency,
                get_current_backoffice_capability_access,
            )
            self.assertTrue(access_depends.use_cache)

    def test_no_jwt_driver_legacy_authority_or_transaction_ownership(self):
        source = (
            ROOT
            / "api"
            / "authentication"
            / "backoffice_authorization.py"
        ).read_text(encoding="utf-8")

        forbidden = (
            "Driver",
            ".is_admin",
            "legacy_full_authority",
            "UserRole",
            "UserLocationAccess",
            "classification",
            "decode_company_token",
            "jwt",
            "TokenBlacklist",
            "legacy_grant_driver_id",
            ".principal_id",
            ".backoffice_user_id",
            ".commit(",
            ".rollback(",
            ".begin(",
        )
        for needle in forbidden:
            self.assertNotIn(needle, source)

        self.assertIn(
            "Depends(get_current_backoffice_context)",
            source,
        )
        self.assertIn("Depends(get_db)", source)
        self.assertEqual(
            source.count("resolve_backoffice_authorization_subject("),
            1,
        )

    def test_factory_declares_cached_canonical_access_dependency(self):
        dependency = require_backoffice_capability("inventory.read")
        access_depends = inspect.signature(
            dependency
        ).parameters["access"].default

        self.assertIs(
            access_depends.dependency,
            get_current_backoffice_capability_access,
        )
        self.assertTrue(access_depends.use_cache)
        self.assertTrue(PERMISSIONS)


if __name__ == "__main__":
    unittest.main()
