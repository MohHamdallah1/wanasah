from __future__ import annotations

import asyncio
import selectors
import sys
from datetime import date
from pathlib import Path

from sqlalchemy import select, text, update

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from context import tenant_context  # noqa: E402
from database import AsyncSessionLocal  # noqa: E402
from domains.live_stock_projection.service import (  # noqa: E402
    apply_live_stock_active_variant_delta,
    refresh_due_live_stock_transitions,
    refresh_live_stock_keys,
)
from models import (  # noqa: E402
    InventoryLiveStockCompanySummary,
    InventoryLocation,
)
from product_import_queue import (  # noqa: E402
    PRODUCT_IMPORT_STALLED_ALLOWLIST,
    PRODUCT_IMPORT_STALLED_TIMEOUT_SECONDS,
    app as product_import_app,
)
from scripts import gate_stage821_live_stock_projector_runtime as fixture  # noqa: E402
from workers.app import (  # noqa: E402
    STALLED_WORKER_TIMEOUT_SECONDS,
    app as operational_app,
)
from workers.recovery import recover_safe_stalled_jobs  # noqa: E402
from workers.scheduling import (  # noqa: E402
    defer_unique_company_jobs,
    iter_active_company_id_pages,
)
from workers.tasks import live_stock as live_stock_tasks  # noqa: E402
from workers.tasks.maintenance import STALLED_RETRY_ALLOWLIST  # noqa: E402
from workers.tenant import acquire_tenant_job_lock, tenant_session  # noqa: E402


RESULTS: list[tuple[str, bool, str]] = []
GATE_QUEUE = "gate-worker-foundation"
OPERATIONAL_GATE_WORKER_ID = -91001
PRODUCT_GATE_WORKER_ID = -92001


@operational_app.task(
    name="gate.worker.company_scope",
    queue=GATE_QUEUE,
)
async def gate_company_scope_task(company_id: int) -> dict[str, int]:
    return {"company_id": int(company_id)}


def record(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))
    print(
        f"[{'PASS' if ok else 'FAIL'}] {name}"
        + (f" — {detail}" if detail else "")
    )


async def cleanup_queue_residue() -> None:
    async with fixture.SessionSU() as su:
        await su.begin()
        await su.execute(
            text(
                "DELETE FROM worker_queue.procrastinate_jobs "
                "WHERE queue_name=:queue"
            ),
            {"queue": GATE_QUEUE},
        )
        await su.execute(
            text(
                "DELETE FROM worker_queue.procrastinate_workers "
                "WHERE id=:worker_id"
            ),
            {"worker_id": OPERATIONAL_GATE_WORKER_ID},
        )
        await su.execute(
            text(
                "DELETE FROM public.procrastinate_jobs "
                "WHERE queue_name=:queue"
            ),
            {"queue": GATE_QUEUE},
        )
        await su.execute(
            text(
                "DELETE FROM public.procrastinate_workers "
                "WHERE id=:worker_id"
            ),
            {"worker_id": PRODUCT_GATE_WORKER_ID},
        )
        await su.commit()


async def build_projection(
    *,
    company_id: int,
    warehouse_id: int,
    variant_id: int,
    as_of: date,
) -> None:
    async with fixture.SessionApp() as db:
        await db.begin()
        await fixture.set_tenant(db, company_id)
        await refresh_live_stock_keys(
            db,
            company_id=company_id,
            keys=[(warehouse_id, variant_id)],
            computed_for_date=as_of,
        )
        await apply_live_stock_active_variant_delta(
            db,
            company_id=company_id,
            delta=0,
        )
        await db.commit()


async def company_summary(company_id: int) -> tuple[str, int]:
    async with tenant_session(company_id) as db:
        row = (
            await db.execute(
                select(
                    InventoryLiveStockCompanySummary.projection_state,
                    InventoryLiveStockCompanySummary.revision,
                ).where(
                    InventoryLiveStockCompanySummary.company_id
                    == int(company_id)
                )
            )
        ).one()
        await db.rollback()
        return str(row.projection_state), int(row.revision)


async def seed_operational_recovery_jobs() -> dict[str, int]:
    async with fixture.SessionSU() as su:
        await su.begin()
        await su.execute(
            text(
                """
                INSERT INTO worker_queue.procrastinate_workers
                    (id, last_heartbeat)
                OVERRIDING SYSTEM VALUE
                VALUES (:worker_id, NOW() - INTERVAL '5 minutes')
                """
            ),
            {"worker_id": OPERATIONAL_GATE_WORKER_ID},
        )

        async def insert_job(
            *,
            task_name: str,
            lock_name: str,
            queueing_lock: str | None = None,
            status: str = "doing",
            worker_id: int | None = OPERATIONAL_GATE_WORKER_ID,
        ) -> int:
            return int(
                (
                    await su.execute(
                        text(
                            """
                            INSERT INTO worker_queue.procrastinate_jobs
                                (queue_name, task_name, lock, queueing_lock,
                                 args, status, worker_id, scheduled_at)
                            VALUES
                                (:queue, :task_name, :lock_name,
                                 :queueing_lock, '{}'::jsonb,
                                 CAST(:status AS worker_queue.procrastinate_job_status),
                                 :worker_id, NOW())
                            RETURNING id
                            """
                        ),
                        {
                            "queue": GATE_QUEUE,
                            "task_name": task_name,
                            "lock_name": lock_name,
                            "queueing_lock": queueing_lock,
                            "status": status,
                            "worker_id": worker_id,
                        },
                    )
                ).scalar_one()
            )

        safe = await insert_job(
            task_name="wanasah.worker_healthcheck",
            lock_name="gate-worker-foundation:safe",
        )
        unsafe = await insert_job(
            task_name="gate.worker.unsafe",
            lock_name="gate-worker-foundation:unsafe",
        )
        periodic_stalled = await insert_job(
            task_name="wanasah.retry_safe_stalled_jobs",
            lock_name="gate-worker-foundation:periodic",
            queueing_lock="gate-worker-foundation:periodic",
        )
        periodic_successor = await insert_job(
            task_name="wanasah.retry_safe_stalled_jobs",
            lock_name="gate-worker-foundation:periodic",
            queueing_lock="gate-worker-foundation:periodic",
            status="todo",
            worker_id=None,
        )
        await su.commit()
        return {
            "safe": safe,
            "unsafe": unsafe,
            "periodic_stalled": periodic_stalled,
            "periodic_successor": periodic_successor,
        }


async def seed_product_recovery_job() -> int:
    async with fixture.SessionSU() as su:
        await su.begin()
        await su.execute(
            text(
                """
                INSERT INTO public.procrastinate_workers
                    (id, last_heartbeat)
                OVERRIDING SYSTEM VALUE
                VALUES (:worker_id, NOW() - INTERVAL '5 minutes')
                """
            ),
            {"worker_id": PRODUCT_GATE_WORKER_ID},
        )
        job_id = int(
            (
                await su.execute(
                    text(
                        """
                        INSERT INTO public.procrastinate_jobs
                            (queue_name, task_name, lock, args, status,
                             worker_id, scheduled_at)
                        VALUES
                            (:queue, 'wanasah.process_product_import',
                             'gate-worker-foundation:product-import',
                             '{}'::jsonb, 'doing',
                             :worker_id, NOW())
                        RETURNING id
                        """
                    ),
                    {
                        "queue": GATE_QUEUE,
                        "worker_id": PRODUCT_GATE_WORKER_ID,
                    },
                )
            ).scalar_one()
        )
        await su.commit()
        return job_id


async def job_states(
    *,
    schema: str,
    job_ids: list[int],
) -> dict[int, tuple[str, int | None]]:
    async with fixture.SessionSU() as su:
        await su.begin()
        rows = (
            await su.execute(
                text(
                    f"""
                    SELECT id, status::text, worker_id
                    FROM {schema}.procrastinate_jobs
                    WHERE id = ANY(CAST(:ids AS bigint[]))
                    ORDER BY id
                    """
                ),
                {"ids": job_ids},
            )
        ).all()
        await su.rollback()
    return {
        int(row.id): (
            str(row.status),
            int(row.worker_id) if row.worker_id is not None else None,
        )
        for row in rows
    }


async def run() -> None:
    ids: dict[str, int] | None = None
    original_refresh = live_stock_tasks.refresh_due_live_stock_transitions

    try:
        await cleanup_queue_residue()
        await fixture.cleanup_test_companies()
        ids = await fixture.seed()

        a = int(ids["a"])
        b = int(ids["b"])
        a_wh = int(ids["a_wh"])
        b_wh = int(ids["b_wh"])
        a_variant = int(ids["a_variant"])
        b_variant = int(ids["b_variant"])
        as_of = date.fromordinal(int(ids["as_of_ordinal"]))

        await build_projection(
            company_id=a,
            warehouse_id=a_wh,
            variant_id=a_variant,
            as_of=as_of,
        )
        await build_projection(
            company_id=b,
            warehouse_id=b_wh,
            variant_id=b_variant,
            as_of=as_of,
        )

        before_context = tenant_context.get()
        async with tenant_session(a) as db:
            own_location = await db.scalar(
                select(InventoryLocation.id).where(
                    InventoryLocation.id == a_wh
                )
            )
            foreign_location = await db.scalar(
                select(InventoryLocation.id).where(
                    InventoryLocation.id == b_wh
                )
            )
            foreign_update = await db.execute(
                update(InventoryLocation)
                .where(InventoryLocation.id == b_wh)
                .values(name="WORKER_GATE_MUST_NOT_WRITE")
            )
            await db.rollback()

        record(
            "tenant worker session sees own warehouse and hides foreign warehouse",
            own_location == a_wh and foreign_location is None,
            f"own={own_location} foreign={foreign_location}",
        )
        record(
            "tenant worker session cannot mutate foreign warehouse",
            int(foreign_update.rowcount or 0) == 0,
            f"rowcount={foreign_update.rowcount}",
        )
        record(
            "tenant context is restored after worker session",
            tenant_context.get() == before_context,
            f"before={before_context!r} after={tenant_context.get()!r}",
        )

        async with AsyncSessionLocal() as db:
            leaked_location = await db.scalar(
                select(InventoryLocation.id).where(
                    InventoryLocation.id == a_wh
                )
            )
            if db.in_transaction():
                await db.rollback()
        record(
            "tenant connection state is cleared before pool reuse",
            leaked_location is None,
            f"tenantless_visible={leaked_location}",
        )

        async with tenant_session(a) as first:
            await acquire_tenant_job_lock(
                first,
                namespace="gate-worker-lock",
                company_id=a,
            )
            async with tenant_session(a) as second:
                same_lock = bool(
                    await second.scalar(
                        text(
                            "SELECT pg_try_advisory_xact_lock("
                            "hashtext(:namespace), :company_id)"
                        ),
                        {"namespace": "gate-worker-lock", "company_id": a},
                    )
                )
                other_company_lock = bool(
                    await second.scalar(
                        text(
                            "SELECT pg_try_advisory_xact_lock("
                            "hashtext(:namespace), :company_id)"
                        ),
                        {"namespace": "gate-worker-lock", "company_id": b},
                    )
                )
                other_namespace_lock = bool(
                    await second.scalar(
                        text(
                            "SELECT pg_try_advisory_xact_lock("
                            "hashtext(:namespace), :company_id)"
                        ),
                        {
                            "namespace": "gate-worker-lock-other",
                            "company_id": a,
                        },
                    )
                )
                await second.rollback()
            await first.rollback()

        record(
            "tenant advisory lock serializes same company and namespace",
            same_lock is False,
            f"same_lock_acquired={same_lock}",
        )
        record(
            "tenant advisory locks stay independent across company or namespace",
            other_company_lock and other_namespace_lock,
            (
                f"other_company={other_company_lock} "
                f"other_namespace={other_namespace_lock}"
            ),
        )

        b_state_before, b_revision_before = await company_summary(b)
        async with tenant_session(a) as db:
            foreign_refresh = await refresh_due_live_stock_transitions(
                db,
                company_id=a,
                warehouse_location_id=b_wh,
                as_of_date=as_of,
                limit=100,
            )
            await db.commit()
        b_state_after, b_revision_after = await company_summary(b)
        record(
            "warehouse-scoped maintenance cannot cross the tenant boundary",
            (
                foreign_refresh == 0
                and b_state_after == b_state_before
                and b_revision_after == b_revision_before
            ),
            (
                f"foreign_refresh={foreign_refresh} "
                f"b_state={b_state_before}->{b_state_after} "
                f"b_revision={b_revision_before}->{b_revision_after}"
            ),
        )

        async with operational_app.open_async():
            deferred_1, skipped_1 = await defer_unique_company_jobs(
                gate_company_scope_task,
                lock_namespace="gate-worker-foundation-company",
                company_ids=[a],
            )
            deferred_2, skipped_2 = await defer_unique_company_jobs(
                gate_company_scope_task,
                lock_namespace="gate-worker-foundation-company",
                company_ids=[a],
            )
            active = list(
                await operational_app.job_manager.list_jobs_async(
                    lock=f"gate-worker-foundation-company:{a}",
                )
            )
            active = [
                job
                for job in active
                if str(job.status) in {"todo", "doing"}
            ]
            record(
                "company job scheduling prevents duplicate TODO/DOING backlog",
                (
                    deferred_1 == 1
                    and skipped_1 == 0
                    and deferred_2 == 0
                    and skipped_2 == 1
                    and len(active) == 1
                    and active[0].queueing_lock is None
                ),
                (
                    f"first=({deferred_1},{skipped_1}) "
                    f"second=({deferred_2},{skipped_2}) "
                    f"active={len(active)}"
                ),
            )

        async with fixture.SessionSU() as su:
            await su.begin()
            await su.execute(
                text(
                    "UPDATE companies SET is_active=false WHERE id=:company_id"
                ),
                {"company_id": b},
            )
            await su.commit()

        active_ids: set[int] = set()
        async for page in iter_active_company_id_pages(page_size=250):
            active_ids.update(page)
        record(
            "global worker scans are bounded and skip inactive tenants",
            a in active_ids and b not in active_ids,
            f"active_a={a in active_ids} inactive_b_visible={b in active_ids}",
        )

        recovery_jobs = await seed_operational_recovery_jobs()
        async with operational_app.open_async():
            recovery = await recover_safe_stalled_jobs(
                operational_app,
                allowlist=STALLED_RETRY_ALLOWLIST,
                seconds_since_heartbeat=STALLED_WORKER_TIMEOUT_SECONDS,
            )

        states = await job_states(
            schema="worker_queue",
            job_ids=list(recovery_jobs.values()),
        )
        record(
            "stalled allowlisted operational job is retried",
            states[recovery_jobs["safe"]][0] == "todo",
            f"status={states[recovery_jobs['safe']][0]} recovery={recovery}",
        )
        record(
            "stalled non-allowlisted operational job is not retried",
            states[recovery_jobs["unsafe"]][0] == "doing",
            f"status={states[recovery_jobs['unsafe']][0]}",
        )
        record(
            "stalled periodic job with queued successor recovers without queueing-lock collision",
            (
                states[recovery_jobs["periodic_stalled"]][0] == "failed"
                and states[recovery_jobs["periodic_successor"]][0] == "todo"
                and recovery["superseded_by_queued"] >= 1
            ),
            (
                f"stalled={states[recovery_jobs['periodic_stalled']][0]} "
                f"successor={states[recovery_jobs['periodic_successor']][0]} "
                f"recovery={recovery}"
            ),
        )

        product_job = await seed_product_recovery_job()
        async with product_import_app.open_async():
            product_recovery = await recover_safe_stalled_jobs(
                product_import_app,
                allowlist=PRODUCT_IMPORT_STALLED_ALLOWLIST,
                seconds_since_heartbeat=PRODUCT_IMPORT_STALLED_TIMEOUT_SECONDS,
            )
        product_state = await job_states(
            schema="public",
            job_ids=[product_job],
        )
        record(
            "product-import process crash is recoverable on its separate queue app",
            product_state[product_job][0] == "todo",
            (
                f"status={product_state[product_job][0]} "
                f"recovery={product_recovery}"
            ),
        )

        async def forced_refresh_failure(*args, **kwargs):
            raise RuntimeError("WORKER_FOUNDATION_FORCED_REFRESH_FAILURE")

        live_stock_tasks.refresh_due_live_stock_transitions = (
            forced_refresh_failure
        )
        failure_seen = False
        try:
            await live_stock_tasks.run_company_live_stock_transition_maintenance(
                a
            )
        except RuntimeError as exc:
            failure_seen = (
                str(exc) == "WORKER_FOUNDATION_FORCED_REFRESH_FAILURE"
            )
        finally:
            live_stock_tasks.refresh_due_live_stock_transitions = original_refresh

        degraded_state, _ = await company_summary(a)
        b_state_during_failure, b_revision_during_failure = await company_summary(
            b
        )
        record(
            "Live Stock worker failure fails closed to DEGRADED",
            failure_seen and degraded_state == "DEGRADED",
            f"failure_seen={failure_seen} state={degraded_state}",
        )
        record(
            "Live Stock worker failure does not degrade another company",
            (
                b_state_during_failure == b_state_after
                and b_revision_during_failure == b_revision_after
            ),
            (
                f"b_state={b_state_after}->{b_state_during_failure} "
                f"b_revision={b_revision_after}->{b_revision_during_failure}"
            ),
        )

        recovered = (
            await live_stock_tasks.run_company_live_stock_transition_maintenance(
                a
            )
        )
        ready_state, _ = await company_summary(a)
        record(
            "Live Stock worker recovers DEGRADED projection back to READY",
            bool(recovered.get("recovered")) and ready_state == "READY",
            f"result={recovered} state={ready_state}",
        )

    finally:
        live_stock_tasks.refresh_due_live_stock_transitions = original_refresh
        await cleanup_queue_residue()
        await fixture.cleanup_test_companies()
        await fixture.engine_app.dispose()
        await fixture.engine_su.dispose()

    failed = [name for name, ok, _ in RESULTS if not ok]
    print(f"CHECKS={len(RESULTS)}")
    print(f"FAILURES={len(failed)}")
    for name in failed:
        print(f"FAILED_CHECK={name}")
    if failed:
        print("WORKER_FOUNDATION_RUNTIME_GATE=FAIL")
        raise SystemExit(1)
    print("WORKER_FOUNDATION_RUNTIME_GATE=PASS")


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.run(
            run(),
            loop_factory=lambda: asyncio.SelectorEventLoop(
                selectors.SelectSelector()
            ),
        )
    else:
        asyncio.run(run())
