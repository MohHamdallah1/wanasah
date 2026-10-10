"""Operator-only complete identity backfill; no runtime auth cutover.

report emits an unreviewed JSON proposal with no passwords/hashes. Review every
classification, supply both DUAL usernames, explicitly set every company_owner
boolean and set reviewed=true. validate is read-only; apply revalidates live
evidence under source/target locks and commits the entire mapping once.

Run from wa_backend (use an explicit migration environment file):
  python scripts/backfill_identity_from_legacy.py report --env-file PATH --output proposal.json
  python scripts/backfill_identity_from_legacy.py validate --env-file PATH --mapping-file reviewed.json
  python scripts/backfill_identity_from_legacy.py apply --env-file PATH --mapping-file reviewed.json
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from dotenv import dotenv_values
import psycopg
from sqlalchemy.engine import make_url

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from domains.identity.migration import backfill
from domains.identity.migration.errors import BackfillError
from domains.identity.migration.mapping import load_mapping


def _explicit_dsn(path):
    # Do not load the developer .env implicitly or let inherited URLs override review.
    declared = dotenv_values(path, interpolate=False)
    urls = []
    for name in ("DATABASE_URL_MIGRATION", "DATABASE_URL"):
        raw = declared.get(name)
        if not raw or "${" in raw or os.environ.get(name, raw) != raw:
            raise BackfillError("EXPLICIT_DATABASE_CONFIGURATION_REQUIRED")
        url = make_url(raw)
        if url.get_backend_name() != "postgresql" or not url.username or not url.database:
            raise BackfillError("EXPLICIT_POSTGRESQL_CONFIGURATION_REQUIRED")
        urls.append(url)
    if any((u.host, u.port or 5432, u.database) != (urls[0].host, urls[0].port or 5432, urls[0].database) for u in urls[1:]):
        raise BackfillError("DATABASE_TARGET_MISMATCH")
    return urls[0].set(drivername="postgresql").render_as_string(hide_password=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("report", "validate", "apply"))
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--mapping-file", type=Path)
    parser.add_argument("--output", type=Path, help="Secret-free JSON report output (report mode only).")
    args = parser.parse_args(argv)
    if not args.env_file.is_file():
        raise BackfillError("ENV_FILE_MISSING")
    if args.mode != "report" and args.mapping_file is None:
        raise BackfillError("EXPLICIT_MAPPING_FILE_REQUIRED")
    if args.mode == "report" and args.mapping_file is not None:
        raise BackfillError("REPORT_DOES_NOT_ACCEPT_MAPPING")
    if args.output is not None and args.mode != "report":
        raise BackfillError("OUTPUT_REQUIRES_REPORT_MODE")
    document = load_mapping(args.mapping_file) if args.mapping_file else None
    # All exceptions outside safe service errors are redacted in the entry point.
    with psycopg.connect(_explicit_dsn(args.env_file), autocommit=True) as conn:
        result = backfill.report(conn) if args.mode == "report" else getattr(backfill, args.mode)(conn, document)
    rendered = json.dumps(result, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BackfillError as exc:
        print(json.dumps({"status": "FAILED", "code": exc.code}), file=sys.stderr)
        raise SystemExit(2) from None
    except Exception:
        # DB exceptions/URL parsing may contain secrets. Never echo them or a traceback.
        print(json.dumps({"status": "FAILED", "code": "OPERATOR_COMMAND_FAILED"}), file=sys.stderr)
        raise SystemExit(3) from None
