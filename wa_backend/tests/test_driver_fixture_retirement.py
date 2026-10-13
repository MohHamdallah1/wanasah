"""Post-drop physical-column census across all backend tests, without app imports.

Sentinel flags, rejected token claims, historical migration assertions and
source-audit corpora remain valid; executable Driver-column dependencies do not.
"""
import ast
from pathlib import Path
import re
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock
from uuid import uuid4


TESTS = Path(__file__).resolve().parent



RETIREMENT_FILES = (
    'run_identity_schema_expand_gate.py',
    'test_canonical_backoffice_runtime_compatibility.py',
    'test_canonical_field_runtime_compatibility.py',
    'test_catalog_canonical_cutover.py',
    'test_catalog_family_batch_b37_db.py',
    'test_committed_costed_inbound_race_c2_isolated.py',
    'test_cost_policy_lock_contention_c2_db.py',
    'test_costed_driver_customer_return_c2_db.py',
    'test_costed_driver_sale_correction_real_c2_db.py',
    'test_costed_inbound_asgi_http_c2_db.py',
    'test_driver_session_field_context_cutover.py',
    'test_identity_schema_expand.py',
    'test_legacy_field_transport.py',
    'test_live_stock_canonical_cutover.py',
    'test_pricing_bulk_catalog_b3_db.py',
    'test_simple_products_canonical_cutover.py',
    'test_supplier_master_db.py',
    'test_warehouse_costed_inbound_c2_db.py',
    'test_warehouse_inbound_concurrent_recovery_c2_db.py',
    'test_warehouse_inbound_requires_cost_policy_c2_db.py',
    'canonical_actor_fixtures.py',
    'test_driver_fixture_retirement.py',
)


def physical_references(source):
    """Classify ORM constructors/attributes, SQL, and explicit column contracts."""
    tree = ast.parse(source)
    aliases = {"Driver"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "models":
            aliases.update(a.asname or a.name for a in node.names if a.name == "Driver")

    def driver(node):
        return (isinstance(node, ast.Name) and node.id in aliases) or (
            isinstance(node, ast.Attribute) and node.attr == "Driver")

    def driver_table(node):
        return any(isinstance(part, ast.Subscript) and isinstance(part.slice, ast.Constant)
                   and part.slice.value == "drivers" and isinstance(part.value, ast.Attribute)
                   and part.value.attr == "tables" for part in ast.walk(node))

    real_rows = set()
    literal_dicts = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            value = node.value
            if value is not None:
                if isinstance(value, ast.Dict):
                    for target in targets:
                        literal_dicts[ast.unparse(target)] = value
                if any(isinstance(call, ast.Call) and (
                        driver(call.func) or (isinstance(call.func, ast.Name)
                                              and call.func.id == "select"
                                              and any(driver(arg) for arg in call.args)))
                       for call in ast.walk(value)):
                    real_rows.update(ast.unparse(target) for target in targets)
            if isinstance(node, ast.AnnAssign) and driver(node.annotation):
                real_rows.add(ast.unparse(node.target))
        if isinstance(node, ast.arg) and node.annotation is not None and driver(node.annotation):
            real_rows.add(node.arg)

    def flag_dictionary(node):
        if isinstance(node, ast.Name):
            node = literal_dicts.get(node.id)
        return isinstance(node, ast.Dict) and any(
            isinstance(key, ast.Constant) and key.value == "is_admin" for key in node.keys
        )

    sql_literals = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = node.func.attr if isinstance(node.func, ast.Attribute) else (
            node.func.id if isinstance(node.func, ast.Name) else None
        )
        if name in {"execute", "executemany", "scalar", "scalars", "text", "SQL"} and node.args:
            query = node.args[0]
            if isinstance(query, ast.Name):
                # Resolve literal SQL assigned before an execute/text call.
                query = next((n.value for n in ast.walk(tree)
                              if isinstance(n, ast.Assign) and any(
                                  isinstance(t, ast.Name) and t.id == query.id for t in n.targets)
                              and isinstance(n.value, (ast.Constant, ast.JoinedStr, ast.BinOp))), query)
            sql_literals.update(id(n) for n in ast.walk(query) if isinstance(n, ast.Constant))

    references = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Attribute) and node.attr == "is_admin"
                and (driver(node.value) or ast.unparse(node.value) in real_rows
                     or driver_table(node.value)
                     or any(driver(part) for part in ast.walk(node.value)))):
            references.append((node.lineno, "ORM attribute"))
        if isinstance(node, ast.Call):
            if (isinstance(node.func, ast.Name) and (
                    node.func.id == "setattr" or (node.func.id == "getattr" and len(node.args) == 2))
                    and len(node.args) >= 2 and isinstance(node.args[1], ast.Constant)
                    and node.args[1].value == "is_admin"
                    and (driver(node.args[0]) or ast.unparse(node.args[0]) in real_rows)):
                references.append((node.lineno, "ORM reflected attribute"))
            constructor = driver(node.func) or (node.args and driver(node.args[0]))
            if constructor and any(k.arg == "is_admin" or
                                   (k.arg is None and flag_dictionary(k.value))
                                   for k in node.keywords):
                references.append((node.lineno, "ORM constructor/insert"))
            if (isinstance(node.func, ast.Attribute) and node.func.attr == "assertIn"
                    and node.args and isinstance(node.args[0], ast.Constant)
                    and node.args[0].value == "is_admin"
                    and "drivers" in ast.unparse(node)):
                references.append((node.lineno, "required ORM column"))
            if (isinstance(node.func, ast.Attribute) and node.func.attr == "change_driver"
                    and any(k.arg == "is_admin" for k in node.keywords)):
                references.append((node.lineno, "ORM update"))
            if (isinstance(node.func, ast.Attribute) and node.func.attr == "values"
                    and "update" in ast.unparse(node.func.value)
                    and any(k.arg == "is_admin" for k in node.keywords)):
                references.append((node.lineno, "SQL table update"))
        if (isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant)
                and node.slice.value == "is_admin"
                and (driver_table(node.value)
                     or any(driver(part) for part in ast.walk(node.value)))):
            references.append((node.lineno, "ORM column lookup"))
        if isinstance(node, ast.Tuple) and any(driver(item) for item in node.elts):
            if any(isinstance(item, ast.Constant) and isinstance(item.value, str)
                   and "is_admin" in item.value.split() for item in node.elts):
                references.append((node.lineno, "Driver column projection"))
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) in sql_literals:
            if (re.search(r"\b(?:FROM|INTO|UPDATE|JOIN)\s+(?:public\.)?drivers\b",
                          node.value, re.I)
                    and re.search(r"\bis_admin\b", node.value, re.I)):
                references.append((node.lineno, "physical Driver SQL"))
    return sorted(set(references))


def fixture_definitions(**bindings):
    """Execute only test seeding functions with a strictly flag-free Driver double."""
    source = (TESTS / "canonical_actor_fixtures.py").read_text(encoding="utf-8-sig")
    tree = ast.parse(source)
    functions = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    namespace = {"uuid4": uuid4, "SimpleNamespace": SimpleNamespace, **bindings}
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(TESTS / "canonical_actor_fixtures.py"), "exec"), namespace)
    return namespace


class FlagFreeDriver(SimpleNamespace):
    def __init__(self, **values):
        if set(values) - {"id", "company_id", "username", "full_name", "password_hash", "is_active"}:
            raise AssertionError("Fixture depends on a removed Driver column")
        super().__init__(**values)

    def set_password(self, password):
        self.password_hash = "synthetic-hash:" + password


class DriverFixtureRetirementTests(unittest.IsolatedAsyncioTestCase):
    def test_post_cutover_backfill_gate_seeds_driver_without_removed_column(self):
        path = TESTS / "run_identity_legacy_backfill_gate.py"
        source = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source)
        driver_seed = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "_driver"
        )
        literals = [
            node.value for node in ast.walk(driver_seed)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        ]
        driver_sql = next(value for value in literals if "INSERT INTO drivers(" in value)
        self.assertNotIn("is_admin", driver_sql)
        self.assertIn("is_active,can_allow_debt,max_debt_limit,created_at", driver_sql)
        self.assertIn("DRIVER_SEED_WITHOUT_PHYSICAL_ADMIN_COLUMN", source)
        self.assertIn("PRE_CUTOVER_CLASSIFICATION_FAILS_CLOSED", source)
        self.assertIn("CANONICAL_PERSISTED_EVIDENCE_ONLY", source)

    def test_all_backend_fixture_census_has_no_physical_dependencies(self):
        violations = {}
        for path in sorted(TESTS.rglob("*.py")):
            source = path.read_text(encoding="utf-8-sig")
            hits = physical_references(source)
            if hits:
                violations[str(path.relative_to(TESTS))] = hits
        self.assertEqual(violations, {})

    def test_all_retirement_files_have_no_deleted_legacy_authorization_dependency(self):
        forbidden_modules = {"inventory_access", "domains.authorization.inventory_access"}
        forbidden_names = {"InventoryAccess", "subject_from_legacy_driver", "AuthorizationSubject"}
        for filename in RETIREMENT_FILES:
            tree = ast.parse((TESTS / filename).read_text(encoding="utf-8-sig"))
            with self.subTest(file=filename):
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        self.assertTrue(forbidden_modules.isdisjoint(a.name for a in node.names))
                    elif isinstance(node, ast.ImportFrom):
                        self.assertNotIn(node.module, forbidden_modules)
                        self.assertTrue((forbidden_names | {"inventory_access"}).isdisjoint(
                            a.name for a in node.names))
                    elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                        self.assertNotIn(node.id, forbidden_names)
                    elif isinstance(node, ast.Attribute):
                        self.assertNotIn(node.attr, forbidden_names)
        # Source-audit strings and historical evidence are intentionally not imports.

    def test_census_distinguishes_real_column_dependencies_from_negative_proof(self):
        for source in (
            "Driver(id=303, is_admin=True)", "Driver.is_admin.is_(True)",
            "row = Driver(id=303)\nrow.is_admin = True",
            "row = db.scalar(select(Driver))\nassert row.is_admin",
            "row = Driver(id=303)\nsetattr(row, 'is_admin', True)",
            "row = Driver(id=303)\ngetattr(row, 'is_admin')",
            "from models import Driver as Actor\nrow = Actor(id=303)\nsetattr(row, 'is_admin', False)",
            "Driver.__table__.c.is_admin",
            "Driver(**{'id': 303, 'is_admin': False})",
            "values = {'is_admin': True}\nDriver(**values)",
            'Driver.__table__.c["is_admin"]',
            "self.insert(Driver, id=303, is_admin=False)",
            "self.change_driver(is_admin=True)",
            'table.update().values(is_admin=False)',
            '(Driver, "id company_id is_admin")',
            'text("SELECT id FROM drivers WHERE is_admin=true")',
            'text("SELECT is_admin FROM drivers WHERE id=:id")',
            'conn.execute("SELECT d.is_admin FROM drivers AS d WHERE d.id=%s", (303,))',
            'conn.execute("UPDATE drivers AS d SET is_admin=false WHERE d.id=%s", (303,))',
            'query = "SELECT drivers.is_admin FROM drivers"\nconn.execute(query)',
            'self.assertIn("is_admin", Base.metadata.tables["drivers"].c)',
        ):
            with self.subTest(source=source):
                self.assertTrue(physical_references(source))
        for source in (
            "SimpleNamespace(id=303, is_admin=True)",
            'self.assertNotIn("Driver.is_admin", source)',
            'claims = {"is_admin": True}',
            'historical_source = {"is_admin": True}',
            "sentinel = SimpleNamespace(id=303)\nsetattr(sentinel, 'is_admin', True)",
            'self.assertNotIn("SELECT d.is_admin FROM drivers AS d", source)',
            'self.assertIn("ALTER TABLE drivers DROP COLUMN is_admin", historical_upgrade_sql)',
            'sample = "Driver(id=303, is_admin=True)"',
            'sample = "SELECT is_admin FROM drivers"',
            "drivers = SimpleNamespace(is_admin=True)\nassert drivers.is_admin",
            "row = Driver(id=303)\nself.assertIsNone(getattr(row, 'is_admin', None))",
            'text("SELECT column_name FROM information_schema.columns WHERE table_name=\'drivers\' AND column_name=\'is_admin\'")',
        ):
            with self.subTest(source=source):
                self.assertEqual(physical_references(source), [])

    async def test_seeds_field_and_backoffice_with_independent_ids_and_no_flag_column(self):
        funcs = fixture_definitions(Driver=FlagFreeDriver, CompanyPrincipal=SimpleNamespace,
            BackofficeUser=SimpleNamespace, FieldRepresentative=SimpleNamespace,
            IdentityLegacyDriverMap=SimpleNamespace)
        for kind in ("BACKOFFICE", "FIELD_REPRESENTATIVE"):
            with self.subTest(kind=kind):
                db = SimpleNamespace(add=Mock(), add_all=Mock(), flush=AsyncMock())
                principal, profile, driver = await funcs["_seed_identity"](db, 7, kind, "secret")
                self.assertEqual(len({principal.id, profile.id, driver.id}), 3)
                self.assertEqual((principal.company_id, profile.company_id, driver.company_id), (7, 7, 7))
                self.assertEqual(profile.principal_id, principal.id)
                self.assertEqual(principal.principal_type, kind)
                self.assertEqual(principal.password_hash, driver.password_hash)
                self.assertFalse(hasattr(driver, "is_admin"))
                mapping = db.add.call_args.args[0]
                self.assertEqual((mapping.company_id, mapping.legacy_driver_id), (7, driver.id))
                prefix = "backoffice" if kind == "BACKOFFICE" else "field"
                self.assertEqual(getattr(mapping, prefix + "_principal_id"), principal.id)
                self.assertEqual(getattr(mapping, "backoffice_user_id" if kind == "BACKOFFICE"
                                         else "field_representative_id"), profile.id)

    def test_fixture_owner_state_requires_exact_canonical_owner_link(self):
        funcs = fixture_definitions(BackofficeFixture=lambda **kw: SimpleNamespace(**kw),
                                   DashboardRequestContext=lambda **kw: SimpleNamespace(**kw))
        principal = SimpleNamespace(id=101, company_id=7, auth_revision=3)
        profile = SimpleNamespace(id=202)
        operational = SimpleNamespace(id=303, is_active=True, password_hash="synthetic")
        for link, expected in ((None, False),
                               (SimpleNamespace(company_id=8, backoffice_user_id=202), False),
                               (SimpleNamespace(company_id=7, backoffice_user_id=999), False),
                               (SimpleNamespace(company_id=7, backoffice_user_id=202), True)):
            for flag in (True, False):
                with self.subTest(link=link, flag=flag):
                    operational.is_admin = flag  # Deliberately a namespace, never a Driver ORM row.
                    fixture = funcs["_backoffice_fixture"](principal, profile, operational, link)
                    self.assertIs(fixture.context.is_company_owner, expected)
                    self.assertEqual((fixture.context.principal_id, fixture.context.backoffice_user_id,
                                      fixture.driver_id), (101, 202, 303))
                    self.assertEqual(fixture.context.company_id, 7)

    def test_owner_selector_is_exact_tenant_profile_map_and_operational_validation(self):
        source = (TESTS / "canonical_actor_fixtures.py").read_text(encoding="utf-8-sig")
        tree = ast.parse(source)
        loader = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef)
                      and node.name == "load_company_owner_fixture")
        comparisons = {ast.unparse(node) for node in ast.walk(loader) if isinstance(node, ast.Compare)}
        for expression in (
            "CompanyPrincipal.company_id == company_id",
            "CompanyOwner.company_id == BackofficeUser.company_id",
            "CompanyOwner.backoffice_user_id == BackofficeUser.id",
            "IdentityLegacyDriverMap.backoffice_principal_id == CompanyPrincipal.id",
            "IdentityLegacyDriverMap.backoffice_user_id == BackofficeUser.id",
            "Driver.company_id == IdentityLegacyDriverMap.company_id",
            "Driver.id == IdentityLegacyDriverMap.legacy_driver_id",
            "Driver.company_id == company_id",
        ):
            self.assertIn(expression, comparisons)
        body = ast.unparse(loader)
        for active in ("Driver.is_active.is_(True)", "CompanyPrincipal.is_active.is_(True)",
                       "Company.is_active.is_(True)"):
            self.assertIn(active, body)
        self.assertIn("result.one_or_none()", body)  # Ambiguous mappings fail, no arbitrary first row.
        self.assertIn("raise AssertionError", body)  # No missing-identity fallback.
        attributes = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
        self.assertTrue({"is_admin", "classification", "commit", "rollback", "begin", "begin_nested"}.isdisjoint(attributes))


if __name__ == "__main__":
    unittest.main()
