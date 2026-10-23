"""Dependency-free focused acceptance for mixed visit-detail authorization."""
from __future__ import annotations

import ast
import copy
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Optional
import unittest
from unittest.mock import AsyncMock

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
SOURCE = BACKEND / "api" / "driver.py"
CAPABILITY_FREEZE = ROOT / "IDENTITY_PHASE2_CAPABILITY_FREEZE.md"
CAPABILITY_CATALOG = BACKEND / "domains" / "authorization" / "capabilities.py"
BACKOFFICE_SUBJECT = BACKEND / "domains" / "authorization" / "backoffice_subject.py"
BACKOFFICE_ACCESS = BACKEND / "domains" / "authorization" / "backoffice_access.py"


class HTTPException(Exception):
    def __init__(self, status_code: int, detail=None, headers=None):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.headers = headers


class BackofficeCapabilityAccessRejected(Exception):
    pass


@dataclass(frozen=True)
class FieldRequestContext:
    principal_id: int
    company_id: int
    representative_id: int
    auth_revision: int


@dataclass(frozen=True)
class DashboardRequestContext:
    principal_id: int
    company_id: int
    backoffice_user_id: int
    auth_revision: int
    is_company_owner: bool


AuthenticatedRequestContext = object
AsyncSession = object


def Depends(dependency):
    return SimpleNamespace(dependency=dependency)


async def get_db():
    raise AssertionError("dependency is supplied explicitly")


async def get_current_principal_context():
    raise AssertionError("dependency is supplied explicitly")


class _Column:
    def __init__(self, name: str):
        self.name = name

    def __eq__(self, other):
        return ("eq", self.name, other)


class _Relationship:
    def __init__(self, name: str):
        self.name = name

    def and_(self, expression):
        return ("and", self.name, expression)


class Visit:
    shop = _Relationship("Visit.shop")
    items = _Relationship("Visit.items")
    returns = _Relationship("Visit.returns")


class VisitItem:
    is_cancelled = _Column("VisitItem.is_cancelled")
    product_variant = _Relationship("VisitItem.product_variant")


class VisitReturn:
    is_cancelled = _Column("VisitReturn.is_cancelled")


class _Loader:
    def __init__(self, kind: str, target):
        self.kind = kind
        self.target = target
        self.joined_target = None

    def joinedload(self, target):
        self.joined_target = target
        return self


class _Statement:
    def __init__(self, model):
        self.model = model
        self.loader_options = ()
        self.filters = {}

    def options(self, *options):
        self.loader_options = options
        return self

    def filter_by(self, **filters):
        self.filters.update(filters)
        return self


def select(model):
    return _Statement(model)


def joinedload(target):
    return _Loader("joinedload", target)


def selectinload(target):
    return _Loader("selectinload", target)


class _Result:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _DB:
    def __init__(self, value):
        self.value = value
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        return _Result(self.value)


def _route_node() -> ast.AsyncFunctionDef:
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    return next(
        node for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "get_visit_details"
    )


def _load_route():
    node = copy.deepcopy(_route_node())
    node.decorator_list = []
    namespace = {
        "AsyncSession": AsyncSession,
        "Depends": Depends,
        "HTTPException": HTTPException,
        "Optional": Optional,
        "AuthenticatedRequestContext": AuthenticatedRequestContext,
        "DashboardRequestContext": DashboardRequestContext,
        "FieldRequestContext": FieldRequestContext,
        "BackofficeCapabilityAccessRejected": BackofficeCapabilityAccessRejected,
        "get_db": get_db,
        "get_current_principal_context": get_current_principal_context,
        "get_current_field_legacy_driver": AsyncMock(),
        "get_current_backoffice_capability_access": AsyncMock(),
        "get_current_field_capability_access": AsyncMock(),
        "require_field_capability": lambda code: AsyncMock(),
        "select": select,
        "joinedload": joinedload,
        "selectinload": selectinload,
        "Visit": Visit,
        "VisitItem": VisitItem,
        "VisitReturn": VisitReturn,
    }
    module = ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[]))
    exec(compile(module, str(SOURCE), "exec"), namespace)
    return namespace


class DriverMixedVisitSourceContractTests(unittest.TestCase):
    def setUp(self):
        self.source = SOURCE.read_text(encoding="utf-8")
        self.node = _route_node()
        self.route = ast.unparse(self.node)

    def test_frozen_capability_and_owner_authority_evidence(self):
        freeze = CAPABILITY_FREEZE.read_text(encoding="utf-8")
        catalog = CAPABILITY_CATALOG.read_text(encoding="utf-8")
        subject = BACKOFFICE_SUBJECT.read_text(encoding="utf-8")
        access = BACKOFFICE_ACCESS.read_text(encoding="utf-8")
        self.assertIn("Freeze `visit.read` for Backoffice access.", freeze)
        self.assertIn("Backoffice access requires `visit.read` plus tenant/object visibility.", freeze)
        self.assertIn("'visit.read'", catalog)
        company_only = catalog.split("COMPANY_ONLY", 1)[1]
        self.assertIn("'visit.read'", company_only)
        self.assertIn("if context.is_company_owner:", subject)
        self.assertIn("is_company_owner=True", subject)
        self.assertIn("if self.subject.is_company_owner:", access)

    def test_runtime_has_zero_legacy_mixed_authority_symbols(self):
        self.assertNotIn("get_current_driver", self.source)
        self.assertNotIn(".is_admin", self.source)
        for forbidden in (
            "current_driver.company_id",
            "legacy_actor.company_id",
            "current_driver.id",
        ):
            self.assertNotIn(forbidden, self.route)
        self.assertIn("Depends(get_current_principal_context)", self.route)

    def test_route_http_and_eager_loading_contract_is_preserved(self):
        decorator = self.node.decorator_list[0]
        self.assertEqual(decorator.func.attr, "get")
        self.assertEqual(ast.literal_eval(decorator.args[0]), "/visits/{visit_id}")
        keywords = {item.arg: ast.unparse(item.value) for item in decorator.keywords}
        self.assertEqual(keywords["response_model"], "VisitDetailsResponse")
        self.assertEqual(keywords["status_code"], "200")
        self.assertIn("joinedload(Visit.shop)", self.route)
        self.assertIn(
            "selectinload(Visit.items.and_(VisitItem.is_cancelled == False)).joinedload(VisitItem.product_variant)",
            self.route,
        )
        self.assertIn(
            "selectinload(Visit.returns.and_(VisitReturn.is_cancelled == False))",
            self.route,
        )
        executes = [
            part for part in ast.walk(self.node)
            if isinstance(part, ast.Call)
            and isinstance(part.func, ast.Attribute)
            and isinstance(part.func.value, ast.Name)
            and part.func.value.id == "db"
            and part.func.attr == "execute"
        ]
        self.assertEqual(len(executes), 1)

    def test_dual_channel_authority_is_explicit_and_exact(self):
        self.assertIn("isinstance(current, FieldRequestContext)", self.route)
        self.assertIn("get_current_field_legacy_driver(current=current, db=db)", self.route)
        self.assertIn("field_driver_id = legacy_actor.id", self.route)
        self.assertIn("company_id = current.company_id", self.route)
        self.assertIn("isinstance(current, DashboardRequestContext)", self.route)
        self.assertIn("get_current_backoffice_capability_access(current=current, db=db)", self.route)
        self.assertIn("await access.require('visit.read')", self.route)
        self.assertIn("company_id = access.company_id", self.route)
        self.assertNotIn("is_company_owner", self.route)


class DriverMixedVisitExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_field_reads_own_visit_and_legacy_is_admin_has_zero_effect(self):
        context = FieldRequestContext(1101, 7, 2202, 13)
        for flag in (False, True):
            with self.subTest(legacy_is_admin=flag):
                namespace = _load_route()
                visit = SimpleNamespace(id=501, driver_id=3303)
                db = _DB(visit)
                namespace["get_current_field_legacy_driver"].return_value = SimpleNamespace(
                    id=3303, company_id=999, is_admin=flag
                )
                response = await namespace["get_visit_details"](501, db=db, current=context)
                self.assertIs(response, visit)
                namespace["get_current_field_legacy_driver"].assert_awaited_once_with(
                    current=context, db=db
                )
                namespace["get_current_backoffice_capability_access"].assert_not_awaited()
                self.assertEqual(len(db.statements), 1)
                self.assertEqual(db.statements[0].filters, {"company_id": 7, "id": 501})

    async def test_field_cannot_read_another_driver_visit(self):
        namespace = _load_route()
        context = FieldRequestContext(1101, 7, 2202, 13)
        namespace["get_current_field_legacy_driver"].return_value = SimpleNamespace(
            id=3303, is_admin=True
        )
        db = _DB(SimpleNamespace(id=501, driver_id=4404))
        with self.assertRaises(HTTPException) as failure:
            await namespace["get_visit_details"](501, db=db, current=context)
        self.assertEqual(failure.exception.status_code, 403)
        self.assertEqual(
            failure.exception.detail,
            "مرفوض أمنياً: غير مصرح لك بالاطلاع على فواتير المناديب الآخرين.",
        )

    async def test_cross_company_visit_fails_closed_with_existing_404(self):
        namespace = _load_route()
        context = FieldRequestContext(1101, 7, 2202, 13)
        namespace["get_current_field_legacy_driver"].return_value = SimpleNamespace(id=3303)
        db = _DB(None)
        with self.assertRaises(HTTPException) as failure:
            await namespace["get_visit_details"](9999, db=db, current=context)
        self.assertEqual(failure.exception.status_code, 404)
        self.assertEqual(failure.exception.detail, "عذراً، الزيارة المطلوبة غير موجودة.")
        self.assertEqual(db.statements[0].filters, {"company_id": 7, "id": 9999})

    async def test_backoffice_visit_read_allows_tenant_visit_without_legacy_driver_load(self):
        namespace = _load_route()
        context = DashboardRequestContext(4404, 7, 5505, 13, False)
        access = SimpleNamespace(company_id=7, require=AsyncMock())
        namespace["get_current_backoffice_capability_access"].return_value = access
        visit = SimpleNamespace(id=501, driver_id=3303)
        db = _DB(visit)
        response = await namespace["get_visit_details"](501, db=db, current=context)
        self.assertIs(response, visit)
        namespace["get_current_backoffice_capability_access"].assert_awaited_once_with(
            current=context, db=db
        )
        access.require.assert_awaited_once_with("visit.read")
        namespace["get_current_field_legacy_driver"].assert_not_awaited()
        self.assertEqual(db.statements[0].filters, {"company_id": 7, "id": 501})

    async def test_backoffice_missing_capability_is_denied_before_query(self):
        namespace = _load_route()
        context = DashboardRequestContext(4404, 7, 5505, 13, False)
        access = SimpleNamespace(
            company_id=7,
            require=AsyncMock(side_effect=BackofficeCapabilityAccessRejected()),
        )
        namespace["get_current_backoffice_capability_access"].return_value = access
        db = _DB(SimpleNamespace(id=501, driver_id=3303))
        with self.assertRaises(HTTPException) as failure:
            await namespace["get_visit_details"](501, db=db, current=context)
        self.assertEqual(failure.exception.status_code, 403)
        self.assertEqual(failure.exception.detail, "Authorization denied.")
        self.assertEqual(db.statements, [])
        namespace["get_current_field_legacy_driver"].assert_not_awaited()

    async def test_company_owner_uses_canonical_backoffice_path_only(self):
        namespace = _load_route()
        owner = DashboardRequestContext(6606, 7, 7707, 13, True)
        access = SimpleNamespace(company_id=7, require=AsyncMock())
        namespace["get_current_backoffice_capability_access"].return_value = access
        visit = SimpleNamespace(id=501, driver_id=8808)
        db = _DB(visit)
        response = await namespace["get_visit_details"](501, db=db, current=owner)
        self.assertIs(response, visit)
        namespace["get_current_backoffice_capability_access"].assert_awaited_once_with(
            current=owner, db=db
        )
        access.require.assert_awaited_once_with("visit.read")
        namespace["get_current_field_legacy_driver"].assert_not_awaited()

    async def test_cancelled_item_filters_remain_on_query_loader_options(self):
        namespace = _load_route()
        context = FieldRequestContext(1101, 7, 2202, 13)
        namespace["get_current_field_legacy_driver"].return_value = SimpleNamespace(id=3303)
        db = _DB(SimpleNamespace(id=501, driver_id=3303))
        await namespace["get_visit_details"](501, db=db, current=context)
        options = db.statements[0].loader_options
        self.assertEqual(len(options), 3)
        self.assertEqual(options[0].kind, "joinedload")
        self.assertEqual(options[1].kind, "selectinload")
        self.assertEqual(options[1].target, ("and", "Visit.items", ("eq", "VisitItem.is_cancelled", False)))
        self.assertIs(options[1].joined_target, VisitItem.product_variant)
        self.assertEqual(options[2].kind, "selectinload")
        self.assertEqual(options[2].target, ("and", "Visit.returns", ("eq", "VisitReturn.is_cancelled", False)))


if __name__ == "__main__":
    unittest.main()
