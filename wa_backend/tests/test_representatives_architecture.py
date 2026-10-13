"""Wave 1 and Wave 2 ownership/security gates, without app/DB startup.

The catalog migration gate uses installed Alembic in PostgreSQL offline mode;
the other source gates need only stdlib unittest.

Missing representative packages/capabilities are deliberate failures until the
backend implementation branch lands. These checks do not prove SQL isolation;
the HTTP contract suite exercises that boundary with a real database.
"""
from __future__ import annotations

import ast
import importlib.util
import io
from pathlib import Path
import re
import sys
import unittest


BACKEND = Path(__file__).resolve().parents[1]
CAPABILITIES = frozenset({
    "representative.read", "representative.manage",
    "representative.credentials.reset",
})
PACKAGES = (BACKEND / "api/representatives", BACKEND / "domains/representatives")
PERSONA_FLAGS = frozenset({
    "is_admin", "is_superuser", "is_manager", "is_supervisor", "is_owner",
    "allow_admin", "legacy_full_authority",
})


def representative_sources():
    paths = []
    for package in PACKAGES:
        if not (package / "__init__.py").is_file():
            raise AssertionError(f"Wave 1 implementation missing: {package.relative_to(BACKEND)}")
        paths.extend(sorted(package.rglob("*.py")))
    return [(path, ast.parse(path.read_text(encoding="utf-8-sig"))) for path in paths]


def imported_modules(tree, path):
    package = path.parent.relative_to(BACKEND).parts
    def resolve(module, level):
        prefix = package[:len(package) - level + 1] if level else ()
        return ".".join((*prefix, *module.split("."))) if module else ".".join(prefix)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = resolve(node.module or "", node.level)
            yield module
            yield from (f"{module}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Call) and isinstance(node.func, (ast.Name, ast.Attribute)):
            name = node.func.id if isinstance(node.func, ast.Name) else node.func.attr
            if name in {"import_module", "__import__"} and node.args:
                if isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                    module = node.args[0].value
                    level = len(module) - len(module.lstrip("."))
                    yield resolve(module.lstrip("."), level)


def reachable_domain_sources(entry):
    """Follow Representative-owned helpers without freezing private function names."""
    pending, seen = [entry], set()
    while pending:
        path = pending.pop()
        if path in seen:
            continue
        seen.add(path)
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        yield path, tree
        for module in imported_modules(tree, path):
            while module.startswith("domains.representatives"):
                candidate = BACKEND.joinpath(*module.split(".")).with_suffix(".py")
                if candidate.is_file():
                    pending.append(candidate)
                    break
                module = module.rpartition(".")[0]


def qualified_calls(tree, path):
    package = path.parent.relative_to(BACKEND).parts
    aliases = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            aliases.update({item.asname or item.name.split(".")[0]: item.name if item.asname else item.name.split(".")[0]
                            for item in node.names})
        elif isinstance(node, ast.ImportFrom):
            prefix = package[:len(package) - node.level + 1] if node.level else ()
            module = ".".join((*prefix, *(node.module or "").split("."))).strip(".")
            aliases.update({item.asname or item.name: module + "." + item.name for item in node.names})
    def qualified(node):
        if isinstance(node, ast.Name):
            return aliases.get(node.id, node.id)
        if isinstance(node, ast.Attribute):
            return qualified(node.value) + "." + node.attr
        return ""
    return {qualified(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)}


class RepresentativesArchitectureTests(unittest.TestCase):
    def test_frozen_capabilities_are_catalogued_and_company_only(self):
        path = BACKEND / "domains/authorization/capabilities.py"
        spec = importlib.util.spec_from_file_location("representatives_capability_catalog", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(CAPABILITIES - module.PERMISSIONS, set(), "Missing Wave 1 capabilities")
        self.assertEqual(CAPABILITIES - module.COMPANY_ONLY, set(), "Location grants must not authorize Representative administration")

    def test_migration_chain_additively_inserts_frozen_permission_catalog(self):
        from alembic.config import Config
        from alembic.migration import MigrationContext
        from alembic.operations import Operations
        from alembic.script import ScriptDirectory

        if str(BACKEND) not in sys.path:
            sys.path.insert(0, str(BACKEND))
        config = Config()
        config.set_main_option("script_location", str(BACKEND / "alembic"))
        scripts = ScriptDirectory.from_config(config)
        self.assertEqual(len(scripts.get_heads()), 1, "Permission migration must belong to the current single-head Alembic chain")
        witnesses = []
        for migration in scripts.walk_revisions():
            tree = ast.parse(Path(migration.path).read_text(encoding="utf-8-sig"))
            strings = [node.value for node in ast.walk(tree)
                       if isinstance(node, ast.Constant) and isinstance(node.value, str)]
            if not all(any(code in value for value in strings) for code in CAPABILITIES):
                continue
            output = io.StringIO()
            context = MigrationContext.configure(dialect_name="postgresql", opts={
                "as_sql": True, "literal_binds": True, "output_buffer": output,
            })
            with Operations.context(context):
                migration.module.upgrade()
            # Inspect executed upgrade SQL, not comments, downgrade literals or
            # an unconnected migration file. The migrated DB assertion below
            # remains the actual persisted-state proof.
            sql = re.sub(r"--[^\n]*|/\*.*?\*/", "", output.getvalue(), flags=re.S)
            permission_table = r'(?:"?public"?\.)?"?permissions"?(?=\s|\()'
            inserts = re.findall(r"\bINSERT\s+INTO\s+" + permission_table + r"[^;]*", sql, flags=re.I)
            inserted = {code for code in CAPABILITIES
                        if any("'" + code + "'" in statement for statement in inserts)}
            if inserted != CAPABILITIES:
                continue
            self.assertNotRegex(sql, re.compile(
                r"\b(?:UPDATE|DELETE\s+FROM|TRUNCATE(?:\s+TABLE)?|DROP\s+TABLE)\s+" + permission_table,
                re.I,
            ), "Catalog additions must preserve existing Permission rows")
            for statement in inserts:
                self.assertNotRegex(statement, re.compile(r"\bDO\s+UPDATE\b", re.I), "Catalog conflicts must not rewrite existing rows")
            witnesses.append(migration.revision)
        self.assertTrue(witnesses, "Current Alembic chain lacks an additive upgrade inserting all three Representative Permission codes; the fixture must not repair it")

    def test_representative_packages_do_not_reach_into_operational_routers(self):
        violations = []
        for path, tree in representative_sources():
            for module in imported_modules(tree, path):
                if any(module == forbidden or module.startswith(forbidden + ".")
                       for forbidden in ("api.driver", "api.dispatch", "wa_backend.api.driver", "wa_backend.api.dispatch")):
                    violations.append((str(path.relative_to(BACKEND)), module))
        self.assertEqual(violations, [], "Consume public domain contracts, not Driver/Dispatch HTTP business internals")
        main = ast.parse((BACKEND / "main.py").read_text(encoding="utf-8-sig"))
        imports = {}
        for node in main.body:
            if isinstance(node, ast.Import):
                imports.update({alias.asname or alias.name.split(".")[0]: alias.name if alias.asname else alias.name.split(".")[0]
                                for alias in node.names})
            elif isinstance(node, ast.ImportFrom):
                imports.update({alias.asname or alias.name: f"{node.module}.{alias.name}" for alias in node.names})
        def qualified(node):
            if isinstance(node, ast.Name):
                return imports.get(node.id, node.id)
            if isinstance(node, ast.Attribute):
                return qualified(node.value) + "." + node.attr
            return ""
        mounted = {qualified(node.args[0]) for node in ast.walk(main)
                   if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                   and node.func.attr == "include_router" and node.args}
        self.assertIn("api.representatives.router", mounted, "The public HTTP application must mount the dedicated router")

    def test_no_generic_persona_authority_or_legacy_authentication_in_packages(self):
        violations = []
        forbidden_names = PERSONA_FLAGS | {"get_current_driver", "get_current_admin", "InventoryAccess", "subject_from_legacy_driver"}
        for path, tree in representative_sources():
            for node in ast.walk(tree):
                # Comments/docstrings/negative-proof text do not count as authority.
                name = node.id if isinstance(node, ast.Name) else node.attr if isinstance(node, ast.Attribute) else None
                if isinstance(node, ast.alias):
                    name = node.name.rsplit(".", 1)[-1]
                elif isinstance(node, ast.arg):
                    name = node.arg
                elif isinstance(node, ast.keyword):
                    name = node.arg
                if name in forbidden_names:
                    violations.append((str(path.relative_to(BACKEND)), node.lineno, name))
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {"getattr", "setattr", "hasattr"}:
                    if len(node.args) > 1 and isinstance(node.args[1], ast.Constant) and node.args[1].value in PERSONA_FLAGS:
                        violations.append((str(path.relative_to(BACKEND)), node.lineno, node.args[1].value))
        self.assertEqual(violations, [], "Canonical is_company_owner is allowed; generic persona shortcuts are not")

    def test_wave2_delegates_credential_policy_and_session_invalidation_to_identity(self):
        revoke = "domains.auth_sessions.invalidation.revoke_principal_refresh_sessions"
        for module in ("lifecycle", "credentials"):
            calls = set()
            for path, tree in reachable_domain_sources(BACKEND / f"domains/representatives/{module}.py"):
                imports = set(imported_modules(tree, path))
                self.assertFalse(any(value == "bcrypt" or value.startswith("bcrypt.") for value in imports),
                                 "Representatives must delegate password mechanisms to Identity")
                calls.update(qualified_calls(tree, path))
            with self.subTest(module=module):
                self.assertIn(revoke, calls, "Wave 2 must consume canonical principal/session invalidation")
                if module == "credentials":
                    self.assertIn("domains.identity.credentials.hash_company_password", calls)

    def test_canonical_identity_password_policy_enforces_utf8_byte_boundary(self):
        # Execute the actual pure Identity policy definitions. Keep lazy hashing/
        # fingerprint bodies but omit imports so validation needs no bcrypt/DB
        # installation. No policy is reimplemented in the test.
        path = BACKEND / "domains/identity/credentials.py"
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        definitions = []
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                definitions.append(node)
            elif isinstance(node, ast.ImportFrom) and node.module == "__future__":
                definitions.append(node)
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                try:
                    ast.literal_eval(node.value)
                except (ValueError, TypeError):
                    continue
                definitions.append(node)
        namespace = {"__name__": "representative_identity_policy_probe"}
        exec(compile(ast.Module(body=definitions, type_ignores=[]), str(path), "exec"), namespace)
        validate = namespace["validate_company_password"]  # Public Identity API.
        for password in ("abcd1234", "a" * 72, "م" * 36, "😀" * 18):
            with self.subTest(characters=len(password), utf8_bytes=len(password.encode("utf-8"))):
                self.assertEqual(validate(password), password)
        for password in ("a" * 7, "م" * 7, "a" * 73, "م" * 37, "😀" * 19):
            with self.subTest(characters=len(password), utf8_bytes=len(password.encode("utf-8"))):
                with self.assertRaises(ValueError):
                    validate(password)

    def test_driver_and_dispatch_do_not_implement_representative_crud(self):
        violations = []
        for name in ("driver", "dispatch"):
            path = BACKEND / f"api/{name}.py"
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
            constructors = {"FieldRepresentative", "CompanyPrincipal", "BackofficeUser"}
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                called = node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else None
                if called in constructors:
                    violations.append((name, node.lineno, called))
                if isinstance(node.func, ast.Attribute) and node.func.attr in {"get", "post", "patch", "put", "delete", "api_route"}:
                    if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                        if any(part in {"representative", "representatives"} for part in node.args[0].value.split("/")):
                            violations.append((name, node.lineno, node.args[0].value))
        self.assertEqual(violations, [], "Representative CRUD belongs to its dedicated router/domain")


if __name__ == "__main__":
    unittest.main()
