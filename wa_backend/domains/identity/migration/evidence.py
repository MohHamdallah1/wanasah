"""Canonical non-secret source evidence. Credentials stay in memory, out of reports."""
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
SOURCE_TABLES = ("drivers", "user_roles", "user_location_access",
                 *(table for table, column in FIELD_REFERENCES.values()))


@dataclass(frozen=True)
class SourceRecord:
    facts: dict
    password_hash: str = field(repr=False)

    @property
    def key(self):
        return self.facts["company_id"], self.facts["legacy_driver_id"]


def assert_full_visibility(conn):
    # FORCE RLS must never let a tenant slice masquerade as the complete source.
    row = conn.execute("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()
    if not row or row[0] is not True:
        raise BackfillError("MIGRATION_ROLE_FULL_VISIBILITY_REQUIRED")
    conn.execute("SET LOCAL row_security = off")
    conn.execute("SET LOCAL search_path = public, pg_catalog")


def _reference_rows(conn):
    queries = {
        "company_roles": "SELECT company_id,driver_id,id,role_id FROM user_roles ORDER BY company_id,driver_id,id",
        "location_grants": "SELECT company_id,driver_id,id,location_id,role_id FROM user_location_access ORDER BY company_id,driver_id,id",
        **{key: f"SELECT company_id,{column},id FROM {table} WHERE {column} IS NOT NULL ORDER BY company_id,{column},id"
           for key, (table, column) in FIELD_REFERENCES.items()},
    }
    result = {}
    for kind, query in queries.items():
        for company_id, driver_id, *values in conn.execute(query).fetchall():
            result.setdefault((company_id, driver_id), {}).setdefault(kind, []).append(values)
    return result


def collect_source(conn, *, credentials=False):
    references = _reference_rows(conn)
    secret_column = ", password_hash" if credentials else ""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT company_id,id AS legacy_driver_id,username,full_name,phone_number,"
                    "is_active,is_admin,can_allow_debt,max_debt_limit" + secret_column +
                    " FROM drivers ORDER BY company_id,id")
        rows = cur.fetchall()
    source = {}
    for row in rows:
        secret = row.pop("password_hash", "")
        row["max_debt_limit"] = format(row["max_debt_limit"], ".3f")
        key = row["company_id"], row["legacy_driver_id"]
        refs = references.get(key, {})
        row["backoffice_grants"] = {kind: len(refs.get(kind, [])) for kind in ("company_roles", "location_grants")}
        row["field_references"] = {kind: len(refs.get(kind, [])) for kind in FIELD_REFERENCES}
        row["reference_fingerprint"] = fingerprint(refs)
        source[key] = SourceRecord(row, secret)
    return source


def validate_source(entries, source):
    if {entry.key for entry in entries} != set(source):
        raise BackfillError("INCOMPLETE_OR_EXTRA_LEGACY_ROWS")
    for entry in entries:
        facts = source[entry.key].facts
        if entry.expected_source != facts or entry.source_fingerprint != fingerprint(facts):
            raise BackfillError("STALE_MAPPING")


def proposal(source):
    entries = []
    for record in source.values():
        facts = record.facts
        office = facts["is_admin"] or any(facts["backoffice_grants"].values())
        field_usage = any(facts["field_references"].values())
        kind = "DUAL_SPLIT" if office and field_usage else "BACKOFFICE_ONLY" if office else "FIELD_ONLY" if field_usage else None
        entries.append({
            "company_id": facts["company_id"], "legacy_driver_id": facts["legacy_driver_id"],
            "classification": kind, "expected_source": facts, "source_fingerprint": fingerprint(facts),
            "backoffice_username": facts["username"] if office else None,
            # DUAL needs an explicit second username; weak evidence needs explicit classification.
            "field_username": facts["username"] if kind == "FIELD_ONLY" else None,
            "company_owner": None,
        })
    return {"format_version": 1, "reviewed": False, "entries": entries}
