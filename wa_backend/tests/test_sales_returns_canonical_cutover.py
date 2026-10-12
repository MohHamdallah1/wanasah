"""Focused canonical Backoffice transport/authorization checks for Sales Returns."""
from __future__ import annotations

import inspect
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
with patch.dict(os.environ, {
    "ENVIRONMENT": "test",
    "SECRET_KEY": "SalesReturnCanonicalSyntheticSecret123456789012345678901234567890",
    "DATABASE_URL": "postgresql+asyncpg://return_unit@127.0.0.1:1/return_unit",
    "DATABASE_URL_MIGRATION": "postgresql+asyncpg://return_admin@127.0.0.1:1/return_unit",
}):
    from api import sales_returns as module

from api.authentication.backoffice_authorization import get_current_backoffice_capability_access
from api.authentication.backoffice_compatibility import get_current_backoffice_legacy_driver
from domains.authorization.backoffice_access import BackofficeCapabilityAccess
from domains.authorization.backoffice_subject import BackofficeAuthorizationSubject


CAPABILITY = "sales_return.create"


def database():
    db = MagicMock(spec=AsyncSession)
    db.scalar = AsyncMock(return_value=True)
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


def access(db, *, owner=False, allowed=True):
    db.scalar.return_value = allowed
    return BackofficeCapabilityAccess(
        db,
        BackofficeAuthorizationSubject(
            principal_id=101,
            backoffice_user_id=202,
            company_id=77,
            is_company_owner=owner,
            legacy_grant_driver_id=None if owner else 903,
        ),
    )


class LegacyActor:
    def __init__(self, legacy_flag):
        self.id = 903
        self._legacy_flag = legacy_flag

    @property
    def is_admin(self):
        raise AssertionError("Legacy Driver flags must never supply authority")

    @property
    def company_id(self):
        raise AssertionError("Legacy Driver company must never supply tenant authority")


class SalesReturnsCanonicalCutoverTests(unittest.IsolatedAsyncioTestCase):
    async def test_ordinary_backoffice_exact_capability_and_owner_semantics(self):
        ordinary_db = database()
        ordinary = access(ordinary_db, allowed=True)
        self.assertIs(await module._sales_return_access(access=ordinary), ordinary)
        ordinary_db.scalar.assert_awaited_once()

        owner_db = database()
        owner = access(owner_db, owner=True)
        self.assertIs(await module._sales_return_access(access=owner), owner)
        owner_db.scalar.assert_not_awaited()

    async def test_missing_capability_fails_opaque_403(self):
        db = database()
        denied = access(db, allowed=False)
        with self.assertRaises(HTTPException) as caught:
            await module._sales_return_access(access=denied)
        self.assertEqual(caught.exception.status_code, 403)
        self.assertEqual(caught.exception.detail, "Authorization denied.")
        self.assertNotIn(CAPABILITY, caught.exception.detail)

    def test_all_five_routes_use_canonical_capability_and_reads_do_not_load_driver(self):
        get_routes = (
            module.list_returns,
            module.returnable_sales,
            module.return_source,
            module.return_detail,
        )
        for endpoint in (*get_routes, module.post_return):
            access_depends = inspect.signature(endpoint).parameters["access"].default
            self.assertIs(access_depends.dependency, module._sales_return_access)
            self.assertTrue(access_depends.use_cache)

        factory_access = inspect.signature(module._sales_return_access).parameters["access"].default
        self.assertIs(factory_access.dependency, get_current_backoffice_capability_access)
        self.assertTrue(factory_access.use_cache)

        for endpoint in get_routes:
            self.assertNotIn("legacy_actor", inspect.signature(endpoint).parameters)

        actor_depends = inspect.signature(module.post_return).parameters["legacy_actor"].default
        self.assertIs(actor_depends.dependency, get_current_backoffice_legacy_driver)
        self.assertTrue(actor_depends.use_cache)

    async def test_post_uses_canonical_company_and_legacy_id_only_for_attribution(self):
        payload = object()
        current_access = SimpleNamespace(company_id=77)
        for legacy_flag in (False, True):
            db = database()
            actor = LegacyActor(legacy_flag)
            with patch.object(
                module,
                "create_sales_return",
                new=AsyncMock(return_value={"id": 1}),
            ) as create:
                result = await module.post_return(
                    payload=payload,
                    db=db,
                    access=current_access,
                    legacy_actor=actor,
                )
            self.assertEqual(result, {"id": 1})
            create.assert_awaited_once_with(
                db,
                company_id=77,
                actor_id=903,
                payload=payload,
            )
            db.commit.assert_awaited_once_with()
            db.rollback.assert_not_awaited()

    def test_source_has_no_legacy_auth_transport_or_driver_authority(self):
        source = Path(module.__file__).read_text(encoding="utf-8")
        self.assertIn('require_backoffice_capability("sales_return.create")', source)
        self.assertIn("get_current_backoffice_legacy_driver", source)
        self.assertNotIn("legacy_backoffice_transport", source)
        self.assertNotIn("get_current_driver", source)
        self.assertNotIn("legacy_actor.company_id", source)
        self.assertNotIn("legacy_actor.is_admin", source)
        self.assertNotIn("principal_id == legacy_actor.id", source)
        self.assertGreaterEqual(source.count("company_id=access.company_id"), 5)


if __name__ == "__main__":
    unittest.main()