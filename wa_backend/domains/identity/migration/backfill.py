"""One atomic, complete backfill. Exact verification replaces repair on rerun."""
from decimal import Decimal

import psycopg
from psycopg.pq import TransactionStatus
from psycopg.rows import dict_row
from psycopg import sql

from .errors import BackfillError
from .evidence import SOURCE_TABLES, assert_full_visibility, collect_source, proposal, validate_source
from .mapping import validate_document

IDENTITY_TABLES = ("company_principals", "backoffice_users", "field_representatives", "company_owners")
BRIDGE = "identity_legacy_driver_map"


def _idle(conn):
    if conn.info.transaction_status != TransactionStatus.IDLE:
        raise BackfillError("IDLE_CONNECTION_REQUIRED")


def _start(conn, *, readonly):
    conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ" + (" READ ONLY" if readonly else ""))
    conn.execute("SET LOCAL lock_timeout = '5s'")
    conn.execute("SET LOCAL statement_timeout = '120s'")
    assert_full_visibility(conn)


def _lock_apply(conn):
    # Lock before reading: block source phantoms and source/target edits until commit.
    # READ COMMITTED gets a fresh snapshot after waiting for these locks.
    for tables, mode in ((SOURCE_TABLES, "SHARE"), ((*IDENTITY_TABLES, BRIDGE), "SHARE ROW EXCLUSIVE")):
        names = sql.SQL(", ").join(sql.Identifier(table) for table in tables)
        conn.execute(sql.SQL("LOCK TABLE {} IN " + mode + " MODE").format(names))


def report(conn):
    _idle(conn)
    try:
        with conn.transaction():
            _start(conn, readonly=True)
            return proposal(collect_source(conn))
    except psycopg.Error:
        raise BackfillError("SOURCE_READ_FAILED") from None


def _rows(conn, table):
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql.SQL("SELECT * FROM {} ORDER BY company_id").format(sql.Identifier(table)))
        return cur.fetchall()


def _bridge_state(conn, entries):
    rows = _rows(conn, BRIDGE)
    if not rows:
        return None
    state = {(row["company_id"], row["legacy_driver_id"]): row for row in rows}
    if set(state) != {entry.key for entry in entries}:
        raise BackfillError("DIVERGENT_BRIDGE")
    return state


def _assert_scope_targets(conn, entries, bridges=None):
    companies = {entry.company_id for entry in entries}
    expected = {table: set() for table in IDENTITY_TABLES}
    if bridges is not None:
        for entry in entries:
            row = bridges[entry.key]
            for table, column in (("company_principals", "backoffice_principal_id"),
                                  ("company_principals", "field_principal_id"),
                                  ("backoffice_users", "backoffice_user_id"),
                                  ("field_representatives", "field_representative_id")):
                if row[column] is not None:
                    expected[table].add((entry.company_id, row[column]))
            if entry.company_owner:
                expected["company_owners"].add((entry.company_id, entry.company_id))
    tables = {}
    for table in IDENTITY_TABLES:
        rows = [row for row in _rows(conn, table) if row["company_id"] in companies]
        key = "company_id" if table == "company_owners" else "id"
        actual = {(row["company_id"], row[key]): row for row in rows}
        if set(actual) != expected[table]:
            raise BackfillError("DIVERGENT_OR_UNMAPPED_TARGETS")
        tables[table] = actual
    return tables


def _check_principal(row, entry, record, username, kind):
    facts = record.facts
    expected = {"company_id": entry.company_id, "username": username, "principal_type": kind,
                "password_hash": record.password_hash, "auth_revision": 1,
                **{key: facts[key] for key in ("full_name", "phone_number", "is_active")}}
    if any(row[key] != value for key, value in expected.items()):
        raise BackfillError("DIVERGENT_PRINCIPAL")


def _verify_rerun(conn, entries, source, bridges):
    tables = _assert_scope_targets(conn, entries, bridges)
    for entry in entries:
        bridge = bridges[entry.key]
        if bridge["classification"] != entry.classification:
            raise BackfillError("DIVERGENT_BRIDGE")
        for username, kind, principal_column, profile_column, table in (
            (entry.backoffice_username, "BACKOFFICE", "backoffice_principal_id", "backoffice_user_id", "backoffice_users"),
            (entry.field_username, "FIELD_REPRESENTATIVE", "field_principal_id", "field_representative_id", "field_representatives"),
        ):
            principal_id, profile_id = bridge[principal_column], bridge[profile_column]
            if username is None:
                if principal_id is not None or profile_id is not None:
                    raise BackfillError("DIVERGENT_BRIDGE")
                continue
            if principal_id is None or profile_id is None:
                raise BackfillError("DIVERGENT_BRIDGE")
            root = tables["company_principals"].get((entry.company_id, principal_id))
            profile = tables[table].get((entry.company_id, profile_id))
            if root is None or profile is None or profile["principal_id"] != principal_id or profile["principal_type"] != kind:
                raise BackfillError("DIVERGENT_PROFILE")
            _check_principal(root, entry, source[entry.key], username, kind)
            if table == "field_representatives":
                facts = source[entry.key].facts
                if profile["can_allow_debt"] != facts["can_allow_debt"] or profile["max_debt_limit"] != Decimal(facts["max_debt_limit"]):
                    raise BackfillError("DIVERGENT_FIELD_DEBT")
        if entry.company_owner:
            owner = tables["company_owners"][(entry.company_id, entry.company_id)]
            if owner["backoffice_user_id"] != bridge["backoffice_user_id"]:
                raise BackfillError("DIVERGENT_OWNER")


def _preflight(conn, entries, source):
    validate_source(entries, source)
    bridges = _bridge_state(conn, entries)
    if bridges is None:
        _assert_scope_targets(conn, entries)
    else:
        _verify_rerun(conn, entries, source, bridges)
    return bridges


def validate(conn, document):
    entries = validate_document(document)
    _idle(conn)
    try:
        with conn.transaction():
            _start(conn, readonly=True)
            source = collect_source(conn, credentials=True)
            bridges = _preflight(conn, entries, source)
            return _result(entries, "VALID_EXACT_RERUN" if bridges is not None else "VALID_NEW_BACKFILL")
    except psycopg.Error:
        raise BackfillError("VALIDATION_DATABASE_FAILED") from None


def _create_channel(conn, entry, record, username, kind):
    facts = record.facts
    principal_id = conn.execute(
        "INSERT INTO company_principals(company_id,username,password_hash,full_name,phone_number,is_active,principal_type) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id",
        (entry.company_id, username, record.password_hash, facts["full_name"], facts["phone_number"], facts["is_active"], kind),
    ).fetchone()[0]
    if kind == "BACKOFFICE":
        profile_id = conn.execute("INSERT INTO backoffice_users(company_id,principal_id) VALUES (%s,%s) RETURNING id",
                                  (entry.company_id, principal_id)).fetchone()[0]
    else:
        profile_id = conn.execute("INSERT INTO field_representatives(company_id,principal_id,can_allow_debt,max_debt_limit) "
                                  "VALUES (%s,%s,%s,%s) RETURNING id",
                                  (entry.company_id, principal_id, facts["can_allow_debt"], Decimal(facts["max_debt_limit"]))).fetchone()[0]
    return principal_id, profile_id


def _create_entry(conn, entry, record):
    targets = [None, None, None, None]
    if entry.backoffice_username is not None:
        targets[:2] = _create_channel(conn, entry, record, entry.backoffice_username, "BACKOFFICE")
    if entry.field_username is not None:
        targets[2:] = _create_channel(conn, entry, record, entry.field_username, "FIELD_REPRESENTATIVE")
    conn.execute("INSERT INTO identity_legacy_driver_map(company_id,legacy_driver_id,classification,"
                 "backoffice_principal_id,backoffice_user_id,field_principal_id,field_representative_id) "
                 "VALUES (%s,%s,%s,%s,%s,%s,%s)", (entry.company_id, entry.legacy_driver_id, entry.classification, *targets))
    if entry.company_owner:
        conn.execute("INSERT INTO company_owners(company_id,backoffice_user_id) VALUES (%s,%s)", (entry.company_id, targets[1]))


def _result(entries, status):
    return {"status": status, "legacy_driver_count": len(entries),
            "company_count": len({entry.company_id for entry in entries}),
            "classifications": {kind: sum(e.classification == kind for e in entries)
                                for kind in ("BACKOFFICE_ONLY", "FIELD_ONLY", "DUAL_SPLIT")}}


def apply(conn, document):
    entries = validate_document(document)
    _idle(conn)
    try:
        with conn.transaction():
            # Use READ COMMITTED from the outset, so lock waits cannot retain an old snapshot.
            conn.execute("SET LOCAL lock_timeout = '5s'")
            conn.execute("SET LOCAL statement_timeout = '120s'")
            conn.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
            assert_full_visibility(conn)
            _lock_apply(conn)
            source = collect_source(conn, credentials=True)
            bridges = _preflight(conn, entries, source)
            if bridges is not None:
                return _result(entries, "EXACT_RERUN")
            for entry in entries:
                _create_entry(conn, entry, source[entry.key])
            # Verify every stored pair/credential/Owner before committing, including triggers.
            _verify_rerun(conn, entries, source, _bridge_state(conn, entries))
            return _result(entries, "APPLIED")
    except psycopg.Error:
        raise BackfillError("ATOMIC_APPLY_DATABASE_FAILED") from None
