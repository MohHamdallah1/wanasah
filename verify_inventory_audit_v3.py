"""Offline regression tests. Never imports application config/database or uses DATABASE_URL.

SQLite exercises actual SQLAlchemy identity-map behavior and service arithmetic.
Foreign keys/indexes are omitted ONLY in the temporary SQLite fixture; full production
PostgreSQL table/index DDL is compiled separately. This is NOT a PostgreSQL lock test.
Run from repository root: python verify_inventory_audit_v3.py
"""
from __future__ import annotations

import ast
import asyncio
import importlib
import inspect
import os
from pathlib import Path
import sys
import types
import tempfile
import unittest
from datetime import date, datetime, timedelta
from decimal import Decimal

ROOT = Path(__file__).resolve().parent
BACKEND = Path(os.environ.get("INVENTORY_AUDIT_BACKEND", str(ROOT / "wa_backend"))).resolve()
sys.path.insert(0, str(BACKEND))
# Services only needs STORAGE_BASE_PATH; do not read .env or initialize application DB.
sys.modules["config"] = types.SimpleNamespace(Config=types.SimpleNamespace(STORAGE_BASE_PATH="local_storage"))
models = importlib.import_module("models")
services = importlib.import_module("services")
schemas = importlib.import_module("schemas")
from pydantic import BaseModel, ValidationError
from sqlalchemy import create_engine, select, update, MetaData, ForeignKeyConstraint
from sqlalchemy.orm import Session, configure_mappers
from sqlalchemy.schema import CreateTable, CreateIndex
from sqlalchemy.dialects import postgresql


# Adapt synchronous in-memory ORM operations to the service await interface, excluding PG locks.
class OfflineSession:
    def __init__(self, session):
        self.session = session
        self.statements = []

    async def execute(self, stmt):
        self.statements.append(stmt)
        if "pg_advisory_xact_lock" in str(stmt):
            return None
        return self.session.execute(stmt)

    async def flush(self):
        self.session.flush()

    def add(self, obj):
        self.session.add(obj)


class AuditTests(unittest.TestCase):
    # Build a new isolated in-memory database for each test, with real mapped model columns/checks.
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        metadata = MetaData()
        for cls in (
            models.Driver, models.Shop, models.WorkSession, models.Visit,
            models.VisitItem, models.VisitReturn, models.ProductBatch,
            models.InventoryLocation, models.InventoryBalance,
            models.InventoryMovement, models.InventoryMovementImpact,
            models.StocktakeSession, models.StocktakeLine,
            models.StocktakeCountAttempt, models.StocktakeCountAttemptLine,
            models.InventoryLock,
        ):
            table = cls.__table__.to_metadata(metadata)
            for constraint in list(table.constraints):
                if isinstance(constraint, ForeignKeyConstraint):
                    table.constraints.remove(constraint)
            table.foreign_keys.clear()
            table.indexes.clear()
        metadata.create_all(self.engine)
        self.orm = Session(self.engine, expire_on_commit=False)
        self.db = OfflineSession(self.orm)
        self.now = datetime(2026, 1, 2, 12)
        self.orm.add(models.Driver(id=1, company_id=1, username="admin", full_name="Admin",
                                   password_hash="fixture", is_admin=True, is_active=True, can_allow_debt=True))
        self.orm.add(models.InventoryLocation(id=1, company_id=1, name="Warehouse", code="WH",
                                              location_type="WAREHOUSE", is_active=True))
        self.orm.flush()

    # Dispose every temporary connection even after a failed assertion.
    def tearDown(self):
        self.orm.close()
        self.engine.dispose()

    # Build an approved, independently recounted fixture using the finalized stocktake model.
    def stocktake(self, lines=((10, 8, 0, "AVAILABLE"),)):
        session = models.StocktakeSession(id=1, company_id=1, location_id=1, reference_number="COUNT-1",
                    stocktake_type="FULL_COUNT", status="APPROVED", started_by=1, approved_by=1,
                    created_at=self.now, snapshot_cutoff_at=self.now,
                    approved_at=self.now + timedelta(minutes=3))
        parent = models.StocktakeCountAttempt(id=1, company_id=1, stocktake_session_id=1,
                    attempt_number=1, counted_by=1, requires_independent_recount=True,
                    submitted_at=self.now + timedelta(minutes=1))
        latest = models.StocktakeCountAttempt(id=2, company_id=1, stocktake_session_id=1,
                    attempt_number=2, counted_by=2, authorized_by=1, recount_reason="Verify shortage",
                    recount_of_attempt_id=1, requires_independent_recount=True,
                    submitted_at=self.now + timedelta(minutes=2))
        lock = models.InventoryLock(id=1, company_id=1, stocktake_session_id=1,
                    location_id=1, created_by=1, created_at=self.now)
        self.orm.add_all([session, parent, latest, lock])
        balances, snapshots, counts = [], [], []
        for i, (expected, actual, reserved, status) in enumerate(lines, 1):
            batch = models.ProductBatch(id=i, company_id=1, product_variant_id=1,
                        batch_number=f"B{i}", expiry_date=date(2030, 1, 1), is_active=True)
            balance = models.InventoryBalance(id=i, company_id=1, location_id=1,
                        product_variant_id=1, batch_id=i, stock_status=status,
                        on_hand_quantity=expected, reserved_quantity=reserved)
            snapshot = models.StocktakeLine(id=i, company_id=1, stocktake_session_id=1,
                        product_variant_id=1, batch_id=i, stock_status=status,
                        line_origin="SNAPSHOT", expected_quantity=expected)
            count = models.StocktakeCountAttemptLine(id=i, company_id=1, stocktake_session_id=1,
                        count_attempt_id=2, stocktake_line_id=i, expected_quantity=expected,
                        actual_quantity=actual, variance_quantity=actual - expected)
            self.orm.add_all([batch, balance, snapshot, count])
            balances.append(balance); snapshots.append(snapshot); counts.append(count)
        self.orm.flush()
        return session, parent, latest, lock, balances, snapshots, counts

    # Execute the actual stocktake domain service without connecting to a project database.
    def post(self, company_id=1):
        return asyncio.run(services.post_approved_stocktake_adjustments(self.db, company_id=company_id,
            stocktake_session_id=1, stocktake_count_attempt_id=2, performed_by=1))

    # Execute the actual generic movement core with a stable inbound/outbound identity.
    def move(self, **changes):
        values = dict(company_id=1, performed_by=1, product_variant_id=1, batch_id=1,
                      quantity=2, movement_kind="PHYSICAL", reference_type="VISIT_SALE",
                      reference_id="1", idempotency_key="sale-1", source_location_id=1,
                      source_stock_status="AVAILABLE")
        values.update(changes)
        return asyncio.run(services.apply_inventory_movement(self.db, **values))

    # Seed an available stock balance for generic movement/FEFO tests.
    def stock(self, quantity=10):
        self.orm.add(models.ProductBatch(id=1, company_id=1, product_variant_id=1,
            batch_number="B", expiry_date=date(2030, 1, 1), is_active=True))
        balance = models.InventoryBalance(id=1, company_id=1, location_id=1, product_variant_id=1,
            batch_id=1, stock_status="AVAILABLE", on_hand_quantity=quantity, reserved_quantity=0)
        self.orm.add(balance); self.orm.flush()
        return balance

    def test_01_model_and_schema_compilation(self):
        configure_mappers()
        self.assertEqual(len(models.Base.metadata.tables), 49)
        for table in models.Base.metadata.sorted_tables:
            str(CreateTable(table).compile(dialect=postgresql.dialect()))
            for index in table.indexes:
                str(CreateIndex(index).compile(dialect=postgresql.dialect()))
        for cls in vars(schemas).values():
            if inspect.isclass(cls) and cls.__module__ == "schemas" and issubclass(cls, BaseModel):
                cls.model_json_schema()

    def test_02_duplicate_settlement_counts(self):
        with self.assertRaises(ValidationError):
            schemas.SettleSessionRequest(actual_cash="0", inventory_jard=[
                {"product_id": 1, "actual": 4}, {"product_id": 1, "actual": 7}])
        self.assertEqual(len(schemas.SettleSessionRequest(actual_cash="0", inventory_jard=[
            {"product_id": 1, "actual": 4}]).inventory_jard), 1)

    def test_03_clear_existing_optional_shop_fields(self):
        for name in ("owner", "mapLink"):
            self.assertEqual(getattr(schemas.EditShopDetailsRequest(**{name: "  "}), name), "")
        with self.assertRaises(ValidationError):
            schemas.EditShopDetailsRequest(owner=None)
        with self.assertRaises(ValidationError):
            schemas.EditShopDetailsRequest(owner="a\x00b")

    def test_04_movement_refreshes_stale_balance(self):
        balance = self.stock(10)
        self.orm.execute(update(models.InventoryBalance).values(on_hand_quantity=7)
                         .execution_options(synchronize_session=False))
        self.assertEqual(balance.on_hand_quantity, 10)  # identity map is genuinely stale
        self.move()
        self.assertEqual(balance.on_hand_quantity, 5)
        self.orm.flush()
        impact = self.orm.scalars(select(models.InventoryMovementImpact)).one()
        self.assertEqual((impact.on_hand_before, impact.on_hand_after), (7, 5))

    def test_05_fefo_refreshes_stale_balance(self):
        balance = self.stock(10)
        self.orm.execute(update(models.InventoryBalance).values(on_hand_quantity=3)
                         .execution_options(synchronize_session=False))
        self.assertEqual(balance.on_hand_quantity, 10)
        with self.assertRaises(services.InventoryMutationError):
            asyncio.run(services.allocate_fefo_inventory(self.db, company_id=1, location_id=1,
                product_variant_id=1, quantity=5, as_of_date=date(2026, 1, 2)))

    def test_06_debt_decision_refreshes_stale_shop(self):
        shop = models.Shop(id=1, company_id=1, name="Shop", max_debt_limit=100,
                           current_balance=10, is_active=True, is_archived=False)
        self.orm.add(shop); self.orm.flush()
        self.orm.execute(update(models.Shop).values(current_balance=90)
                         .execution_options(synchronize_session=False))
        allowed, _ = asyncio.run(services.check_debt_limits(self.db, 1, 1, 1, Decimal("20")))
        self.assertFalse(allowed)

    def test_07_count_expected_must_match_snapshot(self):
        _, _, _, _, _, _, counts = self.stocktake()
        counts[0].expected_quantity = 9; counts[0].variance_quantity = -1
        self.orm.flush()
        with self.assertRaises(services.InventoryMutationError):
            self.post()

    def test_08_live_balance_must_match_snapshot(self):
        _, _, _, _, balances, _, _ = self.stocktake()
        self.orm.execute(update(models.InventoryBalance).values(on_hand_quantity=12)
                         .execution_options(synchronize_session=False))
        with self.assertRaises(services.InventoryMutationError):
            self.post()
        self.assertEqual(balances[0].on_hand_quantity, 12)

    def test_09_zero_variance_does_not_hide_balance_drift(self):
        self.stocktake(((10, 10, 0, "AVAILABLE"),))
        self.orm.execute(update(models.InventoryBalance).values(on_hand_quantity=9)
                         .execution_options(synchronize_session=False))
        with self.assertRaises(services.InventoryMutationError):
            self.post()

    def test_10_failure_does_not_mutate_earlier_lines(self):
        _, _, _, _, balances, _, _ = self.stocktake(((10, 8, 0, "AVAILABLE"), (10, 2, 5, "AVAILABLE")))
        with self.assertRaises(services.InventoryMutationError):
            self.post()
        self.assertEqual([row.on_hand_quantity for row in balances], [10, 10])
        self.assertFalse(any(isinstance(row, models.InventoryMovement) for row in self.orm.new))

    def test_11_recount_requirement_survives_zero_variance(self):
        _, _, latest, _, _, _, _ = self.stocktake(((10, 10, 0, "AVAILABLE"),))
        latest.requires_independent_recount = False; latest.counted_by = 1
        self.orm.flush()
        with self.assertRaises(services.InventoryMutationError):
            self.post()

    def test_12_count_must_predate_approval(self):
        session, _, latest, _, _, _, _ = self.stocktake()
        latest.submitted_at = session.approved_at + timedelta(seconds=1)
        self.orm.flush()
        with self.assertRaises(services.InventoryMutationError):
            self.post()

    def test_13_recount_parent_must_be_immediately_previous(self):
        _, _, latest, _, _, _, _ = self.stocktake()
        latest.attempt_number = 4; self.orm.flush()
        with self.assertRaises(services.InventoryMutationError):
            self.post()

    def test_14_non_snapshot_positive_balance_is_rejected(self):
        self.stocktake()
        self.orm.add(models.InventoryBalance(company_id=1, location_id=1, product_variant_id=1,
            batch_id=999, stock_status="AVAILABLE", on_hand_quantity=1, reserved_quantity=0))
        self.orm.flush()
        with self.assertRaises(services.InventoryMutationError):
            self.post()

    def test_15_valid_post_and_idempotent_retry(self):
        session, _, _, lock, balances, _, _ = self.stocktake(((10, 8, 0, "AVAILABLE"), (10, 12, 0, "DAMAGED")))
        movements = self.post(); self.orm.flush()
        self.assertEqual([b.on_hand_quantity for b in balances], [8, 12])
        self.assertEqual(session.status, "POSTED")
        self.assertIsNotNone(lock.released_at)
        self.assertEqual([m.id for m in self.post()], [m.id for m in movements])
        impacts = self.orm.scalars(select(models.InventoryMovementImpact).order_by(models.InventoryMovementImpact.id)).all()
        self.assertEqual([(i.on_hand_before, i.on_hand_after) for i in impacts], [(10, 8), (10, 12)])
        self.assertEqual(len(self.orm.scalars(select(models.InventoryMovement)).all()), 2)

    def test_16_generic_replay_rejects_different_payload(self):
        balance = self.stock()
        first = self.move(); self.orm.flush()
        self.assertEqual(self.move().id, first.id)
        with self.assertRaises(services.InventoryMutationError):
            self.move(quantity=3)
        self.assertEqual(balance.on_hand_quantity, 8)

    def test_17_other_tenant_cannot_post(self):
        self.stocktake()
        with self.assertRaises(services.InventoryMutationError):
            self.post(company_id=2)

    def test_18_no_stocktake_await_inside_per_line_loops(self):
        source = inspect.getsource(services.post_approved_stocktake_adjustments)
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, (ast.For, ast.While, ast.AsyncFor)):
                self.assertFalse(any(isinstance(n, ast.Await) for n in ast.walk(node)))
        params = inspect.signature(services.apply_inventory_movement).parameters
        self.assertNotIn("ignore_stocktake_session_id", params)
        self.assertNotIn("stocktake_session_id", params)

    def test_19_posting_select_count_is_not_per_line(self):
        self.stocktake(tuple((10, 8, 0, "AVAILABLE") for _ in range(100)))
        self.post()
        selects = [s for s in self.db.statements if getattr(s, "is_select", False)]
        self.assertLessEqual(len(selects), 12)

    def test_20_reversal_cannot_masquerade_as_original_visit(self):
        self.stock(); original = self.move(); self.orm.flush()
        with self.assertRaises(services.InventoryMutationError):
            asyncio.run(services.reverse_inventory_movement(self.db, original=original,
                performed_by=1, reference_type="VISIT_SALE", reference_id="1"))

    def test_21_valid_reversal_and_retry(self):
        balance = self.stock(); original = self.move(); self.orm.flush()
        values = dict(original=original, performed_by=1, reference_type="VISIT_REVERSAL", reference_id="1")
        first = asyncio.run(services.reverse_inventory_movement(self.db, **values)); self.orm.flush()
        self.assertEqual(balance.on_hand_quantity, 10)
        self.assertEqual(asyncio.run(services.reverse_inventory_movement(self.db, **values)).id, first.id)
        self.assertEqual(balance.on_hand_quantity, 10)

    def test_22_blind_count_and_numeric_boundaries(self):
        valid = dict(product_variant_id=1, batch_id=1, stock_status="AVAILABLE", actual_quantity=0)
        schemas.StocktakeCountItem(**valid)
        for value in (True, -1, "1.2", "NaN", "Infinity", 2147483648, "1e1000000"):
            with self.assertRaises(ValidationError):
                schemas.StocktakeCountItem(**{**valid, "actual_quantity": value})
        with self.assertRaises(ValidationError):
            schemas.StocktakeCountItem(**valid, expected_quantity=10)
        with self.assertRaises(ValidationError):
            schemas.UnifiedStocktakeCountRequest(items=[valid, valid])
        schemas.UnifiedStocktakeCountRequest(items=[valid, {**valid, "stock_status": "DAMAGED"}])
        for value in (None, "", "1.0001", "NaN", "Infinity", "1000000000"):
            with self.assertRaises(ValidationError):
                schemas.SettleSessionRequest(actual_cash=value)

    def test_23_invoice_preserves_arithmetic_and_tenant_offer_isolation(self):
        offer = models.OfferRule(id=1, company_id=2, threshold_quantity=1, product_variant_id=1,
                                offer_type="free_items", bonus_quantity=99, discount_value=0, is_active=True)
        result = services.calculate_invoice(2, 1, Decimal("10"), Decimal("0.250"),
                    Decimal("16"), [offer], company_id=1, packs_per_carton=40, variant_id=1)
        self.assertEqual(result["base_amount"], Decimal("20.250"))
        self.assertEqual(result["bonus_units"], 0)
        self.assertEqual(result["final_amount"], Decimal("23.490"))
        self.assertEqual(result["final_amount"], result["base_amount"] - result["discount_applied"] + result["tax_amount"])

    def test_24_pending_valid_changes_survive_orm_refresh(self):
        balance = self.stock()
        balance.on_hand_quantity = 12  # valid change in the caller's transaction, not committed yet
        self.move()
        self.assertEqual(balance.on_hand_quantity, 10)

    def test_25_discovered_stock_creates_a_balance(self):
        session, _, _, _, balances, snapshots, _ = self.stocktake(((0, 4, 0, "AVAILABLE"),))
        snapshots[0].line_origin = "DISCOVERED"
        snapshots[0].discovered_by = 2
        snapshots[0].discovered_at = self.now + timedelta(seconds=30)
        self.orm.delete(balances[0]); self.orm.flush()
        movements = self.post(); self.orm.flush()
        balance = self.orm.scalars(select(models.InventoryBalance)).one()
        self.assertEqual(balance.on_hand_quantity, 4)
        self.assertEqual(len(movements), 1)

    def test_26_cycle_count_does_not_change_other_batches(self):
        session, _, _, lock, balances, _, _ = self.stocktake()
        session.stocktake_type = "CYCLE_COUNT"
        session.scope_product_variant_id = 1; session.scope_batch_id = 1
        lock.product_variant_id = 1; lock.batch_id = 1
        other = models.InventoryBalance(company_id=1, location_id=1, product_variant_id=1,
            batch_id=999, stock_status="AVAILABLE", on_hand_quantity=7, reserved_quantity=0)
        self.orm.add(other); self.orm.flush()
        self.post()
        self.assertEqual(balances[0].on_hand_quantity, 8)
        self.assertEqual(other.on_hand_quantity, 7)

    def test_27_same_batch_different_status_remains_distinct(self):
        _, _, _, _, balances, snapshots, _ = self.stocktake(((10, 8, 0, "AVAILABLE"), (10, 12, 0, "DAMAGED")))
        balances[1].batch_id = 1; snapshots[1].batch_id = 1
        self.orm.flush(); self.post(); self.orm.flush()
        self.assertEqual([b.on_hand_quantity for b in balances], [8, 12])
        self.assertEqual(len(self.orm.scalars(select(models.InventoryMovementImpact)).all()), 2)

    def test_28_zero_variance_posts_without_movements(self):
        session, _, _, lock, balances, _, _ = self.stocktake(((10, 10, 0, "AVAILABLE"),))
        self.assertEqual(self.post(), [])
        self.orm.flush()
        self.assertEqual(session.status, "POSTED")
        self.assertIsNotNone(lock.released_at)
        self.assertEqual(balances[0].on_hand_quantity, 10)
        self.assertEqual(self.post(), [])


    def test_29_tenant_folder_cannot_redirect_to_another_tenant(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "company_2").mkdir()
            try:
                (root / "company_1").symlink_to(root / "company_2", target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("OS does not permit creating test symlinks")
            previous = services.Config.STORAGE_BASE_PATH
            services.Config.STORAGE_BASE_PATH = directory
            try:
                with self.assertRaises(ValueError):
                    services.get_tenant_storage_path(1, "invoice.pdf")
                self.assertEqual(services.get_tenant_storage_path(2, "invoice.pdf"),
                                 str(root.resolve() / "company_2" / "invoice.pdf"))
            finally:
                services.Config.STORAGE_BASE_PATH = previous



if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(AuditTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)
    print("INVENTORY_AUDIT_V3_OFFLINE_OK")
    print("POSTGRESQL_CONCURRENCY_NOT_TESTED_BY_THIS_SCRIPT")
