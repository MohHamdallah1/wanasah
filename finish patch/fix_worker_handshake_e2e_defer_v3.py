from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "worker_handshake_e2e.py"

if not TARGET.exists():
    raise SystemExit("PATCH_ABORTED: worker_handshake_e2e.py must be in project root.")

text = TARGET.read_text(encoding="utf-8")

OLD = 'async def defer_company(company_id: int):\n    from workers.tasks.handshake import scan_company_stale_handshakes\n\n    job = await scan_company_stale_handshakes.defer_async(\n        company_id=int(company_id)\n    )\n    print(\n        f"HANDSHAKE_E2E_DEFER_COMPANY=OK "\n        f"company_id={int(company_id)} job_id={job.id}"\n    )\n\n\nasync def defer_all():\n    from workers.tasks.handshake import scan_all_stale_handshakes\n\n    job = await scan_all_stale_handshakes.defer_async()\n    print(f"HANDSHAKE_E2E_DEFER_ALL=OK job_id={job.id}")\n'
NEW = 'async def defer_company(company_id: int):\n    from workers.app import app\n    from workers.tasks.handshake import scan_company_stale_handshakes\n\n    async with app.open_async():\n        job = await scan_company_stale_handshakes.defer_async(\n            company_id=int(company_id)\n        )\n    print(\n        f"HANDSHAKE_E2E_DEFER_COMPANY=OK "\n        f"company_id={int(company_id)} job_id={job.id}"\n    )\n\n\nasync def defer_all():\n    from workers.app import app\n    from workers.tasks.handshake import scan_all_stale_handshakes\n\n    async with app.open_async():\n        job = await scan_all_stale_handshakes.defer_async()\n    print(f"HANDSHAKE_E2E_DEFER_ALL=OK job_id={job.id}")\n'

if NEW in text:
    print("ALREADY_PATCHED=worker_handshake_e2e.py")
elif text.count(OLD) == 1:
    TARGET.write_text(text.replace(OLD, NEW, 1), encoding="utf-8")
    print("PATCHED=worker_handshake_e2e.py")
else:
    raise SystemExit(
        f"PATCH_ABORTED: expected old defer block once, found {text.count(OLD)}."
    )

ast.parse(TARGET.read_text(encoding="utf-8"), filename=str(TARGET))

final = TARGET.read_text(encoding="utf-8")
assert "async with app.open_async():" in final
assert final.count("async with app.open_async():") >= 2

print("E2E_DEFER_APP_OPEN=OK")
print("RUN_FROM_PROJECT_ROOT=OK")
