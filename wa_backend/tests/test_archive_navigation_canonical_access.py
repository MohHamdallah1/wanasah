from __future__ import annotations

from pathlib import Path

from sqlalchemy.dialects import postgresql

from domains.authorization.backoffice_access import BackofficeCapabilityAccess
from domains.authorization.backoffice_subject import BackofficeAuthorizationSubject
from domains.dispatch_archive_navigation import (
    _archive_access as dispatch_archive_access,
    dispatch_archive_target_query,
)
from domains.inventory_archive_navigation import (
    _archive_access as inventory_archive_access,
    inventory_archive_target_query,
)
from domains.operations_archive_navigation import (
    _archive_access as operations_archive_access,
    operations_archive_target_query,
)


ROOT = Path(__file__).resolve().parents[1]


def _access(*, owner: bool = False) -> BackofficeCapabilityAccess:
    return BackofficeCapabilityAccess(
        db=None,
        subject=BackofficeAuthorizationSubject(
            principal_id=101,
            backoffice_user_id=202,
            company_id=77,
            is_company_owner=owner,
            legacy_grant_driver_id=None if owner else 903,
        ),
    )


def _param_values(compiled):
    values = []
    for value in compiled.params.values():
        if isinstance(value, (list, tuple, set, frozenset)):
            values.extend(value)
        else:
            values.append(value)
    return values


def test_shared_archive_adapters_accept_canonical_access_without_rewrapping():
    access = _access()
    assert inventory_archive_access(access) is access
    assert dispatch_archive_access(access) is access
    assert operations_archive_access(access) is access


def test_archive_adapters_have_no_direct_legacy_admin_or_tenant_authority():
    for relative in (
        "domains/inventory_archive_navigation.py",
        "domains/dispatch_archive_navigation.py",
        "domains/operations_archive_navigation.py",
    ):
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert ".is_admin" not in source
        assert "actor.company_id" not in source
        assert "access.actor" not in source
        assert "BackofficeCapabilityAccess" in source
        assert "InventoryAccess" not in source


def test_canonical_shortage_projection_uses_explicit_shortage_read_capability():
    query = dispatch_archive_target_query(
        _access(),
        501,
        {"OPEN_SHORTAGE": 90},
    )
    assert query is not None
    compiled = query.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    params = _param_values(compiled)
    assert "shortage_requests" in sql
    assert "permissions" in sql
    assert "shortage.read" in params
    assert 77 in params
    assert 903 in params


def test_canonical_custody_projection_uses_explicit_settlement_read_capability():
    query = operations_archive_target_query(
        _access(),
        501,
        {"OPEN_CUSTODY": 95},
    )
    assert query is not None
    compiled = query.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    params = _param_values(compiled)
    assert "session_inventory_snapshots" in sql
    assert "permissions" in sql
    assert "settlement.read" in params
    assert 77 in params
    assert 903 in params


def test_canonical_owner_needs_no_legacy_grant_driver_for_archive_projection():
    owner = _access(owner=True)
    shortage = dispatch_archive_target_query(owner, 501, {"OPEN_SHORTAGE": 90})
    custody = operations_archive_target_query(owner, 501, {"OPEN_CUSTODY": 95})
    inventory = inventory_archive_target_query(owner, 501, {"PRODUCT_LOCATION": 60})
    assert shortage is not None
    assert custody is not None
    assert inventory is not None
    for query in (shortage, custody, inventory):
        compiled = query.compile(dialect=postgresql.dialect())
        assert 77 in _param_values(compiled)
