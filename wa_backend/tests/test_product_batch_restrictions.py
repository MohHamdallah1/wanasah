"""Read-contract acceptance on synthetic SQLite data; no production DB or workers.

Execute the real SQLAlchemy read statements and existing permission predicates.
These fixtures deliberately omit PostgreSQL RLS/FKs, which remain deployment gates.
"""
import ast
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import Column, MetaData, Table, create_engine
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from domains.inventory_batch_restrictions import BatchRestrictionSummary, load_batch_restrictions
from domains.inventory_batch_restrictions.contracts import CurrentDispositionReason, DispositionCounts
from models import InventoryBalance, Permission, ProductBatch, UserLocationAccess, UserRole, role_permissions


class ReadSession:
    def __init__(self, connection):
        self.connection = connection
        self.permission_reads = []
        self.aggregate_reads = []

    async def scalar(self, statement):
        self.permission_reads.append(statement)
        return self.connection.scalar(statement)

    async def execute(self, statement):
        self.aggregate_reads.append(statement)
        return self.connection.execute(statement)


@pytest.fixture
def store():
    metadata = MetaData()
    def table(source, names):
        return Table(source.name, metadata, *(Column(name, source.c[name].type) for name in names.split()))
    tables = {
        "batches": table(ProductBatch.__table__, "id company_id product_variant_id disposition disposition_reason disposition_revision is_active"),
        "balances": table(InventoryBalance.__table__, "id company_id location_id product_variant_id batch_id stock_status on_hand_quantity reserved_quantity"),
        "permissions": table(Permission.__table__, "id code"),
        "roles": table(UserRole.__table__, "company_id driver_id role_id"),
        "locations": table(UserLocationAccess.__table__, "company_id driver_id role_id location_id"),
        "grants": table(role_permissions, "company_id role_id permission_id"),
    }
    engine = create_engine("sqlite://")
    with engine.connect() as connection:
        metadata.create_all(connection)
        connection.execute(tables["permissions"].insert(), [dict(id=1, code="inventory.read"), dict(id=2, code="catalog.read")])
        yield SimpleNamespace(db=ReadSession(connection), connection=connection, tables=tables)
    engine.dispose()


def grant(store, *, company=1, driver=7, permission=1, location=None):
    assignment = dict(company_id=company, driver_id=driver, role_id=20)
    table = store.tables["roles"] if location is None else store.tables["locations"]
    if location is not None:
        assignment["location_id"] = location
    store.connection.execute(table.insert(), assignment)
    store.connection.execute(store.tables["grants"].insert(), dict(company_id=company, role_id=20, permission_id=permission))


def batch(store, batch_id, variant=101, *, company=1, disposition="QUARANTINED", reason=None, active=True):
    store.connection.execute(store.tables["batches"].insert(), dict(
        id=batch_id, company_id=company, product_variant_id=variant, disposition=disposition,
        disposition_reason=reason, disposition_revision=3, is_active=active,
    ))


def balance(store, batch_id, amount, *, company=1, variant=101, location=11, status="AVAILABLE", reserved="0"):
    store.connection.execute(store.tables["balances"].insert(), dict(
        company_id=company, product_variant_id=variant, location_id=location, batch_id=batch_id,
        stock_status=status, on_hand_quantity=Decimal(amount), reserved_quantity=Decimal(reserved),
    ))


def actor(*, company=1, driver=7, admin=False):
    return SimpleNamespace(company_id=company, id=driver, is_admin=admin)


@pytest.mark.asyncio
async def test_counts_are_batches_not_balances_and_quantity_includes_all_locations_and_buckets(store):
    grant(store)
    batch(store, 1, reason="بانتظار نتائج الفحص")
    batch(store, 2, disposition="BLOCKED", reason="Packaging investigation", active=False)
    batch(store, 3, disposition="RECALLED")
    batch(store, 4, disposition="RELEASED", reason="No longer restricted")
    batch(store, 5, active=False)  # No balances; still current restricted metadata.
    balance(store, 1, "10.123456", reserved="2")
    balance(store, 1, "1.000001", location=12, status="BLOCKED")
    balance(store, 1, "3", location=12, status="QUARANTINED")
    balance(store, 2, "5", location=12, status="DAMAGED")
    balance(store, 4, "999", status="RECALLED")  # Portion status is a separate authority.
    result = (await load_batch_restrictions(store.db, actor=actor(), variant_ids=[101]))[101]
    assert result.affected_batch_count == 4
    assert result.counts_by_disposition.model_dump() == {"QUARANTINED": 2, "BLOCKED": 1, "RECALLED": 1}
    assert result.affected_on_hand_quantity == "19.123457"
    assert result.quantity_unit == "BASE_STOCK_UNIT"
    reason = result.representative_reason
    assert reason.batch_id == 1 and reason.disposition == "QUARANTINED" and reason.disposition_revision == 3
    assert reason.disposition_reason == "بانتظار نتائج الفحص"
    assert reason.selection == "LOWEST_BATCH_ID_WITH_CURRENT_REASON"
    assert len(store.db.permission_reads) == len(store.db.aggregate_reads) == 1


@pytest.mark.asyncio
async def test_tenant_variant_predicates_exclude_foreign_batches_and_inconsistent_balances(store):
    grant(store)
    batch(store, 1, reason="Company one")
    batch(store, 2, company=2, disposition="RECALLED", reason="SECRET")
    batch(store, 3, variant=999, reason="Other variant")
    balance(store, 1, "2")
    balance(store, 2, "800", company=2)
    balance(store, 1, "900", company=2)  # Deliberately malformed synthetic FK data.
    balance(store, 1, "700", variant=999)
    result = await load_batch_restrictions(store.db, actor=actor(), variant_ids=[101, 102])
    assert set(result) == {101, 102}
    assert result[101].affected_batch_count == 1
    assert result[101].affected_on_hand_quantity == "2.000000"
    assert "SECRET" not in result[101].model_dump_json()
    assert result[102].affected_batch_count == 0 and result[102].representative_reason is None


@pytest.mark.asyncio
async def test_current_reason_selection_skips_nulls_and_never_fakes_a_reason(store):
    grant(store)
    batch(store, 1)
    batch(store, 9, reason="Current reason of batch nine")
    batch(store, 4, reason="Current reason of batch four")
    batch(store, 2, variant=102, disposition="RECALLED")
    result = await load_batch_restrictions(store.db, actor=actor(), variant_ids=[101, 102])
    assert result[101].representative_reason.batch_id == 4
    assert result[101].representative_reason.disposition_reason == "Current reason of batch four"
    assert result[102].affected_batch_count == 1 and result[102].representative_reason is None
    assert result[102].affected_on_hand_quantity == "0.000000"


@pytest.mark.asyncio
@pytest.mark.parametrize("authority", ["none", "location", "catalog", "foreign_company", "foreign_driver"])
async def test_insufficient_grants_return_unavailable_not_zero_and_do_not_read_inventory(store, authority):
    if authority == "location": grant(store, location=11)
    if authority == "catalog": grant(store, permission=2)
    if authority == "foreign_company": grant(store, company=2)
    if authority == "foreign_driver": grant(store, driver=8)
    batch(store, 1, reason="Private stock reason")
    result = await load_batch_restrictions(store.db, actor=actor(), variant_ids=[101, 102])
    assert result == {101: None, 102: None}
    assert len(store.db.permission_reads) == 1 and not store.db.aggregate_reads


@pytest.mark.asyncio
async def test_company_admin_uses_existing_authority_and_permission_revocation_is_not_cached(store):
    batch(store, 1)
    assert (await load_batch_restrictions(store.db, actor=actor(admin=True), variant_ids=[101]))[101].affected_batch_count == 1
    assert (await load_batch_restrictions(store.db, actor=actor(), variant_ids=[101]))[101] is None
    grant(store)
    assert (await load_batch_restrictions(store.db, actor=actor(), variant_ids=[101]))[101].affected_batch_count == 1
    store.connection.execute(store.tables["grants"].delete())
    assert (await load_batch_restrictions(store.db, actor=actor(), variant_ids=[101]))[101] is None


@pytest.mark.asyncio
async def test_empty_page_performs_no_reads_and_200_variants_still_use_one_aggregate(store):
    assert await load_batch_restrictions(store.db, actor=actor(), variant_ids=[]) == {}
    assert not store.db.permission_reads and not store.db.aggregate_reads
    result = await load_batch_restrictions(store.db, actor=actor(admin=True), variant_ids=list(range(1, 201)))
    assert len(result) == 200
    assert all(item.affected_batch_count == 0 for item in result.values())
    assert len(store.db.permission_reads) == len(store.db.aggregate_reads) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("ids", [[0], [-1], [True], ["101"], list(range(1, 202))])
async def test_unbounded_or_invalid_variant_scope_fails_before_reads(store, ids):
    with pytest.raises(ValueError):
        await load_batch_restrictions(store.db, actor=actor(), variant_ids=ids)
    assert not store.db.permission_reads and not store.db.aggregate_reads


@pytest.mark.asyncio
@pytest.mark.parametrize("company", [None, 0, -1, True, "1"])
async def test_ambiguous_tenant_context_fails_closed(store, company):
    with pytest.raises(ValueError):
        await load_batch_restrictions(store.db, actor=actor(company=company), variant_ids=[101])
    assert not store.db.permission_reads and not store.db.aggregate_reads


def test_contract_preserves_exact_aggregate_strings_beyond_single_balance_capacity():
    summary = BatchRestrictionSummary(affected_batch_count=2,
        affected_on_hand_quantity="199999999999999.999998", counts_by_disposition=DispositionCounts(BLOCKED=2))
    assert summary.model_dump(mode="json")["affected_on_hand_quantity"] == "199999999999999.999998"
    with pytest.raises(ValidationError):
        BatchRestrictionSummary(affected_batch_count=1, affected_on_hand_quantity="0.000000", counts_by_disposition=DispositionCounts())
    with pytest.raises(ValidationError):
        BatchRestrictionSummary(affected_batch_count=0, affected_on_hand_quantity=1.25, counts_by_disposition=DispositionCounts())
    with pytest.raises(ValidationError):
        BatchRestrictionSummary(affected_batch_count=1, affected_on_hand_quantity="0.000000",
            counts_by_disposition=DispositionCounts(QUARANTINED=1), representative_reason=CurrentDispositionReason(
                batch_id=1, disposition="BLOCKED", disposition_revision=2, disposition_reason="Unrelated reason"))


@pytest.mark.asyncio
async def test_postgresql_statement_is_tenant_bounded_and_read_only(store):
    await load_batch_restrictions(store.db, actor=actor(admin=True), variant_ids=[101, 102])
    sql = str(store.db.aggregate_reads[0].compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "product_batches.company_id = 1" in sql and "inventory_balances.company_id = 1" in sql
    assert "product_batches.product_variant_id IN (101, 102)" in sql
    assert "inventory_balances.product_variant_id IN (101, 102)" in sql
    assert "inventory_balances.product_variant_id = restricted_batches.product_variant_id" in sql
    assert "reason_rank = 1" in sql
    assert all(keyword not in sql for keyword in ("FOR UPDATE", "INSERT ", "UPDATE ", "DELETE "))


@pytest.mark.asyncio
async def test_read_loader_never_autoflushes_pending_orm_objects(store):
    with Session(bind=store.connection) as session:
        pending = ProductBatch(company_id=1, product_variant_id=101, batch_number="Unflushed",
            disposition="RECALLED", disposition_reason="Pending, not committed evidence")
        session.add(pending)
        db = ReadSession(session)
        result = await load_batch_restrictions(db, actor=actor(admin=True), variant_ids=[101])
        assert result[101].affected_batch_count == 0
        assert pending in session.new and pending.id is None


def test_actual_products_payload_adds_read_evidence_without_relabeling_lifecycle():
    source = Path(__file__).resolve().parents[1] / "api" / "simple_products.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    route = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "list_simple_products")
    gate = route.body[0].value.value
    assert gate.func.id == "_require" and gate.args[2].value == "catalog.read"
    calls = [node for node in ast.walk(route) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "load_batch_restrictions"]
    assert len(calls) == 1
    payload = next(node for node in ast.walk(route) if isinstance(node, ast.Dict)
        and any(isinstance(key, ast.Constant) and key.value == "batch_restrictions" for key in node.keys))
    variant = SimpleNamespace(id=101, name="SKU", sku="SKU", packs_per_carton=1, base_uom_id=1,
        package_uses_base_barcode=False, version=1, lot_control_mode="NONE", expiry_control_mode="NONE",
        lifecycle_status="ACTIVE", operational_hold="NONE")
    summary = BatchRestrictionSummary(affected_batch_count=1, affected_on_hand_quantity="0.000000",
        counts_by_disposition=DispositionCounts(RECALLED=1))
    context = dict(variant=variant, product=SimpleNamespace(id=10, name="Master"), shape=None,
        package_price=None, unit_price=None, currency="JOD", unit_barcode=None, package_barcode=None,
        compatible={101: True}, batch_restrictions={101: summary},
        status_reasons={101: "مراجعة التسعير"})
    result = eval(compile(ast.Expression(payload), str(source), "eval"), context)
    assert result["id"] == 101 and result["product_id"] == 10
    assert result["batch_restrictions"] == summary.model_dump(mode="json")
    assert result["lifecycle_status"] == "ACTIVE" and result["operational_hold"] == "NONE"
    assert result["status_reason"] == "مراجعة التسعير"
    context["batch_restrictions"] = {101: None}
    assert eval(compile(ast.Expression(payload), str(source), "eval"), context)["batch_restrictions"] is None
