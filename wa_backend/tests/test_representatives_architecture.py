"""Wave 1 ownership gates; run with stdlib unittest, without app/DB startup.

Missing representative packages/capabilities are deliberate failures until the
backend implementation branch lands. These checks do not prove SQL isolation;
the HTTP contract suite exercises that boundary with a real database.
"""
from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
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


class RepresentativesArchitectureTests(unittest.TestCase):
    def test_frozen_capabilities_are_catalogued_and_company_only(self):
        path = BACKEND / "domains/authorization/capabilities.py"
        spec = importlib.util.spec_from_file_location("representatives_capability_catalog", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(CAPABILITIES - module.PERMISSIONS, set(), "Missing Wave 1 capabilities")
        self.assertEqual(CAPABILITIES - module.COMPANY_ONLY, set(), "Location grants must not authorize Representative administration")

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
