from __future__ import annotations

import ast
import inspect
import unittest
from dataclasses import FrozenInstanceError, fields
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import MultipleResultsFound

from domains.auth_sessions.context import DashboardRequestContext, FieldRequestContext
from domains.authorization import field_subject as module
from domains.authorization.field_subject import (
    FieldAuthorizationSubject,
    FieldAuthorizationSubjectRejected,
    resolve_field_authorization_subject,
)


def field_context(**changes):
    values = dict(principal_id=101, representative_id=202, company_id=7, auth_revision=3)
    values.update(changes)
    return FieldRequestContext(**values)


def bridge(**changes):
    values = dict(
        company_id=7,
        field_principal_id=101,
        field_representative_id=202,
        legacy_driver_id=303,
    )
    values.update(changes)
    return SimpleNamespace(**values)


def database(row=None):
    result = Mock()
    result.one_or_none.return_value = row
    return SimpleNamespace(execute=AsyncMock(return_value=result))


class CanonicalFieldAuthorizationSubjectTests(unittest.IsolatedAsyncioTestCase):
    async def test_exact_bridge_success_preserves_independent_ids_and_is_frozen(self):
        db = database(bridge())
        subject = await resolve_field_authorization_subject(db, field_context())
        self.assertEqual(subject, FieldAuthorizationSubject(101, 202, 7, 303))
        self.assertEqual(
            [item.name for item in fields(subject)],
            ["principal_id", "representative_id", "company_id", "legacy_driver_id"],
        )
        with self.assertRaises(FrozenInstanceError):
            subject.legacy_driver_id = 404
        db.execute.assert_awaited_once()
        db.execute.return_value.one_or_none.assert_called_once_with()

    async def test_coincidentally_equal_ids_do_not_create_an_alias_requirement(self):
        subject = await resolve_field_authorization_subject(
            database(bridge(field_principal_id=11, field_representative_id=11, legacy_driver_id=11)),
            field_context(principal_id=11, representative_id=11),
        )
        self.assertEqual(subject, FieldAuthorizationSubject(11, 11, 7, 11))

    async def test_missing_bridge_rejected(self):
        with self.assertRaises(FieldAuthorizationSubjectRejected):
            await resolve_field_authorization_subject(database(), field_context())

    async def test_multiple_bridges_rejected(self):
        db = database()
        db.execute.return_value.one_or_none.side_effect = MultipleResultsFound()
        with self.assertRaises(FieldAuthorizationSubjectRejected):
            await resolve_field_authorization_subject(db, field_context())

    async def test_wrong_company_rejected(self):
        with self.assertRaises(FieldAuthorizationSubjectRejected):
            await resolve_field_authorization_subject(database(bridge(company_id=8)), field_context())

    async def test_principal_mismatch_rejected(self):
        with self.assertRaises(FieldAuthorizationSubjectRejected):
            await resolve_field_authorization_subject(
                database(bridge(field_principal_id=999)), field_context()
            )

    async def test_representative_mismatch_rejected(self):
        with self.assertRaises(FieldAuthorizationSubjectRejected):
            await resolve_field_authorization_subject(
                database(bridge(field_representative_id=999)), field_context()
            )

    async def test_only_field_context_accepted_before_any_lookup(self):
        dashboard = DashboardRequestContext(
            principal_id=101, company_id=7, backoffice_user_id=202,
            auth_revision=3, is_company_owner=False,
        )
        for context in (dashboard, None, vars(field_context()), SimpleNamespace(**vars(field_context()))):
            with self.subTest(context_type=type(context)):
                db = database(bridge())
                with self.assertRaises(FieldAuthorizationSubjectRejected):
                    await resolve_field_authorization_subject(db, context)
                db.execute.assert_not_awaited()

    async def test_each_context_id_is_independently_a_strict_positive_integer(self):
        for name in ("company_id", "principal_id", "representative_id"):
            for bad in (0, -1, True, False, "101", 101.0, None):
                with self.subTest(name=name, bad=bad):
                    db = database(bridge())
                    with self.assertRaises(FieldAuthorizationSubjectRejected):
                        await resolve_field_authorization_subject(db, field_context(**{name: bad}))
                    db.execute.assert_not_awaited()

    async def test_malformed_returned_canonical_ids_rejected(self):
        for name, valid in (
            ("company_id", 7), ("field_principal_id", 101), ("field_representative_id", 202)
        ):
            for bad in (0, -1, True, str(valid), float(valid), None):
                with self.subTest(name=name, bad=bad):
                    with self.assertRaises(FieldAuthorizationSubjectRejected):
                        await resolve_field_authorization_subject(
                            database(bridge(**{name: bad})), field_context()
                        )
        # bool compares equal to integer 1 but must still fail closed.
        with self.assertRaises(FieldAuthorizationSubjectRejected):
            await resolve_field_authorization_subject(
                database(bridge(company_id=True)), field_context(company_id=1)
            )

    async def test_malformed_legacy_id_rejected(self):
        for bad in (0, -1, True, False, "303", 303.0, None):
            with self.subTest(bad=bad):
                with self.assertRaises(FieldAuthorizationSubjectRejected):
                    await resolve_field_authorization_subject(
                        database(bridge(legacy_driver_id=bad)), field_context()
                    )

    async def test_lookup_uses_all_three_exact_identity_predicates_and_only_bridge(self):
        db = database(bridge())
        await resolve_field_authorization_subject(db, field_context())
        statement = db.execute.await_args.args[0]
        self.assertEqual(
            [table.name for table in statement.get_final_froms()], ["identity_legacy_driver_map"]
        )
        self.assertEqual(
            [column.name for column in statement.selected_columns],
            ["company_id", "field_principal_id", "field_representative_id", "legacy_driver_id"],
        )
        self.assertEqual(
            [(predicate.left.name, predicate.right.value) for predicate in statement.whereclause.clauses],
            [("company_id", 7), ("field_principal_id", 101), ("field_representative_id", 202)],
        )
        compiled = statement.compile(dialect=postgresql.dialect())
        self.assertEqual(list(compiled.params.values()), [7, 101, 202])
        self.assertNotIn("classification", str(compiled))

    def test_no_legacy_identity_authority_transport_or_transaction_mutation(self):
        tree = ast.parse(inspect.getsource(module))
        imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        attributes = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
        self.assertTrue(imports.isdisjoint({"Driver", "RefreshToken", "FastAPI", "HTTPException"}))
        self.assertNotIn("Driver", names)
        self.assertTrue(attributes.isdisjoint({
            "is_admin", "classification", "role", "roles", "capabilities",
            "commit", "rollback", "begin", "add", "delete", "flush",
        }))
        self.assertFalse(any(
            isinstance(node, ast.ImportFrom) and (node.module or "").startswith("fastapi")
            for node in ast.walk(tree)
        ))


if __name__ == "__main__":
    unittest.main()
