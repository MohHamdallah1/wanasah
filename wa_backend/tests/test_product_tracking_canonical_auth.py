from __future__ import annotations

import asyncio
import ast
import inspect
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi import HTTPException

BACKEND = Path(__file__).resolve().parents[1]

import api.product_tracking as product_tracking
from domains.authorization.backoffice_access import (
    BackofficeCapabilityAccess,
    BackofficeCapabilityAccessRejected,
)
from domains.authorization.backoffice_subject import BackofficeAuthorizationSubject
from domains.product_tracking import ProductTrackingError, normalize_tracking_mode


class FakeDb:
    def __init__(self, *, allowed: bool = True):
        self.allowed = allowed
        self.added: list[object] = []
        self.commit_calls = 0
        self.rollback_calls = 0
        self.scalar_calls = 0

    async def scalar(self, _statement):
        self.scalar_calls += 1
        return self.allowed

    def add(self, value):
        self.added.append(value)

    async def commit(self):
        self.commit_calls += 1

    async def rollback(self):
        self.rollback_calls += 1


def subject(
    *,
    owner: bool,
    company_id: int = 3101,
    principal_id: int = 71001,
    backoffice_user_id: int = 82002,
    legacy_grant_driver_id: int | None = 93003,
) -> BackofficeAuthorizationSubject:
    return BackofficeAuthorizationSubject(
        principal_id=principal_id,
        backoffice_user_id=backoffice_user_id,
        company_id=company_id,
        is_company_owner=owner,
        legacy_grant_driver_id=(None if owner else legacy_grant_driver_id),
    )


def access(*, owner: bool = False, allowed: bool = True, company_id: int = 3101):
    db = FakeDb(allowed=allowed)
    return db, BackofficeCapabilityAccess(
        db=db,
        subject=subject(owner=owner, company_id=company_id),
    )


def run(coro):
    return asyncio.run(coro)


def defaults_payload(*, lot: str = "REQUIRED", expiry: str = "REQUIRED"):
    return SimpleNamespace(
        lot_control_mode=lot,
        expiry_control_mode=expiry,
        lot_control_source="COMPANY",
        expiry_control_source="COMPANY",
    )


def mutation_payload(*, request_id=None, expected_version: int = 4):
    return product_tracking.ProductTrackingUpdate(
        request_id=request_id or uuid4(),
        expected_version=expected_version,
        lot_control_mode="OPTIONAL",
        expiry_control_mode="REQUIRED",
    )


def defaults_update_payload(*, request_id=None, lot="OPTIONAL", expiry="REQUIRED"):
    return product_tracking.ProductTrackingDefaultsUpdate(
        request_id=request_id or uuid4(),
        lot_control_mode=lot,
        expiry_control_mode=expiry,
    )


def test_source_has_only_canonical_authority_and_read_route_has_no_driver_dependency():
    path = BACKEND / "api" / "product_tracking.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    forbidden = (
        "get_current_driver",
        "get_current_admin",
        "get_current_inventory_access",
        "InventoryAccess",
        ".is_admin",
        "actor.company_id",
        "legacy_actor.company_id",
    )
    for token in forbidden:
        assert token not in source

    assert "get_current_backoffice_capability_access" in source
    assert "get_current_backoffice_legacy_driver" in source
    assert "BackofficeCapabilityAccess" in source

    read_fn = next(
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "get_product_tracking_defaults"
    )
    read_source = ast.get_source_segment(source, read_fn) or ""
    assert "get_current_backoffice_legacy_driver" not in read_source
    assert "Driver" not in read_source
    assert '"catalog.read"' in read_source


def test_canonical_company_owner_gets_catalog_authority_without_grant_driver_lookup():
    db, canonical = access(owner=True, allowed=False)
    run(product_tracking._require(canonical, "catalog.read"))
    run(product_tracking._require(canonical, "catalog.manage"))
    assert db.scalar_calls == 0


@pytest.mark.parametrize("capability", ["catalog.read", "catalog.manage"])
def test_ordinary_backoffice_exact_catalog_capabilities(capability):
    db, canonical = access(owner=False, allowed=True)
    assert canonical.subject.principal_id == 71001
    assert canonical.subject.backoffice_user_id == 82002
    assert canonical.subject.legacy_grant_driver_id == 93003
    assert len({71001, 82002, 93003}) == 3

    run(product_tracking._require(canonical, capability))
    assert db.scalar_calls == 1


def test_missing_capability_is_403():
    _db, canonical = access(owner=False, allowed=False)
    with pytest.raises(HTTPException) as exc_info:
        run(product_tracking._require(canonical, "catalog.manage"))
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Authorization denied."


def test_read_route_uses_canonical_company_scope(monkeypatch):
    db, canonical = access(owner=False, allowed=True, company_id=4101)
    loader = AsyncMock(return_value=defaults_payload())
    monkeypatch.setattr(
        product_tracking,
        "load_company_product_tracking_defaults_state",
        loader,
    )

    response = run(
        product_tracking.get_product_tracking_defaults(
            db=db,
            access=canonical,
        )
    )

    assert response["lot_control_mode"] == "REQUIRED"
    loader.assert_awaited_once_with(db, company_id=4101)


def test_defaults_write_uses_access_tenant_and_mapped_legacy_driver_provenance(monkeypatch):
    db, canonical = access(owner=False, allowed=True, company_id=5101)
    # Deliberately unrelated legacy fields: neither company nor is_admin may authorize/scope.
    legacy_actor = SimpleNamespace(id=96007, company_id=999999, is_admin=True)
    idem = SimpleNamespace()
    begin = AsyncMock(return_value=(idem, None))
    before = defaults_payload(lot="REQUIRED", expiry="REQUIRED")
    after = defaults_payload(lot="OPTIONAL", expiry="REQUIRED")
    loader = AsyncMock(return_value=before)
    saver = AsyncMock(return_value=after)
    complete = Mock()
    monkeypatch.setattr(product_tracking, "begin_idempotent_operation", begin)
    monkeypatch.setattr(product_tracking, "load_company_product_tracking_defaults_state", loader)
    monkeypatch.setattr(product_tracking, "save_company_product_tracking_defaults_serialized", saver)
    monkeypatch.setattr(product_tracking, "complete_idempotent_operation", complete)

    payload = defaults_update_payload()
    response = run(
        product_tracking.update_product_tracking_defaults(
            payload,
            db=db,
            access=canonical,
            legacy_actor=legacy_actor,
        )
    )

    assert response["lot_control_mode"] == "OPTIONAL"
    assert begin.await_args.kwargs["company_id"] == 5101
    assert begin.await_args.kwargs["actor_id"] == 96007
    loader.assert_awaited_once_with(db, company_id=5101)
    assert saver.await_args.kwargs["company_id"] == 5101
    assert db.commit_calls == 1
    assert db.rollback_calls == 0
    assert len(db.added) == 1
    audit = db.added[0]
    assert audit.company_id == 5101
    assert audit.admin_id == 96007
    complete.assert_called_once_with(idem, response)


def test_driver_is_admin_has_no_effect_on_write_authorization(monkeypatch):
    async def exercise(is_admin: bool):
        db, canonical = access(owner=False, allowed=True, company_id=5201)
        legacy_actor = SimpleNamespace(id=97007, company_id=5201, is_admin=is_admin)
        monkeypatch.setattr(
            product_tracking,
            "begin_idempotent_operation",
            AsyncMock(return_value=(SimpleNamespace(), {"replayed": True})),
        )
        result = await product_tracking.update_product_tracking_defaults(
            defaults_update_payload(),
            db=db,
            access=canonical,
            legacy_actor=legacy_actor,
        )
        return result, db

    first, first_db = run(exercise(False))
    second, second_db = run(exercise(True))
    assert first == second == {"replayed": True}
    assert first_db.rollback_calls == second_db.rollback_calls == 1


def test_idempotent_replay_preserves_response_and_rolls_back(monkeypatch):
    db, canonical = access(owner=False, allowed=True, company_id=6101)
    replay = {
        "product_variant_id": 77,
        "version": 5,
        "lot_control_mode": "OPTIONAL",
        "expiry_control_mode": "REQUIRED",
        "changed": True,
    }
    begin = AsyncMock(return_value=(SimpleNamespace(), replay))
    update = AsyncMock()
    monkeypatch.setattr(product_tracking, "begin_idempotent_operation", begin)
    monkeypatch.setattr(product_tracking, "update_product_tracking_modes", update)

    response = run(
        product_tracking.update_variant_product_tracking(
            77,
            mutation_payload(),
            db=db,
            access=canonical,
            legacy_actor=SimpleNamespace(id=98008, is_admin=False),
        )
    )

    assert response is replay
    assert db.rollback_calls == 1
    assert db.commit_calls == 0
    update.assert_not_awaited()


def test_variant_write_passes_canonical_tenant_and_legacy_actor_to_domain_event_path(monkeypatch):
    db, canonical = access(owner=False, allowed=True, company_id=6201)
    legacy_actor = SimpleNamespace(id=99009, company_id=123, is_admin=True)
    idem = SimpleNamespace()
    begin = AsyncMock(return_value=(idem, None))
    result = SimpleNamespace(
        product_variant_id=88,
        version=6,
        lot_control_mode="OPTIONAL",
        expiry_control_mode="REQUIRED",
        changed=True,
        before_snapshot={"version": 5},
        after_snapshot={"version": 6},
    )
    update = AsyncMock(return_value=result)
    complete = Mock()
    monkeypatch.setattr(product_tracking, "begin_idempotent_operation", begin)
    monkeypatch.setattr(product_tracking, "update_product_tracking_modes", update)
    monkeypatch.setattr(product_tracking, "complete_idempotent_operation", complete)

    payload = mutation_payload(expected_version=5)
    response = run(
        product_tracking.update_variant_product_tracking(
            88,
            payload,
            db=db,
            access=canonical,
            legacy_actor=legacy_actor,
        )
    )

    assert update.await_args.kwargs["company_id"] == 6201
    assert update.await_args.kwargs["actor_id"] == 99009
    assert update.await_args.kwargs["product_variant_id"] == 88
    assert update.await_args.kwargs["expected_version"] == 5
    assert update.await_args.kwargs["request_id"] == payload.request_id
    assert response["version"] == 6
    assert db.commit_calls == 1
    assert len(db.added) == 1
    assert db.added[0].company_id == 6201
    assert db.added[0].admin_id == 99009
    complete.assert_called_once_with(idem, response)

    domain_source = inspect.getsource(product_tracking.update_product_tracking_modes)
    assert "record_domain_event" in domain_source
    assert "actor_id=actor_id" in domain_source


def test_version_conflict_remains_409_and_rolls_back(monkeypatch):
    db, canonical = access(owner=False, allowed=True)
    monkeypatch.setattr(
        product_tracking,
        "begin_idempotent_operation",
        AsyncMock(return_value=(SimpleNamespace(), None)),
    )
    monkeypatch.setattr(
        product_tracking,
        "update_product_tracking_modes",
        AsyncMock(
            side_effect=ProductTrackingError(
                "PRODUCT_TRACKING_VERSION_CONFLICT",
                "Product changed. Refresh and retry.",
                status_code=409,
                context={"current_version": 9},
            )
        ),
    )

    with pytest.raises(HTTPException) as exc_info:
        run(
            product_tracking.update_variant_product_tracking(
                91,
                mutation_payload(expected_version=8),
                db=db,
                access=canonical,
                legacy_actor=SimpleNamespace(id=93003),
            )
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "PRODUCT_TRACKING_VERSION_CONFLICT"
    assert db.rollback_calls == 1
    assert db.commit_calls == 0


def _new_inventory_mutation_error():
    try:
        return product_tracking.InventoryMutationError("request-id conflict")
    except TypeError:
        exc = product_tracking.InventoryMutationError.__new__(
            product_tracking.InventoryMutationError
        )
        Exception.__init__(exc, "request-id conflict")
        return exc


def test_request_id_conflict_remains_409_and_rolls_back(monkeypatch):
    db, canonical = access(owner=False, allowed=True)
    monkeypatch.setattr(
        product_tracking,
        "begin_idempotent_operation",
        AsyncMock(side_effect=_new_inventory_mutation_error()),
    )

    with pytest.raises(HTTPException) as exc_info:
        run(
            product_tracking.update_variant_product_tracking(
                92,
                mutation_payload(),
                db=db,
                access=canonical,
                legacy_actor=SimpleNamespace(id=93003),
            )
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "PRODUCT_TRACKING_CONFLICT"
    assert db.rollback_calls == 1
    assert db.commit_calls == 0


def test_defaults_validation_modes_and_422_error_translation(monkeypatch):
    assert normalize_tracking_mode("none", field_name="lot") == "NONE"
    assert normalize_tracking_mode("optional", field_name="lot") == "OPTIONAL"
    assert normalize_tracking_mode("required", field_name="lot") == "REQUIRED"
    with pytest.raises(ProductTrackingError) as invalid:
        normalize_tracking_mode("sometimes", field_name="lot")
    assert invalid.value.status_code == 422

    db, canonical = access(owner=False, allowed=True)
    monkeypatch.setattr(
        product_tracking,
        "begin_idempotent_operation",
        AsyncMock(return_value=(SimpleNamespace(), None)),
    )
    monkeypatch.setattr(
        product_tracking,
        "load_company_product_tracking_defaults_state",
        AsyncMock(return_value=defaults_payload()),
    )
    monkeypatch.setattr(
        product_tracking,
        "save_company_product_tracking_defaults_serialized",
        AsyncMock(
            side_effect=ProductTrackingError(
                "PRODUCT_TRACKING_MODE_INVALID",
                "invalid mode",
                status_code=422,
                context={"field": "lot_control_mode"},
            )
        ),
    )

    with pytest.raises(HTTPException) as exc_info:
        run(
            product_tracking.update_product_tracking_defaults(
                defaults_update_payload(lot="sometimes"),
                db=db,
                access=canonical,
                legacy_actor=SimpleNamespace(id=93003),
            )
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["code"] == "PRODUCT_TRACKING_MODE_INVALID"
    assert db.rollback_calls == 1
    assert db.commit_calls == 0


def test_route_tenant_scope_is_independent_from_principal_user_and_driver_ids(monkeypatch):
    db = FakeDb(allowed=True)
    canonical = BackofficeCapabilityAccess(
        db=db,
        subject=subject(
            owner=False,
            company_id=777,
            principal_id=111,
            backoffice_user_id=222,
            legacy_grant_driver_id=333,
        ),
    )
    loader = AsyncMock(return_value=defaults_payload())
    monkeypatch.setattr(product_tracking, "load_company_product_tracking_defaults_state", loader)

    run(product_tracking.get_product_tracking_defaults(db=db, access=canonical))

    assert len({111, 222, 333, 777}) == 4
    loader.assert_awaited_once_with(db, company_id=777)
