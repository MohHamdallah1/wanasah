"""Focused additive Identity model/migration contract; no live DB or app startup.

Run from wa_backend with an existing backend interpreter:
    python -m unittest tests.test_identity_schema_expand -v
"""
from __future__ import annotations

import ast
import importlib.util
import io
from pathlib import Path
import unittest
from unittest.mock import patch

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.schema import CreateTable
from sqlalchemy.dialects import postgresql

from models import Base


def _signature(table):
    return (
        tuple((c.name, str(c.type), c.nullable, c.primary_key) for c in table.columns),
        tuple(sorted((str(c.name), str(c)) for c in table.constraints)),
        tuple(sorted((i.name, tuple(c.name for c in i.columns)) for i in table.indexes)),
    )


_LEGACY = {name: _signature(table) for name, table in Base.metadata.tables.items()}
from domains.identity.models import (  # noqa: E402
    BackofficeUser, CompanyOwner, CompanyPrincipal, FieldRepresentative,
)
from domains.identity.types import PrincipalType  # noqa: E402

_MODELS = (CompanyPrincipal, BackofficeUser, FieldRepresentative, CompanyOwner)
_TABLES = {model.__tablename__ for model in _MODELS}
_MIGRATION = Path(__file__).resolve().parents[1] / "alembic/versions/e9c4b1a7d620_identity_schema_expand.py"
_SPEC = importlib.util.spec_from_file_location("identity_expand_migration", _MIGRATION)
migration = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(migration)


def _unique(table):
    return {tuple(c.name for c in constraint.columns) for constraint in table.constraints
            if isinstance(constraint, UniqueConstraint)}


def _foreign(table):
    return {(tuple(e.parent.name for e in c.elements),
             tuple(e.target_fullname for e in c.elements), c.ondelete, c.onupdate)
            for c in table.constraints if isinstance(c, ForeignKeyConstraint)}


def _offline(direction):
    output = io.StringIO()
    context = MigrationContext.configure(dialect_name="postgresql", opts={
        "as_sql": True, "output_buffer": output, "target_metadata": Base.metadata,
    })
    with patch.object(migration, "op", Operations(context)), patch.dict(
        "os.environ", {"DATABASE_URL": "postgresql+asyncpg://identity_runtime@127.0.0.1/identity_test"},
    ):
        getattr(migration, direction)()
    return output.getvalue()


class IdentitySchemaExpandTests(unittest.TestCase):
    def test_only_four_new_tables_and_no_legacy_metadata_changes(self):
        self.assertEqual(set(Base.metadata.tables) - set(_LEGACY), _TABLES)
        self.assertEqual({name: _signature(Base.metadata.tables[name]) for name in _LEGACY}, _LEGACY)
        self.assertIn("is_admin", Base.metadata.tables["drivers"].c)
        self.assertEqual({p.value for p in PrincipalType}, {"BACKOFFICE", "FIELD_REPRESENTATIVE"})

    def test_profiles_have_independent_pk_and_unique_principal_link(self):
        for model in (BackofficeUser, FieldRepresentative):
            table = model.__table__
            self.assertEqual([c.name for c in table.primary_key], ["id"])
            self.assertTrue(table.c.id.autoincrement)
            self.assertFalse(table.c.principal_id.primary_key)
            self.assertFalse(table.c.id.foreign_keys)
            self.assertIn(("company_id", "principal_id"), _unique(table))
            self.assertIn(("company_id", "id"), _unique(table))

    def test_company_and_type_are_enforced_together_by_database(self):
        for model, kind in ((BackofficeUser, "BACKOFFICE"), (FieldRepresentative, "FIELD_REPRESENTATIVE")):
            table = model.__table__
            self.assertIn((
                ("company_id", "principal_id", "principal_type"),
                ("company_principals.company_id", "company_principals.id", "company_principals.principal_type"),
                "RESTRICT", "RESTRICT",
            ), _foreign(table))
            checks = {str(c.sqltext) for c in table.constraints if isinstance(c, CheckConstraint)}
            self.assertIn(f"principal_type = '{kind}'", checks)
            self.assertEqual(str(table.c.principal_type.server_default.arg), f"'{kind}'")

    def test_owner_slot_references_tenant_backoffice_not_principal(self):
        table = CompanyOwner.__table__
        self.assertEqual([c.name for c in table.primary_key], ["company_id"])
        self.assertFalse(table.c.company_id.autoincrement)
        self.assertIn((
            ("company_id", "backoffice_user_id"),
            ("backoffice_users.company_id", "backoffice_users.id"), "RESTRICT", "RESTRICT",
        ), _foreign(table))
        self.assertNotIn("principal_id", table.c)

    def test_principal_identity_and_field_policy_boundaries(self):
        principal = CompanyPrincipal.__table__
        self.assertIn(("company_id", "username"), _unique(principal))
        self.assertIn(("company_id", "id", "principal_type"), _unique(principal))
        self.assertFalse(principal.c.company_id.nullable)
        self.assertEqual(str(principal.c.auth_revision.server_default.arg), "1")
        for model in (CompanyPrincipal, BackofficeUser, CompanyOwner):
            self.assertNotIn("can_allow_debt", model.__table__.c)
            self.assertNotIn("max_debt_limit", model.__table__.c)
            self.assertNotIn("branch_id", model.__table__.c)
            self.assertNotIn("is_admin", model.__table__.c)
        field = FieldRepresentative.__table__
        self.assertEqual((field.c.max_debt_limit.type.precision, field.c.max_debt_limit.type.scale), (12, 3))
        self.assertIn("max_debt_limit >= 0", {str(c.sqltext) for c in field.constraints if isinstance(c, CheckConstraint)})

    def test_postgresql_ddl_compiles_without_trigger_or_enum_dependency(self):
        for model in _MODELS:
            table = model.__table__
            ddl = str(CreateTable(table).compile(dialect=postgresql.dialect()))
            self.assertIn("PRIMARY KEY", ddl)
            self.assertIn("REFERENCES companies (id)", ddl)
            for constraint in table.constraints:
                self.assertLessEqual(len(str(constraint.name)), 63)
        self.assertIn("id SERIAL", str(CreateTable(BackofficeUser.__table__).compile(dialect=postgresql.dialect())))
        self.assertIn("id SERIAL", str(CreateTable(FieldRepresentative.__table__).compile(dialect=postgresql.dialect())))

    def test_migration_is_additive_with_fail_closed_rls_and_grants(self):
        self.assertEqual(migration.down_revision, "c6f1a4d8e203")
        sql = _offline("upgrade")
        self.assertEqual(sql.count("CREATE TABLE "), 4)
        self.assertEqual(sql.count("ENABLE ROW LEVEL SECURITY"), 4)
        self.assertEqual(sql.count("FORCE ROW LEVEL SECURITY"), 4)
        self.assertEqual(sql.count("AS RESTRICTIVE"), 4)
        self.assertEqual(sql.count("CREATE POLICY "), 8)
        self.assertEqual(sql.count("GRANT USAGE, SELECT ON SEQUENCE"), 3)
        self.assertNotIn("drivers", sql)
        self.assertNotIn("is_admin", sql)
        self.assertNotIn("DROP ", sql)
        self.assertNotIn("INSERT INTO", sql)
        self.assertIn("WITH CHECK (company_id =", sql)
        tree = ast.parse(_MIGRATION.read_text(encoding="utf-8"))
        upgrade = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "upgrade")
        operations = {n.func.attr for n in ast.walk(upgrade) if isinstance(n, ast.Call)
                      and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name) and n.func.value.id == "op"}
        self.assertEqual(operations, {"create_table", "create_index", "execute", "f"})

    def test_empty_downgrade_is_bounded_and_populated_downgrade_fails_closed(self):
        sql = _offline("downgrade")
        self.assertIn("SET LOCAL row_security = off", sql)
        self.assertIn("IN ACCESS EXCLUSIVE MODE", sql)
        self.assertLess(sql.index("LOCK TABLE"), sql.index("IF EXISTS"))
        self.assertIn("Cannot downgrade populated identity tables", sql)
        self.assertEqual(sql.count("DROP TABLE "), 4)
        self.assertLess(sql.index("DROP TABLE company_owners"), sql.index("DROP TABLE backoffice_users"))
        self.assertLess(sql.index("DROP TABLE backoffice_users"), sql.index("DROP TABLE company_principals"))
        self.assertNotIn("drivers", sql)
        with patch.dict("os.environ", {"DATABASE_URL": "postgresql+asyncpg://unsafe-role@127.0.0.1/test"}):
            with self.assertRaises(RuntimeError):
                migration._runtime_role()


if __name__ == "__main__":
    unittest.main()
