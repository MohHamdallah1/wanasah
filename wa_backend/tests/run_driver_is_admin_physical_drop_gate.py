from __future__ import annotations

import ast
import importlib.util
import io
from pathlib import Path
import subprocess
import sys
import unittest

from alembic.migration import MigrationContext
from alembic.operations import Operations


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "wa_backend"
MODELS = BACKEND / "models.py"
IDENTITY_MODELS = BACKEND / "domains" / "identity" / "models.py"
VERSIONS = BACKEND / "alembic" / "versions"
MIGRATION_NAME = "f2c7a9d4e611_drop_driver_is_admin.py"
MIGRATION = VERSIONS / MIGRATION_NAME
BASE_SHA = "b9afadab4460749fcfe2a198c4a0ab128b832d75"
PARENT_REVISION = "e4c8a1d6b203"
REVISION = "f2c7a9d4e611"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _tree(path: Path) -> ast.Module:
    return ast.parse(_source(path), filename=str(path))


def _class(tree: ast.Module, name: str) -> ast.ClassDef:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    raise AssertionError(f"class {name} not found")


def _function(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"function {name} not found")


def _assigned_constant(tree: ast.Module, name: str):
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if not any(isinstance(target, ast.Name) and target.id == name for target in targets):
            continue
        return ast.literal_eval(node.value)
    raise AssertionError(f"assignment {name} not found")


def _call_name(node: ast.AST) -> str | None:
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        return f"{func.value.id}.{func.attr}"
    if isinstance(func, ast.Name):
        return func.id
    return None


def _op_calls(function: ast.FunctionDef) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "op"
    ]


def _load_module(path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _revision_metadata(path: Path) -> tuple[str | None, object]:
    tree = _tree(path)
    revision = None
    down_revision = None
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if not isinstance(target, ast.Name) or target.id not in {"revision", "down_revision"}:
                continue
            try:
                value = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                continue
            if target.id == "revision":
                revision = value
            else:
                down_revision = value
    return revision, down_revision


def _all_heads() -> set[str]:
    revisions: set[str] = set()
    referenced: set[str] = set()
    for path in VERSIONS.glob("*.py"):
        revision, parent = _revision_metadata(path)
        if not isinstance(revision, str):
            continue
        revisions.add(revision)
        if isinstance(parent, str):
            referenced.add(parent)
        elif isinstance(parent, (tuple, list)):
            referenced.update(value for value in parent if isinstance(value, str))
    return revisions - referenced


class DriverIsAdminPhysicalDropGate(unittest.TestCase):
    def test_driver_orm_metadata_has_no_is_admin(self):
        models = _load_module(MODELS, "_driver_physical_drop_models")
        self.assertNotIn("is_admin", models.Driver.__table__.c.keys())

        driver = _class(_tree(MODELS), "Driver")
        assigned = {
            target.id
            for node in driver.body
            if isinstance(node, ast.Assign)
            for target in node.targets
            if isinstance(target, ast.Name)
        }
        self.assertNotIn("is_admin", assigned)

    def test_new_revision_parent_is_exact_previous_head_and_becomes_only_head(self):
        tree = _tree(MIGRATION)
        self.assertEqual(_assigned_constant(tree, "revision"), REVISION)
        self.assertEqual(_assigned_constant(tree, "down_revision"), PARENT_REVISION)
        self.assertEqual(_all_heads(), {REVISION})

    def test_upgrade_drops_only_drivers_is_admin(self):
        upgrade = _function(_tree(MIGRATION), "upgrade")
        calls = _op_calls(upgrade)
        self.assertEqual(len(calls), 1)
        call = calls[0]
        self.assertEqual(_call_name(call), "op.drop_column")
        self.assertEqual([ast.literal_eval(arg) for arg in call.args], ["drivers", "is_admin"])
        self.assertEqual(call.keywords, [])

    def test_downgrade_restores_only_structural_boolean_column(self):
        downgrade = _function(_tree(MIGRATION), "downgrade")
        calls = _op_calls(downgrade)
        self.assertEqual(len(calls), 1)
        add_call = calls[0]
        self.assertEqual(_call_name(add_call), "op.add_column")
        self.assertEqual(ast.literal_eval(add_call.args[0]), "drivers")
        self.assertEqual(len(add_call.args), 2)

        column = add_call.args[1]
        self.assertIsInstance(column, ast.Call)
        self.assertEqual(_call_name(column), "sa.Column")
        self.assertEqual(ast.literal_eval(column.args[0]), "is_admin")
        self.assertEqual(_call_name(column.args[1]), "sa.Boolean")

        keywords = {keyword.arg: keyword.value for keyword in column.keywords}
        self.assertIs(keywords["nullable"].value, False)
        server_default = keywords["server_default"]
        self.assertEqual(_call_name(server_default), "sa.text")
        self.assertEqual(ast.literal_eval(server_default.args[0]), "false")

        migration_source = _source(MIGRATION)
        for forbidden in ("CompanyOwner", "role", "capabilit", "manager", "supervisor"):
            self.assertNotIn(forbidden, migration_source)

    def test_offline_postgresql_sql_is_exact_drop_and_structural_add(self):
        migration = _load_module(MIGRATION, "_driver_physical_drop_migration")

        upgrade_buffer = io.StringIO()
        upgrade_context = MigrationContext.configure(
            dialect_name="postgresql",
            opts={"as_sql": True, "output_buffer": upgrade_buffer},
        )
        migration.op = Operations(upgrade_context)
        migration.upgrade()
        upgrade_sql = " ".join(upgrade_buffer.getvalue().lower().split())
        self.assertIn("alter table drivers drop column is_admin", upgrade_sql)

        downgrade_buffer = io.StringIO()
        downgrade_context = MigrationContext.configure(
            dialect_name="postgresql",
            opts={"as_sql": True, "output_buffer": downgrade_buffer},
        )
        migration.op = Operations(downgrade_context)
        migration.downgrade()
        downgrade_sql = " ".join(downgrade_buffer.getvalue().lower().split())
        self.assertIn("alter table drivers add column is_admin boolean", downgrade_sql)
        self.assertIn("default false", downgrade_sql)
        self.assertIn("not null", downgrade_sql)

    def test_historical_migrations_are_untouched_on_this_branch(self):
        result = subprocess.run(
            [
                "git",
                "diff",
                "--name-status",
                f"{BASE_SHA}...HEAD",
                "--",
                "wa_backend/alembic/versions",
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        changed = [line for line in result.stdout.splitlines() if line.strip()]
        self.assertEqual(changed, [f"A\twa_backend/alembic/versions/{MIGRATION_NAME}"])

    def test_no_replacement_generic_admin_flag_is_introduced(self):
        driver_source = ast.get_source_segment(_source(MODELS), _class(_tree(MODELS), "Driver")) or ""
        production_delta_source = driver_source + "\n" + _source(MIGRATION)
        for forbidden in ("is_owner", "is_superuser", "is_manager", "admin_override"):
            self.assertNotIn(forbidden, production_delta_source)

    def test_company_owner_remains_explicit_and_independent(self):
        identity_source = _source(IDENTITY_MODELS)
        owner = _class(ast.parse(identity_source), "CompanyOwner")
        owner_source = ast.get_source_segment(identity_source, owner) or ""
        assigned = {
            target.id
            for node in owner.body
            if isinstance(node, ast.Assign)
            for target in node.targets
            if isinstance(target, ast.Name)
        }
        self.assertIn("company_id", assigned)
        self.assertIn("backoffice_user_id", assigned)
        self.assertNotIn("Driver", owner_source)
        self.assertNotIn("is_admin", owner_source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
