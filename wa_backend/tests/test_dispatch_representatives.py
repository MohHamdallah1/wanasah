"""Real SQLite identity/query checks plus PostgreSQL lock compilation.

Query and validation expressions come from the seven runtime call sites. The
small synthetic schema intentionally permits malformed links to test denial;
it is not a production schema, RLS, or concurrency acceptance gate.
"""
from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
import unittest

from sqlalchemy import Column, MetaData, Table, create_engine, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session, aliased

from domains.dispatch_representatives import has_canonical_field_identity
from domains.identity.migration.models import IdentityLegacyDriverMap
from domains.identity.models import CompanyPrincipal, FieldRepresentative
from models import Driver


SOURCE = Path(__file__).resolve().parents[1] / "api" / "dispatch.py"
TREE = ast.parse(SOURCE.read_text(encoding="utf-8"))
SITES = (
    ("dispatch_init", "drivers", None),
    ("dispatch_route", "driver", False),
    ("update_route_status", "driver_row", False),
    ("update_route_status", "driver_rows", False),
    ("undo_end_work", "driver", False),
    ("add_shortages", "drivers", False),
    ("add_shortages", "auto_drivers", True),
)
CASES = (
    ("field-only", {}, True),
    ("dual-split legacy false", {"bridge": {"classification": "DUAL_SPLIT"}}, True),
    ("dual-split legacy true", {"bridge": {"classification": "DUAL_SPLIT"},
                               "driver": {"is_admin": True}}, True),
    ("label is not authority", {"bridge": {"classification": "UNTRUSTED_LABEL"}}, True),
    ("backoffice-only legacy false", {"bridge": {"classification": "BACKOFFICE_ONLY",
        "field_principal_id": None, "field_representative_id": None}}, False),
    ("missing bridge", {"bridge": None}, False),
    ("inactive principal", {"principal": {"is_active": False}}, False),
    ("wrong principal type", {"principal": {"principal_type": "BACKOFFICE"}}, False),
    ("missing principal", {"principal": None}, False),
    ("wrong principal id", {"principal": {"id": 999}}, False),
    ("missing representative", {"representative": None}, False),
    ("wrong representative id", {"representative": {"id": 999}}, False),
    ("wrong profile principal", {"representative": {"principal_id": 999}}, False),
    ("wrong profile type", {"representative": {"principal_type": "BACKOFFICE"}}, False),
    ("wrong mapped principal", {"bridge": {"field_principal_id": 999}}, False),
    ("wrong mapped representative", {"bridge": {"field_representative_id": 999}}, False),
    ("wrong legacy locator", {"bridge": {"legacy_driver_id": 999}}, False),
    ("foreign bridge", {"bridge": {"company_id": 8}}, False),
    ("foreign profile", {"representative": {"company_id": 8}}, False),
    ("foreign principal", {"principal": {"company_id": 8}}, False),
)


def function(name):
    return next(node for node in TREE.body if isinstance(node, ast.AsyncFunctionDef) and node.name == name)


def evaluate(expression, **context):
    namespace = dict(select=select, Driver=Driver,
                     has_canonical_field_identity=has_canonical_field_identity,
                     company_id=7, payload=SimpleNamespace(driver_id=303),
                     session=SimpleNamespace(driver_id=303), snap_driver_id=303,
                     driver_ids_to_lock=[303], driver_ids=[303], auto_driver_ids=[303])
    namespace.update(context)
    return eval(compile(ast.Expression(expression), str(SOURCE), "eval"), namespace)


def query_expression(owner, variable):
    candidates = []
    for node in ast.walk(function(owner)):
        if not isinstance(node, ast.Assign) or not any(
            isinstance(target, ast.Name) and target.id == variable for target in node.targets
        ):
            continue
        for call in ast.walk(node.value):
            if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                    and isinstance(call.func.value, ast.Name) and call.func.value.id == "db"
                    and call.func.attr == "execute"):
                continue
            if any(isinstance(part, ast.Call) and isinstance(part.func, ast.Name)
                   and part.func.id == "select" and part.args
                   and isinstance(part.args[0], ast.Name) and part.args[0].id == "Driver"
                   for part in ast.walk(call.args[0])):
                candidates.append(call.args[0])
    assert len(candidates) == 1, (owner, variable)
    return candidates[0]


def comprehension(owner, variable):
    return next(node.value for node in ast.walk(function(owner))
                if isinstance(node, ast.Assign) and isinstance(node.value, (ast.SetComp, ast.DictComp))
                and any(isinstance(target, ast.Name) and target.id == variable for target in node.targets))


def rejection_condition(identity_flag):
    return next(node.test for node in ast.walk(function("update_route_status"))
                if isinstance(node, ast.If) and any(isinstance(part, ast.Name) and part.id == identity_flag
                                                   for part in ast.walk(node.test)))


class DispatchRepresentativeTests(unittest.TestCase):
    def setUp(self):
        metadata = MetaData()
        definitions = {
            Driver: [column.name for column in Driver.__table__.columns],
            IdentityLegacyDriverMap: ["company_id", "legacy_driver_id", "field_principal_id",
                                     "field_representative_id", "classification"],
            FieldRepresentative: ["company_id", "id", "principal_id", "principal_type"],
            CompanyPrincipal: ["company_id", "id", "principal_type", "is_active"],
        }
        self.tables = {model: Table(model.__tablename__, metadata, *(
            Column(name, model.__table__.c[name].type) for name in names
        )) for model, names in definitions.items()}
        self.engine = create_engine("sqlite://")
        self.connection = self.engine.connect()
        metadata.create_all(self.connection)
        self.session = Session(bind=self.connection)

    def tearDown(self):
        self.session.close()
        self.connection.close()
        self.engine.dispose()

    def seed(self, changes=None):
        self.session.expunge_all()
        for table in self.tables.values():
            self.connection.execute(table.delete())
        self.insert_identity(changes or {})

    def insert_identity(self, changes):
        defaults = {
            "driver": (Driver, dict(id=303, company_id=7, is_active=True,
                                    is_admin=False, full_name="Operational 303")),
            "bridge": (IdentityLegacyDriverMap, dict(company_id=7, legacy_driver_id=303,
                field_principal_id=101, field_representative_id=202, classification="FIELD_ONLY")),
            "representative": (FieldRepresentative, dict(company_id=7, id=202,
                principal_id=101, principal_type="FIELD_REPRESENTATIVE")),
            "principal": (CompanyPrincipal, dict(company_id=7, id=101,
                principal_type="FIELD_REPRESENTATIVE", is_active=True)),
        }
        for name, (model, values) in defaults.items():
            update = changes.get(name, {})
            if update is not None:
                self.connection.execute(self.tables[model].insert(), {**values, **update})

    def test_exact_canonical_identity_matrix_with_independent_ids(self):
        for name, changes, expected in CASES:
            with self.subTest(case=name):
                self.seed(changes)
                actual = self.connection.execute(select(has_canonical_field_identity(
                    company_id=7, legacy_driver_id=303,
                ))).scalar_one()
                self.assertIs(actual, expected)

    def accepted_ids(self, owner, variable):
        rows = self.session.execute(evaluate(query_expression(owner, variable))).all()
        if variable == "driver_row":
            driver, identity = rows[0] if rows else (None, False)
            rejected = evaluate(rejection_condition("driver_has_field_identity"),
                                driver=driver, driver_has_field_identity=identity)
            return set() if rejected else {driver.id}
        if variable == "driver_rows":
            driver_map = evaluate(comprehension(owner, "driver_map"), driver_rows=rows)
            field_ids = evaluate(comprehension(owner, "field_driver_ids"), driver_rows=rows)
            target = driver_map.get(303)
            rejected = evaluate(rejection_condition("field_driver_ids"),
                                target_driver=target, requested_driver_id=303, field_driver_ids=field_ids)
            return set() if rejected else {target.id}
        if owner == "add_shortages" and variable == "drivers":
            return evaluate(comprehension(owner, "valid"), drivers=rows)
        return {row[0].id for row in rows}

    def test_all_seven_runtime_query_and_validation_sites_use_canonical_identity(self):
        cases = (*CASES, ("inactive operational driver", {"driver": {"is_active": False}}, False),
                 ("foreign operational driver", {"driver": {"company_id": 8}}, False),
                 ("missing operational driver", {"driver": None}, False))
        for owner, variable, _ in SITES:
            for name, changes, expected in cases:
                with self.subTest(site=(owner, variable), case=name):
                    self.seed(changes)
                    self.assertEqual(self.accepted_ids(owner, variable), {303} if expected else set())

    def test_init_lists_only_active_company_field_rows_in_legacy_id_order(self):
        self.seed()
        for driver_id, active, principal_active, company, mapping in (
            (404, True, True, 7, True), (505, True, True, 7, False),
            (606, False, True, 7, True), (707, True, False, 7, True),
            (808, True, True, 8, True),
        ):
            self.insert_identity({
                "driver": dict(id=driver_id, company_id=company, is_active=active,
                               is_admin=driver_id == 404),
                "bridge": dict(company_id=company, legacy_driver_id=driver_id,
                               field_principal_id=driver_id + 1000 if mapping else None,
                               field_representative_id=driver_id + 2000 if mapping else None,
                               classification="DUAL_SPLIT" if driver_id == 404 else "BACKOFFICE_ONLY"),
                "representative": dict(company_id=company, id=driver_id + 2000,
                                       principal_id=driver_id + 1000) if mapping else None,
                "principal": dict(company_id=company, id=driver_id + 1000, is_active=principal_active),
            })
        drivers = self.session.execute(evaluate(query_expression("dispatch_init", "drivers"))).scalars().all()
        self.assertEqual([driver.id for driver in drivers], [303, 404])

    def test_identity_projection_keeps_locked_nonfield_rows_for_historical_operations(self):
        self.seed({"bridge": None})
        for owner, variable in (("update_route_status", "driver_row"),
                                ("update_route_status", "driver_rows"), ("add_shortages", "drivers")):
            with self.subTest(site=(owner, variable)):
                rows = self.session.execute(evaluate(query_expression(owner, variable))).all()
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0][0].id, 303)
                self.assertIs(rows[0][1], False)

    def test_postgresql_row_lock_modes_and_driver_order_are_preserved(self):
        for owner, variable, read in SITES:
            with self.subTest(site=(owner, variable)):
                query = evaluate(query_expression(owner, variable))
                self.assertEqual([table.name for table in query.get_final_froms()], ["drivers"])
                self.assertEqual([str(item) for item in query._order_by_clauses], ["drivers.id ASC"])
                sql = str(query.compile(dialect=postgresql.dialect()))
                if read is None:
                    self.assertIsNone(query._for_update_arg)
                    self.assertNotIn("FOR UPDATE", sql)
                else:
                    self.assertEqual(query._for_update_arg.read, read)
                    self.assertFalse(query._for_update_arg.nowait)
                    self.assertFalse(query._for_update_arg.skip_locked)
                    self.assertIsNone(query._for_update_arg.of)
                    self.assertTrue(sql.endswith("FOR SHARE" if read else "FOR UPDATE"))

    def test_predicate_composes_with_aliased_driver_projection_where_and_pagination(self):
        self.seed()
        driver = aliased(Driver)
        predicate = has_canonical_field_identity(company_id=7, legacy_driver_id=driver.id)
        query = select(driver.id, predicate).where(driver.company_id == 7, predicate).order_by(driver.id).limit(1)
        self.assertEqual(self.session.execute(query).all(), [(303, True)])
        self.assertEqual(self.session.execute(query.offset(1)).all(), [])
        sql = str(query.compile(dialect=postgresql.dialect()))
        self.assertIn("drivers_1.id", sql)
        self.assertNotIn("classification", sql)
        self.assertNotIn("is_admin", sql)


if __name__ == "__main__":
    unittest.main()
