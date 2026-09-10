"""Offline regression checks, with no application DB or secrets loaded."""
import sys
from pathlib import Path
import pytest
from sqlalchemy.schema import CreateTable
from sqlalchemy.dialects import postgresql

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from token_identity import access_token_identity
from models import role_permissions


def test_valid_access_identity():
    assert access_token_identity({'type': 'access', 'sub': '7', 'company_id': 11}) == (7, 11)


@pytest.mark.parametrize('kind', ['refresh', None, '', 'Admin'])
def test_reject_non_access_token(kind):
    with pytest.raises(ValueError):
        access_token_identity({'type': kind, 'sub': '7', 'company_id': 11})


@pytest.mark.parametrize('value', [None, True, False, 0, -1, 1.5, '1.0', '01', ' 1', 2**31, [], {}])
@pytest.mark.parametrize('field', ['sub', 'company_id'])
def test_identity_rejected_before_database_access(value, field):
    payload = {'type': 'access', 'sub': '7', 'company_id': 11, field: value}
    with pytest.raises((ValueError, TypeError)):
        access_token_identity(payload)


def test_role_grant_cannot_reference_another_company_role():
    ddl = str(CreateTable(role_permissions).compile(dialect=postgresql.dialect()))
    assert 'company_id INTEGER NOT NULL' in ddl
    assert 'FOREIGN KEY(company_id, role_id) REFERENCES roles (company_id, id)' in ddl
    assert 'ON DELETE CASCADE' in ddl
    assert any(tuple(c.name for c in index.columns) == ('company_id', 'role_id')
               for index in role_permissions.indexes)
