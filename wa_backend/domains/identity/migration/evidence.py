"""Canonical non-secret current-state evidence for identity migration tooling.

Legacy Driver rows remain useful for compatibility/provenance facts, but they no
longer carry identity classification or owner authority. Current classification
is read only from persisted canonical identity state and the exact legacy bridge.
"""
from dataclasses import dataclass, field

from psycopg.rows import dict_row

from .errors import BackfillError
from .mapping import fingerprint

FIELD_REFERENCES = {
    "work_sessions": ("work_sessions", "driver_id"),
    "dispatch_routes": ("dispatch_routes", "driver_id"),
    "visits": ("visits", "driver_id"),
    "shortage_requests": ("shortage_requests", "driver_id"),
    "expected_receivers": ("inventory_transfer_headers", "expected_receiver_id"),
}
SOURCE_TABLES = (
    "drivers",
    "user_roles",
    "user_location_access",
    *(table for table, column in FIELD_REFERENCES.values()),
)
_CANONICAL_TABLES = (
    "company_principals",
    "backoffice_users",
    "company_owners",
    "field_representatives",
    "identity_legacy_driver_map",
)
_CLASSIFICATIONS = {"BACKOFFICE_ONLY", "FIELD_ONLY", "DUAL_SPLIT"}


@dataclass(frozen=True)
class SourceRecord:
    facts: dict
    password_hash: str = field(repr=False)

    @property
    def key(self):
        return self.facts["company_id"], self.facts["legacy_driver_id"]


def assert_full_visibility(conn):
    # FORCE RLS must never let a tenant slice masquerade as the complete source.
    row = conn.execute(
        "SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname=current_user"
    ).fetchone()
    if not row or row[0] is not True:
        raise BackfillError("MIGRATION_ROLE_FULL_VISIBILITY_REQUIRED")
    conn.execute("SET LOCAL row_security = off")
    conn.execute("SET LOCAL search_path = public, pg_catalog")


def _reference_rows(conn):
    queries = {
        "company_roles": (
            "SELECT company_id,driver_id,id,role_id FROM user_roles "
            "ORDER BY company_id,driver_id,id"
        ),
        "location_grants": (
            "SELECT company_id,driver_id,id,location_id,role_id "
            "FROM user_location_access ORDER BY company_id,driver_id,id"
        ),
        **{
            key: (
                f"SELECT company_id,{column},id FROM {table} "
                f"WHERE {column} IS NOT NULL ORDER BY company_id,{column},id"
            )
            for key, (table, column) in FIELD_REFERENCES.items()
        },
    }
    result = {}
    for kind, query in queries.items():
        for company_id, driver_id, *values in conn.execute(query).fetchall():
            result.setdefault((company_id, driver_id), {}).setdefault(kind, []).append(
                values
            )
    return result


def _require_post_cutover_identity_state(conn) -> None:
    placeholders = ",".join("to_regclass(%s)" for _ in _CANONICAL_TABLES)
    row = conn.execute(
        f"SELECT {placeholders}",
        tuple(f"public.{table}" for table in _CANONICAL_TABLES),
    ).fetchone()
    if not row or any(value is None for value in row):
        raise BackfillError("PRE_CUTOVER_LEGACY_CLASSIFICATION_EVIDENCE_UNAVAILABLE")


def _canonical_identity_rows(conn):
    """Return exact persisted current-state identity evidence keyed by legacy Driver."""
    _require_post_cutover_identity_state(conn)
    query = """
        SELECT
            m.company_id,
            m.legacy_driver_id,
            m.classification,
            m.backoffice_principal_id,
            m.backoffice_user_id,
            bp.username AS backoffice_username,
            (bu.id IS NOT NULL) AS backoffice_profile_present,
            (co.company_id IS NOT NULL) AS company_owner,
            m.field_principal_id,
            m.field_representative_id,
            fp.username AS field_username,
            (fr.id IS NOT NULL) AS field_profile_present
        FROM identity_legacy_driver_map AS m
        LEFT JOIN company_principals AS bp
          ON bp.company_id = m.company_id
         AND bp.id = m.backoffice_principal_id
         AND bp.principal_type = 'BACKOFFICE'
        LEFT JOIN backoffice_users AS bu
          ON bu.company_id = m.company_id
         AND bu.id = m.backoffice_user_id
         AND bu.principal_id = m.backoffice_principal_id
         AND bu.principal_type = 'BACKOFFICE'
        LEFT JOIN company_owners AS co
          ON co.company_id = m.company_id
         AND co.backoffice_user_id = m.backoffice_user_id
        LEFT JOIN company_principals AS fp
          ON fp.company_id = m.company_id
         AND fp.id = m.field_principal_id
         AND fp.principal_type = 'FIELD_REPRESENTATIVE'
        LEFT JOIN field_representatives AS fr
          ON fr.company_id = m.company_id
         AND fr.id = m.field_representative_id
         AND fr.principal_id = m.field_principal_id
         AND fr.principal_type = 'FIELD_REPRESENTATIVE'
        ORDER BY m.company_id, m.legacy_driver_id
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(query)
        rows = cur.fetchall()

    result = {}
    for row in rows:
        key = row["company_id"], row["legacy_driver_id"]
        if key in result:
            raise BackfillError("CANONICAL_IDENTITY_BRIDGE_INVALID")

        kind = row["classification"]
        if kind not in _CLASSIFICATIONS:
            raise BackfillError("CANONICAL_IDENTITY_BRIDGE_INVALID")

        backoffice_expected = kind != "FIELD_ONLY"
        field_expected = kind != "BACKOFFICE_ONLY"
        backoffice_valid = (
            row["backoffice_principal_id"] is not None
            and row["backoffice_user_id"] is not None
            and row["backoffice_username"] is not None
            and row["backoffice_profile_present"] is True
        )
        field_valid = (
            row["field_principal_id"] is not None
            and row["field_representative_id"] is not None
            and row["field_username"] is not None
            and row["field_profile_present"] is True
        )
        if backoffice_expected != backoffice_valid or field_expected != field_valid:
            raise BackfillError("CANONICAL_IDENTITY_BRIDGE_INVALID")
        if not backoffice_expected and any(
            row[name] is not None
            for name in (
                "backoffice_principal_id",
                "backoffice_user_id",
                "backoffice_username",
            )
        ):
            raise BackfillError("CANONICAL_IDENTITY_BRIDGE_INVALID")
        if not field_expected and any(
            row[name] is not None
            for name in (
                "field_principal_id",
                "field_representative_id",
                "field_username",
            )
        ):
            raise BackfillError("CANONICAL_IDENTITY_BRIDGE_INVALID")
        if row["company_owner"] is True and not backoffice_expected:
            raise BackfillError("CANONICAL_IDENTITY_BRIDGE_INVALID")

        result[key] = {
            "classification": kind,
            "backoffice_principal_id": row["backoffice_principal_id"],
            "backoffice_user_id": row["backoffice_user_id"],
            "backoffice_username": row["backoffice_username"],
            "company_owner": row["company_owner"] is True,
            "field_principal_id": row["field_principal_id"],
            "field_representative_id": row["field_representative_id"],
            "field_username": row["field_username"],
        }
    return result


def collect_source(conn, *, credentials=False):
    references = _reference_rows(conn)
    canonical = _canonical_identity_rows(conn)
    secret_column = ", password_hash" if credentials else ""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT company_id,id AS legacy_driver_id,username,full_name,phone_number,"
            "is_active,can_allow_debt,max_debt_limit"
            + secret_column
            + " FROM drivers ORDER BY company_id,id"
        )
        rows = cur.fetchall()

    source = {}
    for row in rows:
        secret = row.pop("password_hash", "")
        row["max_debt_limit"] = format(row["max_debt_limit"], ".3f")
        key = row["company_id"], row["legacy_driver_id"]
        current_identity = canonical.get(key)
        if current_identity is None:
            # The old pre-cutover proposal used legacy heuristics (including an
            # admin flag) to invent classification. That historical operation is
            # intentionally retired once the canonical cutover is in effect.
            raise BackfillError(
                "PRE_CUTOVER_LEGACY_CLASSIFICATION_EVIDENCE_UNAVAILABLE"
            )
        refs = references.get(key, {})
        row["backoffice_grants"] = {
            kind: len(refs.get(kind, []))
            for kind in ("company_roles", "location_grants")
        }
        row["field_references"] = {
            kind: len(refs.get(kind, [])) for kind in FIELD_REFERENCES
        }
        row["reference_fingerprint"] = fingerprint(refs)
        row["canonical_identity"] = current_identity
        source[key] = SourceRecord(row, secret)

    if set(canonical) != set(source):
        raise BackfillError("CANONICAL_IDENTITY_BRIDGE_INVALID")
    return source


def validate_source(entries, source):
    if {entry.key for entry in entries} != set(source):
        raise BackfillError("INCOMPLETE_OR_EXTRA_LEGACY_ROWS")
    for entry in entries:
        facts = source[entry.key].facts
        if (
            entry.expected_source != facts
            or entry.source_fingerprint != fingerprint(facts)
        ):
            raise BackfillError("STALE_MAPPING")


def proposal(source):
    """Mirror persisted canonical state; never infer current authority from legacy facts."""
    entries = []
    for key in sorted(source):
        facts = source[key].facts
        current_identity = facts.get("canonical_identity")
        if not isinstance(current_identity, dict):
            raise BackfillError(
                "PRE_CUTOVER_LEGACY_CLASSIFICATION_EVIDENCE_UNAVAILABLE"
            )
        kind = current_identity["classification"]
        entries.append(
            {
                "company_id": facts["company_id"],
                "legacy_driver_id": facts["legacy_driver_id"],
                "classification": kind,
                "expected_source": facts,
                "source_fingerprint": fingerprint(facts),
                "backoffice_username": current_identity["backoffice_username"],
                "field_username": current_identity["field_username"],
                "company_owner": current_identity["company_owner"],
            }
        )
    return {"format_version": 1, "reviewed": False, "entries": entries}
