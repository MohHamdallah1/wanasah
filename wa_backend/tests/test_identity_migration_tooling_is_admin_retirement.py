"""Focused post-cutover identity migration/evidence acceptance."""
from __future__ import annotations

import copy
from pathlib import Path
import unittest

from domains.identity.migration import evidence, mapping
from domains.identity.migration.errors import BackfillError


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_PATH = ROOT / "domains" / "identity" / "migration" / "evidence.py"
MAPPING_PATH = ROOT / "domains" / "identity" / "migration" / "mapping.py"


class _Result:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class _Cursor:
    def __init__(self, rows):
        self._rows = rows
        self.query = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query):
        self.query = query

    def fetchall(self):
        return list(self._rows)


class _CanonicalConnection:
    def __init__(self, rows, *, tables_present=True):
        self.rows = rows
        self.tables_present = tables_present
        self.executed = []
        self.cursor_instance = None

    def execute(self, query, params=None):
        self.executed.append((query, params))
        if query.startswith("SELECT to_regclass"):
            if self.tables_present:
                return _Result(tuple(object() for _ in evidence._CANONICAL_TABLES))
            return _Result((None,) + tuple(object() for _ in evidence._CANONICAL_TABLES[1:]))
        raise AssertionError(f"unexpected execute: {query}")

    def cursor(self, row_factory=None):
        self.cursor_instance = _Cursor(self.rows)
        return self.cursor_instance


def _canonical(
    *,
    kind="BACKOFFICE_ONLY",
    owner=True,
    backoffice_principal_id=101,
    backoffice_user_id=202,
    backoffice_username="owner",
    field_principal_id=None,
    field_representative_id=None,
    field_username=None,
):
    return {
        "classification": kind,
        "backoffice_principal_id": backoffice_principal_id,
        "backoffice_user_id": backoffice_user_id,
        "backoffice_username": backoffice_username,
        "company_owner": owner,
        "field_principal_id": field_principal_id,
        "field_representative_id": field_representative_id,
        "field_username": field_username,
    }


def _facts(*, canonical=None, company=7, driver=909):
    return {
        "company_id": company,
        "legacy_driver_id": driver,
        "username": "legacy",
        "full_name": "Legacy Compatibility",
        "phone_number": None,
        "is_active": True,
        "can_allow_debt": False,
        "max_debt_limit": "0.000",
        "backoffice_grants": {"company_roles": 0, "location_grants": 0},
        "field_references": {
            "work_sessions": 0,
            "dispatch_routes": 0,
            "visits": 0,
            "shortage_requests": 0,
            "expected_receivers": 0,
        },
        "reference_fingerprint": "0" * 64,
        "canonical_identity": canonical or _canonical(),
    }


def _reviewed_document(facts):
    current = facts["canonical_identity"]
    entry = {
        "company_id": facts["company_id"],
        "legacy_driver_id": facts["legacy_driver_id"],
        "classification": current["classification"],
        "expected_source": facts,
        "source_fingerprint": mapping.fingerprint(facts),
        "backoffice_username": current["backoffice_username"],
        "field_username": current["field_username"],
        "company_owner": current["company_owner"],
    }
    return {"format_version": 1, "reviewed": True, "entries": [entry]}


class IdentityMigrationToolingPostCutoverTests(unittest.TestCase):
    def test_production_sources_have_zero_driver_is_admin_dependency(self):
        for path in (EVIDENCE_PATH, MAPPING_PATH):
            source = path.read_text(encoding="utf-8")
            for forbidden in (
                "drivers.is_admin",
                "d.is_admin",
                ".is_admin",
                '"is_admin"',
                "'is_admin'",
                "is_admin,",
                ",is_admin",
            ):
                self.assertNotIn(forbidden, source, (path.name, forbidden))

    def test_bridge_classification_and_owner_come_from_persisted_canonical_state(self):
        row = {
            "company_id": 7,
            "legacy_driver_id": 909,
            "classification": "BACKOFFICE_ONLY",
            "backoffice_principal_id": 101,
            "backoffice_user_id": 202,
            "backoffice_username": "owner",
            "backoffice_profile_present": True,
            "company_owner": True,
            "field_principal_id": None,
            "field_representative_id": None,
            "field_username": None,
            "field_profile_present": False,
        }
        conn = _CanonicalConnection([row])
        state = evidence._canonical_identity_rows(conn)
        self.assertEqual(state[(7, 909)]["classification"], "BACKOFFICE_ONLY")
        self.assertIs(state[(7, 909)]["company_owner"], True)
        query = conn.cursor_instance.query
        self.assertIn("m.classification", query)
        self.assertIn("LEFT JOIN company_owners AS co", query)
        self.assertIn("co.backoffice_user_id = m.backoffice_user_id", query)

    def test_field_classification_requires_exact_canonical_field_relation(self):
        row = {
            "company_id": 7,
            "legacy_driver_id": 909,
            "classification": "FIELD_ONLY",
            "backoffice_principal_id": None,
            "backoffice_user_id": None,
            "backoffice_username": None,
            "backoffice_profile_present": False,
            "company_owner": False,
            "field_principal_id": 303,
            "field_representative_id": 404,
            "field_username": "field-user",
            "field_profile_present": True,
        }
        conn = _CanonicalConnection([row])
        state = evidence._canonical_identity_rows(conn)
        self.assertEqual(state[(7, 909)]["classification"], "FIELD_ONLY")
        self.assertEqual(state[(7, 909)]["field_principal_id"], 303)
        self.assertEqual(state[(7, 909)]["field_representative_id"], 404)
        query = conn.cursor_instance.query
        self.assertIn("LEFT JOIN field_representatives AS fr", query)
        self.assertIn("fr.company_id = m.company_id", query)
        self.assertIn("fr.principal_id = m.field_principal_id", query)

    def test_cross_company_or_missing_exact_profile_mapping_is_rejected(self):
        row = {
            "company_id": 7,
            "legacy_driver_id": 909,
            "classification": "BACKOFFICE_ONLY",
            "backoffice_principal_id": 101,
            "backoffice_user_id": 202,
            "backoffice_username": None,
            "backoffice_profile_present": False,
            "company_owner": False,
            "field_principal_id": None,
            "field_representative_id": None,
            "field_username": None,
            "field_profile_present": False,
        }
        with self.assertRaisesRegex(
            BackfillError, "CANONICAL_IDENTITY_BRIDGE_INVALID"
        ):
            evidence._canonical_identity_rows(_CanonicalConnection([row]))

    def test_proposal_uses_bridge_state_not_legacy_grants_or_field_references(self):
        facts = _facts()
        facts["backoffice_grants"] = {"company_roles": 99, "location_grants": 88}
        facts["field_references"] = {
            "work_sessions": 12,
            "dispatch_routes": 11,
            "visits": 10,
            "shortage_requests": 9,
            "expected_receivers": 8,
        }
        source = {(7, 909): evidence.SourceRecord(facts, "")}
        report = evidence.proposal(source)
        entry = report["entries"][0]
        self.assertEqual(entry["classification"], "BACKOFFICE_ONLY")
        self.assertTrue(entry["company_owner"])
        self.assertEqual(entry["backoffice_username"], "owner")
        self.assertIsNone(entry["field_username"])

    def test_mapping_validation_requires_exact_persisted_classification_and_owner(self):
        facts = _facts()
        document = _reviewed_document(facts)
        entries = mapping.validate_document(document)
        self.assertEqual(entries[0].classification, "BACKOFFICE_ONLY")
        self.assertTrue(entries[0].company_owner)

        changed = copy.deepcopy(document)
        changed["entries"][0]["classification"] = "DUAL_SPLIT"
        changed["entries"][0]["field_username"] = "invented"
        with self.assertRaisesRegex(BackfillError, "CANONICAL_MAPPING_MISMATCH"):
            mapping.validate_document(changed)

        changed = copy.deepcopy(document)
        changed["entries"][0]["company_owner"] = False
        with self.assertRaisesRegex(BackfillError, "CANONICAL_MAPPING_MISMATCH"):
            mapping.validate_document(changed)

    def test_independent_principal_profile_and_driver_ids_are_supported(self):
        facts = _facts(
            driver=909,
            canonical=_canonical(
                kind="DUAL_SPLIT",
                owner=True,
                backoffice_principal_id=101,
                backoffice_user_id=202,
                backoffice_username="office",
                field_principal_id=303,
                field_representative_id=404,
                field_username="field",
            ),
        )
        document = _reviewed_document(facts)
        entry = mapping.validate_document(document)[0]
        ids = {
            entry.legacy_driver_id,
            facts["canonical_identity"]["backoffice_principal_id"],
            facts["canonical_identity"]["backoffice_user_id"],
            facts["canonical_identity"]["field_principal_id"],
            facts["canonical_identity"]["field_representative_id"],
        }
        self.assertEqual(ids, {909, 101, 202, 303, 404})

    def test_pre_cutover_classification_operation_fails_closed(self):
        conn = _CanonicalConnection([], tables_present=False)
        with self.assertRaisesRegex(
            BackfillError,
            "PRE_CUTOVER_LEGACY_CLASSIFICATION_EVIDENCE_UNAVAILABLE",
        ):
            evidence._canonical_identity_rows(conn)

        legacy_only = _facts()
        legacy_only.pop("canonical_identity")
        source = {(7, 909): evidence.SourceRecord(legacy_only, "")}
        with self.assertRaisesRegex(
            BackfillError,
            "PRE_CUTOVER_LEGACY_CLASSIFICATION_EVIDENCE_UNAVAILABLE",
        ):
            evidence.proposal(source)

    def test_driver_query_remains_valid_after_physical_admin_column_removal(self):
        source = EVIDENCE_PATH.read_text(encoding="utf-8")
        self.assertIn(
            '"is_active,can_allow_debt,max_debt_limit"',
            source,
        )
        self.assertNotIn("is_active,is_admin", source)
        self.assertNotIn("is_admin,can_allow_debt", source)

    def test_exact_tenant_scoping_is_present_on_every_canonical_join(self):
        source = EVIDENCE_PATH.read_text(encoding="utf-8")
        for fragment in (
            "bp.company_id = m.company_id",
            "bu.company_id = m.company_id",
            "co.company_id = m.company_id",
            "fp.company_id = m.company_id",
            "fr.company_id = m.company_id",
        ):
            self.assertIn(fragment, source)

    def test_mapping_source_schema_contains_canonical_state_and_no_admin_flag(self):
        self.assertIn("canonical_identity", mapping.SOURCE_KEYS)
        self.assertNotIn("is_admin", mapping.SOURCE_KEYS)
        self.assertEqual(
            mapping.CANONICAL_IDENTITY_KEYS,
            {
                "classification",
                "backoffice_principal_id",
                "backoffice_user_id",
                "backoffice_username",
                "company_owner",
                "field_principal_id",
                "field_representative_id",
                "field_username",
            },
        )


if __name__ == "__main__":
    unittest.main()
