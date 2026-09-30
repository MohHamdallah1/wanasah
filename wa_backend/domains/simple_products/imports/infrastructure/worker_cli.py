"""One foreground process per isolated Product Import workload role."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import logging
import os
from pathlib import Path
import subprocess
import sys

from domains.simple_products.imports.infrastructure.queue_topology import ROLE_QUEUES
from domains.simple_products.imports.infrastructure.resource_budget import (
    RESOURCE_BUDGET,
)


def code_identity() -> tuple[str, str]:
    backend = Path(__file__).resolve().parents[4]
    revision = os.environ.get("WANASAH_RELEASE_COMMIT", "").strip()
    if not revision:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=backend, capture_output=True,
            text=True, check=True,
        ).stdout.strip()
    if len(revision) != 40 or any(c not in "0123456789abcdef" for c in revision.lower()):
        raise RuntimeError("Worker release must identify a full Git commit SHA.")
    # Include domain, worker and root backend Python modules, including lazy
    # imports, rather than identifying only this launcher's source.
    # Deployment must keep this checkout immutable for the process lifetime.
    roots = [backend / "domains", backend / "workers"]
    paths = sorted(
        [p for root in roots for p in root.rglob("*.py")]
        + list(backend.glob("*.py"))
    )
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.relative_to(backend).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return revision, digest.hexdigest()


async def run(role: str) -> None:
    # Tag libpq/psycopg connections per role for pg_stat_activity diagnosis.
    os.environ["PGAPPNAME"] = f"wanasah-product-import-{role}"
    from domains.simple_products.imports.infrastructure.queue import (
        app,
        recover_stalled_product_imports,
    )

    slots = RESOURCE_BUDGET.slots_for(role)
    revision, digest = code_identity()
    logging.getLogger(__name__).info(
        "PRODUCT_IMPORT_WORKER_CODE pid=%s role=%s queue=%s slots=%s "
        "queue_pool=%s..%s db_envelope=%s/%s commit=%s source_sha256=%s",
        os.getpid(), role, ROLE_QUEUES[role], slots,
        RESOURCE_BUDGET.queue_pool_min, RESOURCE_BUDGET.queue_pool_max,
        RESOURCE_BUDGET.estimated_peak_connections,
        RESOURCE_BUDGET.connection_budget,
        revision, digest,
    )
    async with app.open_async():
        result = await recover_stalled_product_imports()
        logging.getLogger(__name__).info("WORKER_STARTUP_RECOVERY=%s", result)
        await app.run_worker_async(
            queues=[ROLE_QUEUES[role]], concurrency=slots,
            name=f"product-import-{role}:{revision[:12]}:{digest[:12]}",
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", choices=tuple(ROLE_QUEUES), required=True)
    parser.add_argument("--print-code-identity", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    if args.print_code_identity:
        revision, digest = code_identity()
        print(f"commit={revision} source_sha256={digest}")
        return
    if sys.platform == "win32":
        asyncio.run(run(args.role), loop_factory=asyncio.SelectorEventLoop)
    else:
        asyncio.run(run(args.role))


if __name__ == "__main__":
    main()
