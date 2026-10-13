"""Post-cutover identity migration-tooling gate in an isolated PostgreSQL 16 cluster.

This used to replay the Phase 3/4 legacy-classification backfill. That operation is
retired: current tooling must fail closed when persisted canonical identity evidence
is absent, and may only report/validate/apply against the canonical bridge state.

No existing DB URL is accepted and no developer .env is read.
Run from wa_backend: python tests/run_identity_legacy_backfill_gate.py --run
"""
from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile

import psycopg

import run_identity_schema_expand_gate as fixture_tools

BACKEND = Path(__file__).resolve().parents[1]
HEAD = "f2c7a9d4e611"
ADMIN = "identity_backfill_admin"
RUNTIME = "identity_backfill_runtime"
DATABASE = "identity_backfill_test"
SECRET = "synthetic-hash-do-not-report-post-cutover"


def _driver(conn, company_id: int) -> int:
    return conn.execute(
        """INSERT INTO drivers(
               company_id,username,password_hash,full_name,phone_number,
               is_active,can_allow_debt,max_debt_limit,created_at
           ) VALUES (%s,'legacy-owner',%s,'Synthetic owner','+96200000',
                     true,false,'0.000',CURRENT_TIMESTAMP)
           RETURNING id""",
        (company_id, SECRET),
    ).fetchone()[0]


def _canonical_owner(conn, company_id: int, driver_id: int) -> tuple[int, int]:
    # Make the independence of legacy Driver / principal / profile IDs explicit.
    conn.execute("SELECT setval('company_principals_id_seq',10000,true)")
    conn.execute("SELECT setval('backoffice_users_id_seq',20000,true)")
    principal_id = conn.execute(
        """INSERT INTO company_principals(
               company_id,username,password_hash,full_name,phone_number,
               principal_type,is_active
           ) VALUES (%s,'canonical-owner',%s,'Synthetic owner','+96200000',
                     'BACKOFFICE',true)
           RETURNING id""",
        (company_id, SECRET),
    ).fetchone()[0]
    backoffice_user_id = conn.execute(
        "INSERT INTO backoffice_users(company_id,principal_id) VALUES (%s,%s) RETURNING id",
        (company_id, principal_id),
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO company_owners(company_id,backoffice_user_id) VALUES (%s,%s)",
        (company_id, backoffice_user_id),
    )
    conn.execute(
        """INSERT INTO identity_legacy_driver_map(
               company_id,legacy_driver_id,classification,
               backoffice_principal_id,backoffice_user_id,
               field_principal_id,field_representative_id
           ) VALUES (%s,%s,'BACKOFFICE_ONLY',%s,%s,NULL,NULL)""",
        (company_id, driver_id, principal_id, backoffice_user_id),
    )
    assert len({driver_id, principal_id, backoffice_user_id}) == 3
    return principal_id, backoffice_user_id


def _expect_backfill_error(callable_, code: str) -> None:
    from domains.identity.migration.errors import BackfillError

    try:
        callable_()
    except BackfillError as exc:
        assert exc.code == code, (exc.code, code)
        assert SECRET not in str(exc)
        return
    raise AssertionError(f"Expected BackfillError({code})")


def _operator_cli(env: dict[str, str], cluster: Path, document: dict) -> None:
    explicit = cluster / "operator.env"
    explicit.write_text(
        "DATABASE_URL=" + env["DATABASE_URL"] + "\n"
        "DATABASE_URL_MIGRATION=" + env["DATABASE_URL_MIGRATION"] + "\n",
        encoding="utf-8",
    )
    mapping = cluster / "reviewed.json"
    mapping.write_text(json.dumps(document), encoding="utf-8")
    command = [sys.executable, "scripts/backfill_identity_from_legacy.py"]

    report = json.loads(
        fixture_tools.run([*command, "report", "--env-file", str(explicit)], env=env)
    )
    assert report["reviewed"] is False
    assert report["entries"][0]["classification"] == "BACKOFFICE_ONLY"
    assert report["entries"][0]["company_owner"] is True
    assert SECRET not in json.dumps(report)

    validated = json.loads(
        fixture_tools.run(
            [*command, "validate", "--env-file", str(explicit), "--mapping-file", str(mapping)],
            env=env,
        )
    )
    assert validated["status"] == "VALID_EXACT_RERUN"

    applied = json.loads(
        fixture_tools.run(
            [*command, "apply", "--env-file", str(explicit), "--mapping-file", str(mapping)],
            env=env,
        )
    )
    assert applied["status"] == "EXACT_RERUN"

    bad = copy.deepcopy(document)
    bad["entries"][0]["company_owner"] = False
    invalid = cluster / "invalid.json"
    invalid.write_text(json.dumps(bad), encoding="utf-8")
    failed = subprocess.run(
        [*command, "validate", "--env-file", str(explicit), "--mapping-file", str(invalid)],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    output = failed.stdout + failed.stderr
    assert failed.returncode == 2
    assert SECRET not in output
    assert "Traceback" not in output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true")
    parser.add_argument(
        "--pg-bin",
        type=Path,
        default=(
            Path(r"C:\Program Files\PostgreSQL\16\bin")
            if os.name == "nt"
            else Path("/usr/lib/postgresql/16/bin")
        ),
    )
    args = parser.parse_args()
    if not args.run:
        parser.error("--run required; existing DB URLs are never accepted")
    assert Path.cwd().resolve() == BACKEND

    pg = lambda name: str(args.pg_bin / (name + (".exe" if os.name == "nt" else "")))
    cluster = Path(tempfile.mkdtemp(prefix="wanasah_identity_backfill_")).resolve()
    data = cluster / "data"
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        port = reserved.getsockname()[1]

    env = os.environ.copy()
    env.update(
        {
            "PYTHONDONTWRITEBYTECODE": "1",
            "ENVIRONMENT": "test",
            "SECRET_KEY": "IdentityBackfillSynthetic123456789012345678901234567",
            "DATABASE_URL": f"postgresql+asyncpg://{RUNTIME}@127.0.0.1:{port}/{DATABASE}",
            "DATABASE_URL_MIGRATION": f"postgresql+asyncpg://{ADMIN}@127.0.0.1:{port}/{DATABASE}",
        }
    )
    os.environ.update(
        {
            key: env[key]
            for key in (
                "PYTHONDONTWRITEBYTECODE",
                "ENVIRONMENT",
                "SECRET_KEY",
                "DATABASE_URL",
                "DATABASE_URL_MIGRATION",
            )
        }
    )
    sys.path.insert(0, str(BACKEND))
    from domains.identity.migration import backfill as service

    checks: list[str] = []
    started = False

    def checkpoint(label: str) -> None:
        checks.append(label)
        print(label + "=PASS", flush=True)

    def alembic(*arguments: str) -> str:
        return fixture_tools.run([sys.executable, "-m", "alembic", *arguments], env=env)

    try:
        fixture_tools.run(
            [
                pg("initdb"),
                "-D",
                str(data),
                "-U",
                ADMIN,
                "--auth=trust",
                "--encoding=UTF8",
                "--no-locale",
            ]
        )
        server_opts = f"-h 127.0.0.1 -p {port}"
        if os.name != "nt":
            server_opts += f" -k {cluster}"
        fixture_tools.run(
            [
                pg("pg_ctl"),
                "-D",
                str(data),
                "-l",
                str(cluster / "postgres.log"),
                "-o",
                server_opts,
                "-w",
                "start",
            ],
            pg_ctl=True,
        )
        started = True
        print(f"ISOLATED_CLUSTER_STARTED={cluster}", flush=True)

        connect = {"host": "127.0.0.1", "port": port, "dbname": DATABASE}
        with psycopg.connect(
            host="127.0.0.1", port=port, dbname="postgres", user=ADMIN, autocommit=True
        ) as conn:
            assert Path(conn.execute("SHOW data_directory").fetchone()[0]).resolve() == data
            conn.execute(
                f"CREATE ROLE {RUNTIME} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS"
            )
            conn.execute(f"CREATE DATABASE {DATABASE}")

        alembic("upgrade", "head")
        assert HEAD in alembic("current")
        checkpoint("CLEAN_BOOTSTRAP_TO_CURRENT_HEAD")

        with psycopg.connect(**connect, user=ADMIN, autocommit=True) as conn:
            assert (
                conn.execute(
                    """SELECT count(*) FROM information_schema.columns
                       WHERE table_schema='public' AND table_name='drivers' AND column_name='is_admin'"""
                ).fetchone()[0]
                == 0
            )
            company_id = fixture_tools.company(conn, "POST-CUTOVER-BACKFILL")
            driver_id = _driver(conn, company_id)
            checkpoint("DRIVER_SEED_WITHOUT_PHYSICAL_ADMIN_COLUMN")

            _expect_backfill_error(
                lambda: service.report(conn),
                "PRE_CUTOVER_LEGACY_CLASSIFICATION_EVIDENCE_UNAVAILABLE",
            )
            checkpoint("PRE_CUTOVER_CLASSIFICATION_FAILS_CLOSED")

            principal_id, backoffice_user_id = _canonical_owner(conn, company_id, driver_id)
            proposal = service.report(conn)
            assert SECRET not in json.dumps(proposal)
            assert proposal["reviewed"] is False and len(proposal["entries"]) == 1
            entry = proposal["entries"][0]
            assert entry["legacy_driver_id"] == driver_id
            assert entry["classification"] == "BACKOFFICE_ONLY"
            assert entry["company_owner"] is True
            assert entry["backoffice_username"] == "canonical-owner"
            canonical = entry["expected_source"]["canonical_identity"]
            assert canonical["backoffice_principal_id"] == principal_id
            assert canonical["backoffice_user_id"] == backoffice_user_id
            assert "is_admin" not in entry["expected_source"]
            checkpoint("CANONICAL_PERSISTED_EVIDENCE_ONLY")

            document = copy.deepcopy(proposal)
            document["reviewed"] = True
            assert service.validate(conn, document)["status"] == "VALID_EXACT_RERUN"
            before = {
                table: conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                for table in (
                    "company_principals",
                    "backoffice_users",
                    "field_representatives",
                    "company_owners",
                    "identity_legacy_driver_map",
                )
            }
            assert service.apply(conn, document)["status"] == "EXACT_RERUN"
            after = {
                table: conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                for table in before
            }
            assert after == before
            checkpoint("VALIDATE_AND_APPLY_ARE_EXACT_RERUNS")

        _operator_cli(env, cluster, document)
        checkpoint("OPERATOR_CLI_USES_CANONICAL_STATE_ONLY")

        assert "No new upgrade operations detected" in alembic("check")
        assert HEAD in alembic("current")
        checkpoint("ALEMBIC_CURRENT_HEAD_AND_METADATA_DRIFT")
        print(f"CHECKS={len(checks)}", flush=True)
        print("POST_CUTOVER_IDENTITY_BACKFILL_VERDICT=READY", flush=True)
    finally:
        if started:
            fixture_tools.run([pg("pg_ctl"), "-D", str(data), "-m", "fast", "-w", "stop"], pg_ctl=True)
            print("ISOLATED_CLUSTER_STOPPED=PASS", flush=True)
        print(f"EVIDENCE_DIR={cluster}", flush=True)


if __name__ == "__main__":
    main()
