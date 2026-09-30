"""D8 backup AND full disposable restore regression; never uses customer data.

Runs a brand-new local PG16 cluster on a checked-free loopback port.
This test uses a tiny synthetic table instead of a development/customer dump.
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT
BASH = Path(r"C:\Program Files\Git\bin\bash.exe")
PG = Path(r"C:\Program Files\PostgreSQL\16\bin")
PORT = 55447
OWNER = "wanasah_restore_gate"


def run(args, *, env=None, check=True, capture=True):
    # pg_ctl on Windows can leave stdout pipe handles open in its child
    # PostgreSQL server. Avoid capturing either pipe on start/stop.
    result = subprocess.run(
        [str(x) for x in args],
        cwd=BACKEND, env=env, text=True,
        stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
        stderr=subprocess.PIPE if capture else subprocess.DEVNULL,
        timeout=90, check=False,
    )
    if check and result.returncode:
        raise RuntimeError(
            f"D8 restore gate command failed ({Path(str(args[0])).name}): "
            + (result.stderr or result.stdout)[-1500:]
        )
    return result


def bash_path(path: Path) -> str:
    return run([BASH, "-c", 'cygpath -u "$1"', "bash", path]).stdout.strip()


def pg_cmd(binary: str):
    return PG / (binary + ".exe")


def main():
    if os.getenv("WANASAH_D8_DISPOSABLE_GATE") != "1":
        raise RuntimeError("Explicit WANASAH_D8_DISPOSABLE_GATE=1 required")
    for x in (BASH, pg_cmd("initdb"), pg_cmd("pg_ctl"), pg_cmd("createdb"),
              pg_cmd("psql"), pg_cmd("pg_restore"), pg_cmd("pg_dump")):
        if not x.is_file():
            raise RuntimeError(f"D8 required local tool missing: {x.name}")

    for script in ("backup_db.sh", "verify_restore_backup.sh"):
        r = run([BASH, "-n", BACKEND / "scripts" / script])
        if r.returncode:
            raise RuntimeError(f"Cannot parse {script}")

    with socket.socket() as sock:
        if sock.connect_ex(("127.0.0.1", PORT)) == 0:
            raise RuntimeError("Disposable D8 port already in use; refusing")
    root = Path(tempfile.mkdtemp(prefix="wanasah_d8_backup_restore_"))
    started = False
    try:
        data = root / "pgdata"
        run([pg_cmd("initdb"), "-D", data, "-U", OWNER,
             "-A", "trust", "-E", "UTF8", "--no-instructions"])
        run([pg_cmd("pg_ctl"), "-D", data,
             "-l", root / "postgres.log",
             "-o", f"-p {PORT} -h 127.0.0.1", "-w", "start"], capture=False)
        started = True
        run([pg_cmd("createdb"), "-h", "127.0.0.1", "-p", PORT,
             "-U", OWNER, "wanasah_backup_probe"])
        run([pg_cmd("psql"), "-X", "-v", "ON_ERROR_STOP=1",
             "-h", "127.0.0.1", "-p", PORT, "-U", OWNER,
             "-d", "wanasah_backup_probe",
             "-c", "CREATE TABLE backup_probe "
                   "(id bigint PRIMARY KEY, label text NOT NULL); "
                   "INSERT INTO backup_probe VALUES "
                   "(1,'synthetic-one'),(2,'synthetic-two'),(3,'synthetic-three')"])

        env = os.environ.copy()
        env["PATH"] = str(PG) + os.pathsep + env["PATH"]
        env.update({
            "POSTGRES_DB": "wanasah_backup_probe",
            "POSTGRES_USER": OWNER,
            "POSTGRES_HOST": "127.0.0.1",
            "POSTGRES_PORT": str(PORT),
            "BACKUP_DIR": bash_path(root / "backups"),
            "RETENTION_DAYS": "30",
            "RESTORE_HOST": "127.0.0.1",
            "RESTORE_PORT": str(PORT),
            "RESTORE_USER": OWNER,
            "RESTORE_EXPECTED_TABLE": "backup_probe",
            "RESTORE_EXPECTED_ROWS": "3",
        })

        backup = run([BASH, bash_path(BACKEND / "scripts" / "backup_db.sh")], env=env)
        dumps = list((root / "backups").glob("wanasah_backup_*.dump"))
        if len(dumps) != 1 or dumps[0].stat().st_size < 64:
            raise AssertionError("D8 atomic backup not present exactly once")
        if list((root / "backups").glob(".wanasah_backup_*")):
            raise AssertionError("D8 partial backup leaked into retention folder")
        good = run([BASH, bash_path(BACKEND / "scripts" / "verify_restore_backup.sh"),
                    bash_path(dumps[0])], env=env)
        if "FULL_RESTORE_GATE=PASS" not in good.stdout:
            raise AssertionError("D8 full restore result not confirmed")
        if "rows=3" not in good.stdout:
            raise AssertionError("D8 restored data did not preserve all rows")
        leftovers = run([pg_cmd("psql"), "-X", "-At", "-h", "127.0.0.1",
                         "-p", PORT, "-U", OWNER, "-d", "postgres",
                         "-c", "SELECT count(*) FROM pg_database "
                               "WHERE datname LIKE 'wanasah_restore_verify_%'"])
        if leftovers.stdout.strip() != "0":
            raise AssertionError("D8 disposable restore database not cleaned")

        bad_env = env.copy()
        bad_env["RETENTION_DAYS"] = "0"
        bad = run([BASH, bash_path(BACKEND / "scripts" / "backup_db.sh")],
                  env=bad_env, check=False)
        if bad.returncode == 0 or len(list((root/"backups").glob("*.dump"))) != 1:
            raise AssertionError("D8 bad retention setting failed to close safely")
        corrupted = root / "not_a_dump.dump"
        corrupted.write_bytes(b"not a PostgreSQL archive")
        fail = run([BASH, bash_path(BACKEND / "scripts" /
                                    "verify_restore_backup.sh"),
                    bash_path(corrupted)], env=env, check=False)
        if fail.returncode == 0:
            raise AssertionError("D8 corrupted archive was falsely accepted")

        print("D8_CUSTOM_ARCHIVE_AND_ATOMIC_PUBLISH=PASS")
        print("D8_FULL_ISOLATED_RESTORE_3_ROWS=PASS")
        print("D8_NO_RESTORE_RESIDUE=PASS")
        print("D8_BAD_RETENTION_FAIL_CLOSED=PASS")
        print("D8_CORRUPT_ARCHIVE_FAIL_CLOSED=PASS")
        print("D8_BACKUP_RESTORE_DISPOSABLE_GATE=PASS")
    finally:
        if started or (root / "pgdata" / "postmaster.pid").exists():
            try:
                run([pg_cmd("pg_ctl"), "-D", root / "pgdata",
                     "-m", "fast", "-w", "stop"], capture=False)
            except Exception as exc:
                # Do not delete files of a cluster still running.
                raise RuntimeError("Failed to stop D8 disposable PostgreSQL") from exc
        shutil.rmtree(root)


if __name__ == "__main__":
    main()
