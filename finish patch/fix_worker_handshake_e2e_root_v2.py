from pathlib import Path

TARGET = Path(__file__).resolve().parent / "worker_handshake_e2e.py"

if not TARGET.exists():
    raise SystemExit(
        "PATCH_ABORTED: worker_handshake_e2e.py not found in project root."
    )

text = TARGET.read_text(encoding="utf-8")

OLD1 = 'import asyncio\nimport os\nimport sys\nfrom datetime import datetime, timedelta, timezone\n\nimport asyncpg\nfrom dotenv import load_dotenv\n\nload_dotenv(override=True)\n\nAPP_URL = os.getenv("DATABASE_URL")\nMIGRATION_URL = os.getenv("DATABASE_URL_MIGRATION")\n'
NEW1 = 'import asyncio\nimport os\nimport sys\nfrom pathlib import Path\nfrom datetime import datetime, timedelta, timezone\n\nimport asyncpg\nfrom dotenv import load_dotenv\n\nROOT = Path(__file__).resolve().parent\nBACKEND = ROOT / "wa_backend"\n\nif str(BACKEND) not in sys.path:\n    sys.path.insert(0, str(BACKEND))\n\nload_dotenv(BACKEND / ".env", override=True)\n\nAPP_URL = os.getenv("DATABASE_URL")\nMIGRATION_URL = os.getenv("DATABASE_URL_MIGRATION")\n'
OLD2 = 'COMMANDS = {\n    "setup": setup,\n    "verify-warning": verify_warning,\n    "escalate": escalate,\n    "verify-critical": verify_critical,\n    "verify-no-duplicates": verify_no_duplicates,\n    "cleanup": cleanup,\n}\n\n\nasync def main():\n    if len(sys.argv) != 2 or sys.argv[1] not in COMMANDS:\n        print("Usage:")\n        for command in COMMANDS:\n            print(f"  python worker_handshake_e2e.py {command}")\n        raise SystemExit(2)\n\n    await COMMANDS[sys.argv[1]]()\n'
NEW2 = 'async def defer_company(company_id: int):\n    from workers.tasks.handshake import scan_company_stale_handshakes\n\n    job = await scan_company_stale_handshakes.defer_async(\n        company_id=int(company_id)\n    )\n    print(\n        f"HANDSHAKE_E2E_DEFER_COMPANY=OK "\n        f"company_id={int(company_id)} job_id={job.id}"\n    )\n\n\nasync def defer_all():\n    from workers.tasks.handshake import scan_all_stale_handshakes\n\n    job = await scan_all_stale_handshakes.defer_async()\n    print(f"HANDSHAKE_E2E_DEFER_ALL=OK job_id={job.id}")\n\n\nCOMMANDS = {\n    "setup": setup,\n    "verify-warning": verify_warning,\n    "escalate": escalate,\n    "verify-critical": verify_critical,\n    "verify-no-duplicates": verify_no_duplicates,\n    "cleanup": cleanup,\n    "defer-all": defer_all,\n}\n\n\nasync def main():\n    if len(sys.argv) >= 2 and sys.argv[1] == "defer-company":\n        if len(sys.argv) != 3:\n            raise SystemExit(\n                "Usage: python worker_handshake_e2e.py "\n                "defer-company <company_id>"\n            )\n        await defer_company(int(sys.argv[2]))\n        return\n\n    if len(sys.argv) != 2 or sys.argv[1] not in COMMANDS:\n        print("Usage:")\n        for command in COMMANDS:\n            print(f"  python worker_handshake_e2e.py {command}")\n        print("  python worker_handshake_e2e.py defer-company <company_id>")\n        raise SystemExit(2)\n\n    await COMMANDS[sys.argv[1]]()\n'

if text.count(OLD1) != 1:
    raise SystemExit(
        f"PATCH_ABORTED: expected env/import block once, found {text.count(OLD1)}."
    )
text = text.replace(OLD1, NEW1, 1)

if text.count(OLD2) != 1:
    raise SystemExit(
        f"PATCH_ABORTED: expected command/main block once, found {text.count(OLD2)}."
    )
text = text.replace(OLD2, NEW2, 1)

TARGET.write_text(text, encoding="utf-8")

print("WORKER_HANDSHAKE_E2E_ROOT_V2_PATCH=OK")
print("DOTENV_SOURCE=wa_backend/.env")
print("JSON_CLI_DEPENDENCY=REMOVED_FOR_E2E")
print("RUN_FROM_PROJECT_ROOT=OK")
