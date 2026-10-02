"""Opt-in, transaction-local Product Import execution evidence.

No global engine/session hooks, SQL text, parameters or business object identities.
The caller owns transactions; this observer only uses SQLAlchemy public events.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from hashlib import sha256
import json
import logging
import os
from time import perf_counter
from typing import Any
from uuid import UUID

from sqlalchemy import event


logger = logging.getLogger("wanasah_logger")
_PROFILE_KEY = "simple_products_import_batch_profile"
# Bound per-statement detail even when a 200-row batch splits after row errors.
_MAX_SQL_STATEMENT_DETAILS = 256
# Only explicitly registered static labels may appear in product-import logs.
# Pricing attaches the option to existing statements without importing this module.
_IMPORT_SQL_LABEL_OPTION = "wanasah_sql_trace_label"
_IMPORT_SQL_LABELS = frozenset({
    "pricing_company_lock", "pricing_maker_checker", "pricing_next_revision",
    "simple_pricing_policy_assignments", "simple_pricing_company_default_book",
    "pricing_book_lock", "pricing_book_lock_next_revision", "pricing_book_read",
    "pricing_draft_publication_lock",
    "pricing_draft_variants", "pricing_draft_uoms",
    "pricing_draft_variant_uom", "pricing_initial_variant_uom_history",
    "pricing_publish_publication_lock", "pricing_publish_entries_lock",
    "pricing_publish_entries_variant_uom",
    "pricing_publish_variants", "pricing_publish_uoms",
    "pricing_publish_variant_uom",
    "pricing_predecessor_exists", "pricing_locked_context_check",
    "pricing_close_previous_ranges", "pricing_effectivity_overlap_check",
    "pricing_publish_entry_update", "pricing_supersede_publications",
})
_SQL_OPERATION_LABELS = frozenset({
    "SELECT", "INSERT", "UPDATE", "DELETE", "WITH", "SAVEPOINT",
    "RELEASE", "ROLLBACK", "SET", "SHOW", "COMMIT",
})
_PHASES = frozenset({
    "session_open_rls", "batch_other", "input_python", "idempotency",
    "product_structures", "barcode_python", "variant_objects",
    "activation_objects", "family_flush", "draft_flush", "activation_flush",
    "pricing_policy", "price_publication_create", "price_entries_python",
    "price_draft_entries", "price_publish", "savepoint_attempt",
    "row_outcome_python", "commit", "rollback", "session_close",
})
_OBJECTS = (
    "Product", "ProductVariant", "ProductUomConversion", "ProductBarcode",
    "DomainAuditEvent", "TransactionalOutbox", "PriceBook", "PricePublication",
    "PriceBookEntry", "PriceBookAssignment", "OperationIdempotency",
    "InventoryLiveStockCompanySummary", "other",
)


def profile_every_n_batches() -> int:
    """Read once per execution invocation. Invalid/unset values disable profiling."""
    value = os.environ.get("PRODUCT_IMPORT_PROFILE_EVERY_N_BATCHES", "0")
    if not value.isascii() or not value.isdecimal() or len(value) > 7:
        return 0
    interval = int(value)
    return interval if 0 <= interval <= 1_000_000 else 0


def batch_profile(db: Any) -> ImportBatchProfile | None:
    session = getattr(db, "sync_session", None)
    return session.info.get(_PROFILE_KEY) if session is not None else None


def product_phase(db: Any, phase: str):
    return profile_phase(batch_profile(db), phase)


def profile_phase(profile: ImportBatchProfile | None, phase: str):
    return profile.measure(phase) if profile is not None else nullcontext()


@contextmanager
def profile_savepoint(db: Any) -> Iterator[None]:
    """Discard only observer creation counts when an attempt is rolled back."""
    profile = batch_profile(db)
    if profile is None:
        yield
        return
    retained = profile.retained_new_objects.copy()
    profile.savepoint_attempts += 1
    try:
        with profile.measure("savepoint_attempt"):
            yield
    except BaseException:
        profile.retained_new_objects = retained
        profile.savepoint_interrupted += 1
        raise


async def profiled_commit(db: Any, profile: ImportBatchProfile | None = None) -> None:
    if profile is None:
        profile = batch_profile(db)
    if profile is not None:
        # A lost response must never be reported as a known failed commit.
        profile.commit_state = "unknown"
    with profile_phase(profile, "commit"):
        await db.commit()
    if profile is not None:
        profile.commit_state = "returned"


class ImportBatchProfile:
    """Fixed-size aggregates for one selected <=100-row execution transaction."""

    def __init__(
        self, *, company_id: int, job_id: UUID, batch_number: int,
        service_started: float,
    ) -> None:
        self.company_id = int(company_id)
        self.job_id = str(job_id)
        self.batch_number = batch_number
        self.service_started = service_started
        self.started = perf_counter()
        self.phases: dict[str, dict[str, float | int]] = {}
        self.stack: list[str] = []
        self.listeners: list[tuple[Any, str, Any]] = []
        self.session: Any = None
        self.cursor_started: tuple[float, str, int] | None = None
        # Completed cursor calls, in actual execution order; never store SQL or binds.
        self.sql_statement_timings: list[dict[str, Any]] = []
        self.sql_statement_timings_dropped = 0
        self.flush_started: tuple[float, str] | None = None
        self.sql_started = 0
        self.sql_completed = 0
        self.sql_executemany = 0
        self.flush_started_count = 0
        self.flush_completed = 0
        self.flush_new_candidates = 0
        self.flush_dirty_candidates = 0
        self.flush_deleted_candidates = 0
        self.attempted_new_objects = dict.fromkeys(_OBJECTS, 0)
        self.retained_new_objects = dict.fromkeys(_OBJECTS, 0)
        self.savepoint_attempts = 0
        self.savepoint_interrupted = 0
        self.rows_selected = 0
        self.rows_imported = 0
        self.rows_failed = 0
        self.commit_state = "not_attempted"
        self.instrumentation_complete = True

    def _phase(self, phase: str) -> dict[str, float | int]:
        # All labels are code constants; never accept source values as log keys.
        if phase not in _PHASES:
            phase = "batch_other"
        return self.phases.setdefault(phase, {
            "calls": 0, "wall_ms": 0.0, "sql_calls_started": 0,
            "sql_calls_completed": 0, "sql_completed_wall_ms": 0.0,
            "flush_passes_started": 0, "flush_passes_completed": 0,
            "flush_completed_wall_ms": 0.0,
        })

    def _current_phase(self) -> str:
        return self.stack[-1] if self.stack else "batch_other"

    @contextmanager
    def measure(self, phase: str) -> Iterator[None]:
        metric = self._phase(phase)
        started = perf_counter()
        self.stack.append(phase if phase in _PHASES else "batch_other")
        try:
            yield
        finally:
            self.stack.pop()
            metric["calls"] += 1
            metric["wall_ms"] += (perf_counter() - started) * 1000

    async def attach(self, db: Any) -> None:
        """Use the connection already borrowed by open_tenant_session's RLS SQL."""
        try:
            connection = (await db.connection()).sync_connection
            self.session = db.sync_session
            self.session.info[_PROFILE_KEY] = self
            for target, name, callback in (
                (connection, "before_cursor_execute", self._before_cursor),
                (connection, "after_cursor_execute", self._after_cursor),
                (self.session, "before_flush", self._before_flush),
                (self.session, "after_flush_postexec", self._after_flush),
                (self.session, "pending_to_persistent", self._new_object),
            ):
                event.listen(target, name, callback)
                self.listeners.append((target, name, callback))
        except Exception:
            # Optional instrumentation must not change the business outcome.
            self.instrumentation_complete = False
            self.detach()

    def detach(self) -> None:
        for target, name, callback in reversed(self.listeners):
            try:
                event.remove(target, name, callback)
            except Exception:
                self.instrumentation_complete = False
        self.listeners.clear()
        if self.session is not None:
            self.session.info.pop(_PROFILE_KEY, None)
            self.session = None

    def _before_cursor(
        self, connection, cursor, statement, parameters, context, executemany,
    ) -> None:
        phase = self._current_phase()
        self.sql_started += 1
        self.cursor_started = (perf_counter(), phase, self.sql_started)
        self.sql_executemany += int(bool(executemany))
        self._phase(phase)["sql_calls_started"] += 1

    def _after_cursor(
        self, connection, cursor, statement, parameters, context, executemany,
    ) -> None:
        if self.cursor_started is None:
            return
        started, phase, ordinal = self.cursor_started
        self.cursor_started = None
        elapsed_ms = (perf_counter() - started) * 1000
        self.sql_completed += 1
        metric = self._phase(phase)
        metric["sql_calls_completed"] += 1
        metric["sql_completed_wall_ms"] += elapsed_ms

        # This connection already belongs to one opt-in, sampled import batch.
        # Hash the parameter-free SQL template; neither text nor bind values
        # enter the log. Keep each completed call, rather than a phase aggregate,
        # so price_publish's 11 calls can be compared individually.
        try:
            if len(self.sql_statement_timings) >= _MAX_SQL_STATEMENT_DETAILS:
                self.sql_statement_timings_dropped += 1
                return
            operation = statement.lstrip().split(None, 1)
            verb = operation[0].upper() if operation else "OTHER"
            static_label = context.execution_options.get(_IMPORT_SQL_LABEL_OPTION)
            if static_label not in _IMPORT_SQL_LABELS:
                static_label = "unlabeled"
            self.sql_statement_timings.append({
                "ordinal": ordinal,
                "phase": phase,
                "sql_label": static_label,
                "sql_type": verb if verb in _SQL_OPERATION_LABELS else "OTHER",
                "sql_sha256_16": sha256(statement.encode("utf-8")).hexdigest()[:16],
                "executemany": bool(executemany),
                "wall_ms": round(elapsed_ms, 3),
            })
        except Exception:
            # Instrumentation must not change whether the import commits.
            self.instrumentation_complete = False
            self.sql_statement_timings_dropped += 1

    def _before_flush(self, session, flush_context, instances) -> None:
        phase = self._current_phase()
        self.flush_started = (perf_counter(), phase)
        self.flush_started_count += 1
        self.flush_new_candidates += len(session.new)
        self.flush_dirty_candidates += len(session.dirty)
        self.flush_deleted_candidates += len(session.deleted)
        self._phase(phase)["flush_passes_started"] += 1

    def _after_flush(self, session, flush_context) -> None:
        if self.flush_started is None:
            return
        started, phase = self.flush_started
        self.flush_started = None
        self.flush_completed += 1
        metric = self._phase(phase)
        metric["flush_passes_completed"] += 1
        metric["flush_completed_wall_ms"] += (perf_counter() - started) * 1000

    def _new_object(self, session, instance) -> None:
        name = type(instance).__name__
        key = name if name in self.attempted_new_objects else "other"
        self.attempted_new_objects[key] += 1
        self.retained_new_objects[key] += 1

    def emit(self) -> None:
        """One bounded, safe record, even after interruption; never raise a log error."""
        try:
            now = perf_counter()
            payload = {
                "schema": 1,
                "correlation_id": f"product-import:{self.job_id}",
                "company_id": self.company_id,
                "job_id": self.job_id,
                "batch_number": self.batch_number,
                "rows_selected": self.rows_selected,
                "rows_imported_before_commit": self.rows_imported,
                "rows_failed_before_commit": self.rows_failed,
                "commit_state": self.commit_state,
                "batch_wall_ms": round((now - self.started) * 1000, 3),
                "service_elapsed_wall_ms": round((now - self.service_started) * 1000, 3),
                # No dispatch timestamp or isolated checkout boundary is available here.
                "queue_wait_ms": None,
                "pool_checkout_ms": None,
                "instrumentation_complete": self.instrumentation_complete,
                "sql_calls_started": self.sql_started,
                "sql_calls_completed": self.sql_completed,
                "sql_calls_without_completion": self.sql_started - self.sql_completed,
                "sql_executemany_calls": self.sql_executemany,
                # One bounded row per completed call, with stable SQL-template
                # hash and no SQL text, bind values, row contents or objects.
                "sql_statement_timings": self.sql_statement_timings,
                "sql_statement_timings_limit": _MAX_SQL_STATEMENT_DETAILS,
                "sql_statement_timings_dropped": self.sql_statement_timings_dropped,
                "flush_passes_started": self.flush_started_count,
                "flush_passes_completed": self.flush_completed,
                "flush_passes_without_completion": self.flush_started_count - self.flush_completed,
                "flush_new_candidates": self.flush_new_candidates,
                "flush_dirty_candidates": self.flush_dirty_candidates,
                "flush_deleted_candidates": self.flush_deleted_candidates,
                "attempted_new_objects": self.attempted_new_objects,
                "committed_new_objects": (
                    self.retained_new_objects if self.commit_state == "returned" else None
                ),
                "savepoint_attempts": self.savepoint_attempts,
                "savepoint_interrupted": self.savepoint_interrupted,
                "phases": {
                    name: {
                        key: round(value, 3) if isinstance(value, float) else value
                        for key, value in metric.items()
                    }
                    for name, metric in self.phases.items()
                },
            }
            logger.info(
                "PRODUCT_IMPORT_BATCH_PROFILE %s",
                json.dumps(payload, separators=(",", ":"), ensure_ascii=True),
            )
        except Exception:
            # Do not mask a returned commit, rollback or cancellation.
            pass
