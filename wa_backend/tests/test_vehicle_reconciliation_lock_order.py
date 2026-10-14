from __future__ import annotations

import ast
import asyncio
import copy
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock


BACKEND = Path(__file__).resolve().parents[1]
SOURCE = BACKEND / "api/warehouse/stocktake.py"


def _function(tree: ast.Module, name: str) -> ast.AsyncFunctionDef:
    return next(
        node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == name
    )


def _source(node: ast.AST, source: str) -> str:
    segment = ast.get_source_segment(source, node)
    assert segment is not None
    return segment


def _call_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


class Field:
    def __init__(self, model: str, name: str):
        self.model = model
        self.name = name


class StocktakeSessionModel:
    location_id = Field("StocktakeSession", "location_id")
    stocktake_type = Field("StocktakeSession", "stocktake_type")
    related_work_session_id = Field("StocktakeSession", "related_work_session_id")


class WorkSessionModel:
    id = Field("WorkSession", "id")


class Query:
    def __init__(self, *entities):
        self.entities = entities
        self.filters = {}
        self.locked = False

    def filter_by(self, **kwargs):
        self.filters.update(kwargs)
        return self

    def with_for_update(self):
        self.locked = True
        return self


class Result:
    def __init__(self, *, one=None, scalar=None):
        self._one = one
        self._scalar = scalar

    def one_or_none(self):
        return self._one

    def scalar_one_or_none(self):
        return self._scalar


class HTTPException(Exception):
    def __init__(self, status_code: int, detail=None):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class InventoryMutationError(Exception):
    pass


class IntegrityError(Exception):
    pass


def _select(*entities):
    return Query(*entities)


def _compile_approve(namespace: dict):
    source = SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(source, feature_version=(3, 11))
    nodes = [
        copy.deepcopy(_function(tree, "_probe_stocktake_location_id")),
        copy.deepcopy(_function(tree, "approve_stocktake_session")),
    ]
    for node in nodes:
        node.decorator_list = []
        node.returns = None
        for arg in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs):
            arg.annotation = None
        node.args.defaults = [ast.Constant(None) for _ in node.args.defaults]
        node.args.kw_defaults = [
            ast.Constant(None) if default is not None else None
            for default in node.args.kw_defaults
        ]
    module = ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[]))
    exec(compile(module, str(SOURCE), "exec"), namespace)
    return namespace["approve_stocktake_session"]


class FakeDB:
    def __init__(self, events: list[str], *, probe, locked_work_session=55):
        self.events = events
        self.probe = probe
        self.locked_work_session = locked_work_session
        self.queries: list[Query] = []
        self.rollback = AsyncMock()
        self.commit = AsyncMock()
        self.flush = AsyncMock()

    async def execute(self, query: Query):
        self.queries.append(query)
        names = tuple(
            (entity.model, entity.name) if isinstance(entity, Field) else (str(entity), "")
            for entity in query.entities
        )
        if names == (
            ("StocktakeSession", "location_id"),
            ("StocktakeSession", "stocktake_type"),
            ("StocktakeSession", "related_work_session_id"),
        ):
            self.events.append("scalar-probe")
            return Result(one=self.probe)
        if names == (("WorkSession", "id"),):
            self.events.append("work-session-lock")
            return Result(scalar=self.locked_work_session)
        raise AssertionError(f"Unexpected query: {names}")

    def add(self, value):
        raise AssertionError(f"No mutation expected before drift rejection: {value!r}")


def _approval_case(*, probe, locked_session, locked_work_session=55):
    events: list[str] = []
    db = FakeDB(events, probe=probe, locked_work_session=locked_work_session)

    async def guard(*args, **kwargs):
        events.append("location-guard")

    async def load_locked(*args, **kwargs):
        events.append("stocktake-for-update")
        return locked_session

    namespace = {
        "asyncio": asyncio,
        "bcrypt": SimpleNamespace(checkpw=Mock(return_value=True)),
        "HTTPException": HTTPException,
        "InventoryMutationError": InventoryMutationError,
        "IntegrityError": IntegrityError,
        "StocktakeSession": StocktakeSessionModel,
        "WorkSession": WorkSessionModel,
        "select": _select,
        "_require_stocktake_capability": AsyncMock(),
        "acquire_inventory_location_guard": AsyncMock(side_effect=guard),
        "_load_stocktake_session": AsyncMock(side_effect=load_locked),
        "_latest_stocktake_attempt": AsyncMock(),
        "_utc_naive_now": Mock(),
        "post_approved_stocktake_adjustments": AsyncMock(),
        "logger": Mock(),
    }
    approve = _compile_approve(namespace)
    payload = SimpleNamespace(password="ok", count_attempt_id=77, notes=None)
    access = SimpleNamespace(company_id=7)
    actor = SimpleNamespace(id=9004, password_hash="hash")
    return SimpleNamespace(
        events=events,
        db=db,
        ns=namespace,
        approve=approve,
        payload=payload,
        access=access,
        actor=actor,
    )


class VehicleReconciliationLockOrderTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = SOURCE.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source, feature_version=(3, 11))
        cls.loader = _function(cls.tree, "_load_stocktake_session")
        cls.probe = _function(cls.tree, "_probe_stocktake_location_id")
        cls.start = _function(cls.tree, "start_unified_stocktake")
        cls.approve = _function(cls.tree, "approve_stocktake_session")
        cls.loader_source = _source(cls.loader, cls.source)
        cls.probe_source = _source(cls.probe, cls.source)
        cls.start_source = _source(cls.start, cls.source)
        cls.approve_source = _source(cls.approve, cls.source)

    def test_vehicle_recon_start_locks_work_session_before_location_guard(self):
        validate = self.start_source.index("await validate_vehicle_recon_work_session(")
        guard = self.start_source.index("await acquire_inventory_location_guard(")
        self.assertLess(validate, guard)
        self.assertIn("work_session_id=payload.related_work_session_id", self.start_source)

    def test_vehicle_recon_start_revalidates_strict_custody_after_guard(self):
        guard = self.start_source.index("await acquire_inventory_location_guard(")
        strict = self.start_source.index("await resolve_vehicle_custody_location_id(")
        effects = self.start_source.index("existing_recon_id = (")
        self.assertLess(guard, strict)
        self.assertLess(strict, effects)
        self.assertIn("expected_location_id=int(payload.location_id)", self.start_source)

    def test_warehouse_start_does_not_require_work_session(self):
        vehicle_if = next(
            node for node in ast.walk(self.start)
            if isinstance(node, ast.If)
            and ast.unparse(node.test) == "payload.stocktake_type == 'VEHICLE_RECON'"
            and any(
                isinstance(child, ast.Call)
                and _call_name(child) == "validate_vehicle_recon_work_session"
                for child in ast.walk(node)
            )
        )
        self.assertIsNotNone(vehicle_if)
        self.assertEqual(self.start_source.count("validate_vehicle_recon_work_session("), 1)

    def test_approval_uses_three_scalar_columns_and_not_stocktake_entity(self):
        probe_select = next(
            call for call in ast.walk(self.probe)
            if isinstance(call, ast.Call)
            and _call_name(call) == "select"
            and len(call.args) == 3
        )
        self.assertEqual(
            [
                (arg.value.id, arg.attr)
                for arg in probe_select.args
                if isinstance(arg, ast.Attribute) and isinstance(arg.value, ast.Name)
            ],
            [
                ("StocktakeSession", "location_id"),
                ("StocktakeSession", "stocktake_type"),
                ("StocktakeSession", "related_work_session_id"),
            ],
        )
        self.assertNotIn("with_for_update", self.probe_source)
        self.assertNotIn("select(StocktakeSession)", self.probe_source)
        self.assertIn(
            "probe = await _probe_stocktake_location_id(db, company_id, session_id)",
            self.approve_source,
        )
        self.assertNotIn("lock_vehicle_recon_work_session", self.loader_source)

    def test_vehicle_recon_approval_order_is_scalar_work_guard_stocktake_lock(self):
        probe = self.approve_source.index(
            "probe = await _probe_stocktake_location_id(db, company_id, session_id)"
        )
        work_lock = self.approve_source.index("select(WorkSession.id).filter_by(")
        guard = self.approve_source.index("await acquire_inventory_location_guard(")
        reload = self.approve_source.index(
            "session = await _load_stocktake_session(db, company_id, session_id, for_update=True)"
        )
        approved = self.approve_source.index("session.status = 'APPROVED'")
        self.assertLess(probe, work_lock)
        self.assertLess(work_lock, guard)
        self.assertLess(guard, reload)
        self.assertLess(reload, approved)

    async def test_adversarial_probe_a_locked_reload_b_observes_b_and_rejects_drift(self):
        locked = SimpleNamespace(
            id=66,
            location_id=12,
            stocktake_type="VEHICLE_RECON",
            related_work_session_id=55,
            status="PENDING_REVIEW",
        )
        case = _approval_case(
            probe=(11, "VEHICLE_RECON", 55),
            locked_session=locked,
        )
        with self.assertRaises(HTTPException) as caught:
            await case.approve(66, case.payload, case.db, case.access, case.actor)
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(
            case.events,
            ["scalar-probe", "work-session-lock", "location-guard", "stocktake-for-update"],
        )
        probe_query, work_query = case.db.queries
        self.assertFalse(probe_query.locked)
        self.assertTrue(work_query.locked)
        case.ns["_load_stocktake_session"].assert_awaited_once_with(
            case.db, 7, 66, for_update=True
        )
        case.ns["post_approved_stocktake_adjustments"].assert_not_awaited()
        case.db.flush.assert_not_awaited()
        case.db.commit.assert_not_awaited()
        case.db.rollback.assert_awaited_once()
        self.assertEqual(locked.status, "PENDING_REVIEW")

    async def test_missing_related_work_session_stops_before_guard(self):
        locked = SimpleNamespace(
            id=66, location_id=11, stocktake_type="VEHICLE_RECON",
            related_work_session_id=None, status="PENDING_REVIEW",
        )
        case = _approval_case(
            probe=(11, "VEHICLE_RECON", None),
            locked_session=locked,
        )
        with self.assertRaises(HTTPException) as caught:
            await case.approve(66, case.payload, case.db, case.access, case.actor)
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(case.events, ["scalar-probe"])
        case.ns["acquire_inventory_location_guard"].assert_not_awaited()
        case.ns["_load_stocktake_session"].assert_not_awaited()
        case.ns["post_approved_stocktake_adjustments"].assert_not_awaited()

    async def test_warehouse_approval_does_not_lock_work_session(self):
        locked = SimpleNamespace(
            id=66,
            location_id=12,
            stocktake_type="FULL_COUNT",
            related_work_session_id=None,
            status="PENDING_REVIEW",
        )
        case = _approval_case(
            probe=(11, "FULL_COUNT", None),
            locked_session=locked,
        )
        with self.assertRaises(HTTPException) as caught:
            await case.approve(66, case.payload, case.db, case.access, case.actor)
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(
            case.events,
            ["scalar-probe", "location-guard", "stocktake-for-update"],
        )
        self.assertEqual(len(case.db.queries), 1)
        case.ns["post_approved_stocktake_adjustments"].assert_not_awaited()

    def test_no_vehicle_row_lock_is_introduced(self):
        for function in (self.start, self.approve):
            for call in (node for node in ast.walk(function) if isinstance(node, ast.Call)):
                if _call_name(call) != "select":
                    continue
                self.assertFalse(
                    any(isinstance(arg, ast.Name) and arg.id == "Vehicle" for arg in call.args),
                    function.name,
                )

    def test_approval_delegates_posting_once_and_preserves_rollback_contract(self):
        self.assertEqual(self.approve_source.count("post_approved_stocktake_adjustments("), 1)
        self.assertGreaterEqual(self.approve_source.count("await db.rollback()"), 4)
        posting = self.approve_source.index("movements = await post_approved_stocktake_adjustments(")
        success_commit = self.approve_source.index("await db.commit()", posting)
        self.assertLess(posting, success_commit)
        handlers = [node for node in self.approve.body if isinstance(node, ast.Try)][0].handlers
        self.assertEqual(len(handlers), 4)
        for handler in handlers:
            body = "\n".join(ast.unparse(statement) for statement in handler.body)
            self.assertIn("await db.rollback()", body)


if __name__ == "__main__":
    unittest.main()
