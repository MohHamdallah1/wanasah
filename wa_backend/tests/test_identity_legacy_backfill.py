"""Focused secret-free mapping/model checks; no database or package installation."""
import importlib.util
import io
from pathlib import Path
import sys
import unittest

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.schema import CreateTable
from sqlalchemy.dialects import postgresql

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from domains.identity.migration.errors import BackfillError
from domains.identity.migration.mapping import fingerprint, load_mapping, validate_document
from domains.identity.migration.models import IdentityLegacyDriverMap


def document():
    facts = {"company_id": 1, "legacy_driver_id": 10, "username": "owner", "full_name": "Owner",
             "phone_number": None, "is_active": True, "is_admin": True, "can_allow_debt": False,
             "max_debt_limit": "0.000", "backoffice_grants": {"company_roles": 0, "location_grants": 0},
             "field_references": dict.fromkeys(("work_sessions", "dispatch_routes", "visits", "shortage_requests", "expected_receivers"), 0),
             "reference_fingerprint": fingerprint({})}
    return {"format_version": 1, "reviewed": True, "entries": [{"company_id": 1, "legacy_driver_id": 10,
            "classification": "BACKOFFICE_ONLY", "expected_source": facts, "source_fingerprint": fingerprint(facts),
            "backoffice_username": "owner", "field_username": None, "company_owner": True}]}


class MappingTests(unittest.TestCase):
    def test_complete_reviewed_format_and_fingerprint(self):
        self.assertEqual(validate_document(document())[0].key, (1, 10))
        facts = document()["entries"][0]["expected_source"]
        self.assertEqual(fingerprint(facts), fingerprint(dict(reversed(list(facts.items())))))

    def test_review_unknown_fields_and_stale_digest_fail_closed(self):
        for change in (lambda d: d.update(reviewed=False),
                       lambda d: d["entries"][0].update(password_hash="forbidden"),
                       lambda d: d["entries"][0]["expected_source"].update(password_hash="forbidden"),
                       lambda d: d["entries"][0]["expected_source"].update(username="changed"),
                       lambda d: d["entries"][0].update(company_owner=None)):
            candidate = document()
            change(candidate)
            with self.assertRaises(BackfillError):
                validate_document(candidate)

    def test_owner_and_dual_usernames(self):
        for kind, owner, field in (("FIELD_ONLY", True, "owner"), ("DUAL_SPLIT", True, None),
                                   ("DUAL_SPLIT", True, "owner"), ("BACKOFFICE_ONLY", False, None)):
            candidate = document()
            candidate["entries"][0].update(classification=kind, company_owner=owner, field_username=field)
            with self.assertRaises(BackfillError):
                validate_document(candidate)
        valid = document()
        valid["entries"][0].update(classification="DUAL_SPLIT", field_username="field")
        self.assertEqual(len(validate_document(valid)), 1)

    def test_duplicate_json_keys_rejected_without_echo(self):
        from unittest.mock import Mock
        path = Mock()
        path.read_text.return_value = '{"reviewed":true,"reviewed":false}'
        with self.assertRaisesRegex(BackfillError, "DUPLICATE_JSON_KEY"):
            load_mapping(path)


class SchemaTests(unittest.TestCase):
    def test_bridge_exact_columns_and_tenant_keys(self):
        table = IdentityLegacyDriverMap.__table__
        self.assertEqual(list(table.c.keys()), ["company_id", "legacy_driver_id", "classification",
            "backoffice_principal_id", "backoffice_user_id", "field_principal_id", "field_representative_id", "created_at"])
        self.assertEqual(list(table.primary_key.columns.keys()), ["company_id", "legacy_driver_id"])
        self.assertEqual(len(table.foreign_key_constraints), 5)
        self.assertTrue(all(list(fk.column_keys)[0] == "company_id" for fk in table.foreign_key_constraints))
        ddl = str(CreateTable(table).compile(dialect=postgresql.dialect()))
        self.assertNotIn("SERIAL", ddl)
        self.assertNotIn("principal_actor_default", ddl)

    def test_additive_offline_migration_and_safe_downgrade(self):
        path = Path(__file__).resolve().parents[1] / "alembic/versions/a4d2e7c9b630_identity_legacy_driver_bridge.py"
        spec = importlib.util.spec_from_file_location("identity_bridge_revision", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(module.down_revision, "e9c4b1a7d620")
        import os
        from unittest.mock import patch
        buffer = io.StringIO()
        context = MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": buffer})
        with Operations.context(context), patch.dict(os.environ, {"DATABASE_URL": "postgresql://restricted@localhost/test"}):
            module.upgrade()
            module.downgrade()
        ddl = buffer.getvalue()
        self.assertEqual(ddl.count("CREATE TABLE"), 1)
        self.assertIn("AS RESTRICTIVE", ddl)
        self.assertIn("FORCE ROW LEVEL SECURITY", ddl)
        self.assertIn("Cannot downgrade populated identity bridge", ddl)
        self.assertNotIn("ALTER TABLE drivers", ddl)


if __name__ == "__main__":
    unittest.main()
