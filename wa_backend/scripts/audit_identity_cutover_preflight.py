"""Read-only identity migration preflight.

Reports legacy owner ambiguity, dual-use Driver rows, Backoffice-style grants,
refresh-session residue, and unresolved legacy FK usage before any identity
backfill/cutover. It never writes application data or schema.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from dotenv import dotenv_values, load_dotenv
from sqlalchemy.engine import make_url
import psycopg


FIELD_USAGE_QUERIES = {
    "work_sessions": "SELECT count(*) FROM work_sessions WHERE company_id=%s AND driver_id=%s",
    "dispatch_routes": "SELECT count(*) FROM dispatch_routes WHERE company_id=%s AND driver_id=%s",
    "visits": "SELECT count(*) FROM visits WHERE company_id=%s AND driver_id=%s",
    "shortage_requests": "SELECT count(*) FROM shortage_requests WHERE company_id=%s AND driver_id=%s",
    "expected_receivers": "SELECT count(*) FROM inventory_transfer_headers WHERE company_id=%s AND expected_receiver_id=%s",
}


def _bind_explicit_env(env_file: Path, *, scope: str) -> None:
    declared = dotenv_values(env_file, interpolate=False)
    for name in ("DATABASE_URL_MIGRATION", "DATABASE_URL"):
        value = declared.get(name)
        if not value:
            raise RuntimeError(f"{name} must be explicitly declared")
        if "${" in value:
            raise RuntimeError(f"{name} must be a literal PostgreSQL URL")
        inherited = os.environ.get(name)
        if inherited is not None and inherited != value:
            raise RuntimeError(f"Inherited {name} conflicts with explicit env file")
    migration = make_url(str(declared["DATABASE_URL_MIGRATION"]))
    runtime = make_url(str(declared["DATABASE_URL"]))
    migration_identity = (migration.host, migration.port or 5432, migration.database)
    runtime_identity = (runtime.host, runtime.port or 5432, runtime.database)
    if migration_identity != runtime_identity:
        raise RuntimeError("Migration/runtime DB targets disagree")
    if scope == "staging" and os.environ.get("WANASAH_STAGING_READONLY_ACK") != "ISOLATED_SYNTHETIC_STAGING":
        raise RuntimeError("Staging requires WANASAH_STAGING_READONLY_ACK=ISOLATED_SYNTHETIC_STAGING")


def _dsn() -> str:
    return make_url(os.environ["DATABASE_URL_MIGRATION"]).set(
        drivername="postgresql"
    ).render_as_string(hide_password=False)


def _scalar(cur: psycopg.Cursor, sql: str, params: tuple[object, ...]) -> int:
    cur.execute(sql, params)
    row = cur.fetchone()
    return int(row[0]) if row else 0


def _driver_field_usage(cur: psycopg.Cursor, company_id: int, driver_id: int) -> dict[str, int]:
    return {
        name: _scalar(cur, sql, (company_id, driver_id))
        for name, sql in FIELD_USAGE_QUERIES.items()
    }


def _tenant_report(cur: psycopg.Cursor, company_id: int) -> dict[str, object]:
    cur.execute(
        "SELECT id, is_admin, is_active FROM drivers WHERE company_id=%s ORDER BY id",
        (company_id,),
    )
    drivers = [
        {"id": int(row[0]), "is_admin": bool(row[1]), "is_active": bool(row[2])}
        for row in cur.fetchall()
    ]

    active_admins = [d for d in drivers if d["is_admin"] and d["is_active"]]
    inactive_admins = [d for d in drivers if d["is_admin"] and not d["is_active"]]
    nonadmins = [d for d in drivers if not d["is_admin"]]

    field_usage = {
        str(d["id"]): _driver_field_usage(cur, company_id, int(d["id"]))
        for d in drivers
    }

    dual_use_admin_ids = [
        int(d["id"])
        for d in active_admins
        if sum(field_usage[str(d["id"])].values()) > 0
    ]

    cur.execute(
        """
        SELECT d.id,
               (SELECT count(*) FROM user_roles ur WHERE ur.company_id=d.company_id AND ur.driver_id=d.id),
               (SELECT count(*) FROM user_location_access ula WHERE ula.company_id=d.company_id AND ula.driver_id=d.id)
        FROM drivers d
        WHERE d.company_id=%s
        ORDER BY d.id
        """,
        (company_id,),
    )
    grant_rows = [
        {"driver_id": int(row[0]), "company_roles": int(row[1]), "location_grants": int(row[2])}
        for row in cur.fetchall()
    ]
    nonadmin_ids = {int(d["id"]) for d in nonadmins}
    nonadmin_with_backoffice_grants = [
        r for r in grant_rows
        if r["driver_id"] in nonadmin_ids and (r["company_roles"] or r["location_grants"])
    ]

    cur.execute(
        """
        SELECT rt.driver_id,
               count(*) AS total,
               count(*) FILTER (WHERE NOT rt.revoked AND rt.expires_at > now()) AS active
        FROM refresh_tokens rt
        JOIN drivers d ON d.id=rt.driver_id
        WHERE d.company_id=%s
        GROUP BY rt.driver_id
        ORDER BY rt.driver_id
        """,
        (company_id,),
    )
    refresh = [
        {"driver_id": int(row[0]), "total": int(row[1]), "active": int(row[2])}
        for row in cur.fetchall()
    ]

    ambiguous_fk_usage = {
        "shops.added_by_driver_id": _scalar(
            cur,
            "SELECT count(*) FROM shops WHERE company_id=%s AND added_by_driver_id IS NOT NULL",
            (company_id,),
        ),
        "inventory_damage_events.source_driver_id": _scalar(
            cur,
            "SELECT count(*) FROM inventory_damage_events WHERE company_id=%s AND source_driver_id IS NOT NULL",
            (company_id,),
        ),
        "inventory_damage_events.receiving_admin_id": _scalar(
            cur,
            "SELECT count(*) FROM inventory_damage_events WHERE company_id=%s AND receiving_admin_id IS NOT NULL",
            (company_id,),
        ),
    }

    blockers: list[str] = []
    review: list[str] = []
    if len(active_admins) == 0:
        blockers.append("NO_ACTIVE_LEGACY_OWNER_CANDIDATE")
    elif len(active_admins) > 1:
        blockers.append("MULTIPLE_ACTIVE_LEGACY_OWNER_CANDIDATES")
    if dual_use_admin_ids:
        blockers.append("OWNER_CANDIDATE_HAS_FIELD_WORK_HISTORY")
    if nonadmin_with_backoffice_grants:
        review.append("NONADMIN_ROWS_HAVE_BACKOFFICE_GRANTS")
    if any(ambiguous_fk_usage.values()):
        review.append("AMBIGUOUS_LEGACY_FKS_HAVE_DATA")

    return {
        "company_id": company_id,
        "driver_count": len(drivers),
        "active_legacy_admin_ids": [int(d["id"]) for d in active_admins],
        "inactive_legacy_admin_ids": [int(d["id"]) for d in inactive_admins],
        "legacy_nonadmin_count": len(nonadmins),
        "dual_use_admin_ids": dual_use_admin_ids,
        "nonadmin_with_backoffice_grants": nonadmin_with_backoffice_grants,
        "refresh_sessions": refresh,
        "ambiguous_fk_usage": ambiguous_fk_usage,
        "blockers": blockers,
        "review": review,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--scope", choices=("developer", "staging"), required=True)
    args = parser.parse_args()
    if not args.env_file.is_file():
        raise RuntimeError("Explicit environment file missing")

    _bind_explicit_env(args.env_file, scope=args.scope)
    load_dotenv(args.env_file, override=False)

    reports: list[dict[str, object]] = []
    with psycopg.connect(_dsn(), autocommit=False) as conn:
        with conn.transaction():
            conn.execute("SET TRANSACTION READ ONLY")
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM companies ORDER BY id")
                company_ids = [int(row[0]) for row in cur.fetchall()]
                for company_id in company_ids:
                    reports.append(_tenant_report(cur, company_id))

    summary = {
        "scope": args.scope,
        "company_count": len(reports),
        "blocking_company_ids": [r["company_id"] for r in reports if r["blockers"]],
        "review_company_ids": [r["company_id"] for r in reports if r["review"]],
        "companies": reports,
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 2 if summary["blocking_company_ids"] else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"identity preflight failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(3) from None
