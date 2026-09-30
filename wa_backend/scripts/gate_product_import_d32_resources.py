"""Static/runtime contract for D3.2 bounded Product Import concurrency."""
from __future__ import annotations

from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from config import Config
from domains.simple_products.imports.infrastructure.resource_budget import (
    RESOURCE_BUDGET,
)

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "wa_backend"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


queue = read(
    BACKEND
    / "domains/simple_products/imports/infrastructure/queue.py"
)
worker_cli = read(
    BACKEND
    / "domains/simple_products/imports/infrastructure/worker_cli.py"
)
budget_source = read(
    BACKEND
    / "domains/simple_products/imports/infrastructure/resource_budget.py"
)
operational = read(BACKEND / "workers/app.py")
isolated = read(BACKEND / "scripts/run_product_import_d32_isolated_gate.py")
child = read(BACKEND / "scripts/product_import_d32_isolated_child.py")

checks: list[tuple[str, bool]] = []


def check(label: str, condition: bool) -> None:
    checks.append((label, bool(condition)))


check(
    "deployment budget reserves web operational and Product Import together",
    Config.DB_DEPLOYMENT_RESERVED_CONNECTIONS
    == (
        Config.DB_CONNECTIONS_TOTAL
        + Config.DB_OPERATIONAL_RESERVED_CONNECTIONS
        + Config.PRODUCT_IMPORT_DB_CONNECTION_BUDGET
    )
    and Config.DB_DEPLOYMENT_RESERVED_CONNECTIONS
    <= Config.DB_DEPLOYMENT_CONNECTION_BUDGET,
)
check(
    "operational worker pool uses reviewed Config bounds",
    "min_size=Config.OPERATIONAL_WORKER_DB_POOL_MIN" in operational
    and "max_size=Config.OPERATIONAL_WORKER_DB_POOL_MAX" in operational,
)
check(
    "Product Import queue pool is explicit and bounded",
    "min_size=RESOURCE_BUDGET.queue_pool_min" in queue
    and "max_size=RESOURCE_BUDGET.queue_pool_max" in queue
    and RESOURCE_BUDGET.queue_pool_min == 1
    and RESOURCE_BUDGET.queue_pool_max == 2,
)
check(
    "two execution slots are bounded by tenant DB capacity",
    RESOURCE_BUDGET.execution_slots == 2
    and RESOURCE_BUDGET.execution_slots <= Config.DB_POOL_SIZE
    and "execution > int(Config.DB_POOL_SIZE)" in budget_source,
)
check(
    "Product Import subsystem connection envelope is fail closed",
    RESOURCE_BUDGET.estimated_peak_connections
    <= RESOURCE_BUDGET.connection_budget
    and "estimated > budget" in budget_source,
)
check(
    "same-company serialization remains while cross-company slots can run",
    'lock=f"product-import:{int(company_id)}"' in queue
    and "RESOURCE_BUDGET.slots_for(role)" in worker_cli,
)
check(
    "disposable D3.2 gate proves overlap isolation latency WAL and source safety",
    'for role in ("control", "maintenance", "execution")' in child
    and "cross_company_overlap" in child
    and "same_company_double" in child
    and "short_finished_before_second_long" in child
    and "during_p95_ms" in child
    and "wal_delta_bytes" in child
    and "max_app_connections" in child
    and "WANASAH_D32_DISPOSABLE_CHILD" in child
    and "PRODUCT_IMPORT_D32_ISOLATED_GATE=PASS" in isolated
    and "_verify_source_still_empty" in isolated
    and "127.0.0.1" in isolated
    and "55442" in isolated,
)

failures = [label for label, passed in checks if not passed]
for label, passed in checks:
    print(("[PASS] " if passed else "[FAIL] ") + label)
print(f"CHECKS={len(checks)}")
print(f"FAILURES={len(failures)}")
for failure in failures:
    print("FAILED_CHECK=" + failure)
if failures:
    raise SystemExit(1)
print("PRODUCT_IMPORT_D32_RESOURCE_GATE=PASS")
