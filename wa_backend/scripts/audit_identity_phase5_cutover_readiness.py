"""Read-only Phase 5 identity/auth cutover readiness audit.

This gate never mutates data or schema. It verifies that the reviewed identity
bridge can account for every legacy Driver, active companies have exactly one
CompanyOwner, legacy Backoffice grants have deterministic Backoffice mappings,
and the principal refresh-session table is present. In post-invalidation mode it
also requires zero active legacy refresh sessions before Runtime auth cutover.
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


def _bind_explicit_env(env_file: Path, *, scope: str) -> None:
    declared = dotenv_values(env_file, interpolate=False)
    for name in ("DATABASE_URL_MIGRATION", "DATABASE_URL"):
        value = declared.get(name)
        if not value:
            raise RuntimeError(f"{name} must be explicitly declared")
        if "${" in str(value):
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


def _scalar(cur: psycopg.Cursor, sql: str, params: tuple[object, ...] = ()) -> int:
    cur.execute(sql, params)
    row = cur.fetchone()
    return int(row[0]) if row else 0


def _required_tables(cur: psycopg.Cursor) -> list[str]:
    names = (
        "company_principals",
        "backoffice_users",
        "field_representatives",
        "company_owners",
        "identity_legacy_driver_map",
        "principal_refresh_tokens",
    )
    missing: list[str] = []
    for name in names:
        cur.execute("SELECT to_regclass(%s)", (name,))
        row = cur.fetchone()
        if row is None or row[0] is None:
            missing.append(name)
    return missing


def _company_report(cur: psycopg.Cursor, company_id: int, *, require_legacy_refresh_zero: bool) -> dict[str, object]:
    driver_count = _scalar(cur, "SELECT count(*) FROM drivers WHERE company_id=%s", (company_id,))
    mapped_driver_count = _scalar(
        cur,
        "SELECT count(*) FROM identity_legacy_driver_map WHERE company_id=%s",
        (company_id,),
    )
    principal_count = _scalar(cur, "SELECT count(*) FROM company_principals WHERE company_id=%s", (company_id,))
    owner_count = _scalar(cur, "SELECT count(*) FROM company_owners WHERE company_id=%s", (company_id,))

    unmapped_company_roles = _scalar(
        cur,
        """
        SELECT count(*)
        FROM user_roles ur
        LEFT JOIN identity_legacy_driver_map m
          ON m.company_id=ur.company_id
         AND m.legacy_driver_id=ur.driver_id
         AND m.backoffice_user_id IS NOT NULL
        WHERE ur.company_id=%s AND m.legacy_driver_id IS NULL
        """,
        (company_id,),
    )
    unmapped_location_grants = _scalar(
        cur,
        """
        SELECT count(*)
        FROM user_location_access ula
        LEFT JOIN identity_legacy_driver_map m
          ON m.company_id=ula.company_id
         AND m.legacy_driver_id=ula.driver_id
         AND m.backoffice_user_id IS NOT NULL
        WHERE ula.company_id=%s AND m.legacy_driver_id IS NULL
        """,
        (company_id,),
    )
    active_legacy_refresh = _scalar(
        cur,
        """
        SELECT count(*)
        FROM refresh_tokens rt
        JOIN drivers d ON d.id=rt.driver_id
        WHERE d.company_id=%s
          AND NOT rt.is_revoked
          AND rt.expires_at > now()
        """,
        (company_id,),
    )
    principal_refresh = _scalar(
        cur,
        "SELECT count(*) FROM principal_refresh_tokens WHERE company_id=%s",
        (company_id,),
    )

    blockers: list[str] = []
    review: list[str] = []
    if driver_count != mapped_driver_count:
        blockers.append("LEGACY_DRIVER_MAPPING_INCOMPLETE")
    if driver_count and principal_count == 0:
        blockers.append("NO_CANONICAL_PRINCIPALS")
    if owner_count != 1:
        blockers.append("COMPANY_OWNER_NOT_EXACTLY_ONE")
    if unmapped_company_roles:
        blockers.append("COMPANY_ROLE_GRANT_WITHOUT_BACKOFFICE_MAPPING")
    if unmapped_location_grants:
        blockers.append("LOCATION_GRANT_WITHOUT_BACKOFFICE_MAPPING")
    if require_legacy_refresh_zero and active_legacy_refresh:
        blockers.append("ACTIVE_LEGACY_REFRESH_SESSIONS_REMAIN")
    elif active_legacy_refresh:
        review.append("LEGACY_REFRESH_INVALIDATION_REQUIRED_AT_CUTOVER")

    return {
        "company_id": company_id,
        "legacy_driver_count": driver_count,
        "mapped_legacy_driver_count": mapped_driver_count,
        "canonical_principal_count": principal_count,
        "company_owner_count": owner_count,
        "unmapped_company_role_grants": unmapped_company_roles,
        "unmapped_location_grants": unmapped_location_grants,
        "active_legacy_refresh_sessions": active_legacy_refresh,
        "principal_refresh_session_count": principal_refresh,
        "blockers": blockers,
        "review": review,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--scope", choices=("developer", "staging"), required=True)
    parser.add_argument(
        "--stage",
        choices=("pre-switch", "post-invalidation"),
        default="pre-switch",
        help="post-invalidation additionally requires zero active legacy refresh sessions",
    )
    args = parser.parse_args()
    if not args.env_file.is_file():
        raise RuntimeError("Explicit environment file missing")

    _bind_explicit_env(args.env_file, scope=args.scope)
    load_dotenv(args.env_file, override=False)

    with psycopg.connect(_dsn(), autocommit=False) as conn:
        with conn.transaction():
            conn.execute("SET TRANSACTION READ ONLY")
            with conn.cursor() as cur:
                missing_tables = _required_tables(cur)
                if missing_tables:
                    summary = {
                        "scope": args.scope,
                        "stage": args.stage,
                        "missing_required_tables": missing_tables,
                        "blocking_company_ids": [],
                        "companies": [],
                    }
                    print(json.dumps(summary, indent=2, sort_keys=True))
                    return 2

                cur.execute("SELECT id FROM companies WHERE is_active IS TRUE ORDER BY id")
                company_ids = [int(row[0]) for row in cur.fetchall()]
                reports = [
                    _company_report(
                        cur,
                        company_id,
                        require_legacy_refresh_zero=(args.stage == "post-invalidation"),
                    )
                    for company_id in company_ids
                ]

    summary = {
        "scope": args.scope,
        "stage": args.stage,
        "missing_required_tables": [],
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
        print(f"phase5 readiness audit failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(3) from None
