"""Bounded Product Import worker/connection topology.

This is the Product Import subsystem envelope. Config reserves the whole
envelope inside the deployment-wide PostgreSQL budget so web, operational
workers and Product Import cannot be sized independently by accident.
"""
from __future__ import annotations

from dataclasses import dataclass
import os

from config import Config


def _positive_int(name: str, default: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a positive integer.") from exc
    if value <= 0:
        raise RuntimeError(f"{name} must be a positive integer.")
    return value


@dataclass(frozen=True, slots=True)
class ProductImportResourceBudget:
    queue_pool_min: int
    queue_pool_max: int
    execution_slots: int
    control_slots: int
    maintenance_slots: int
    connection_budget: int
    estimated_peak_connections: int

    def slots_for(self, role: str) -> int:
        if role == "execution":
            return self.execution_slots
        if role == "control":
            return self.control_slots
        if role == "maintenance":
            return self.maintenance_slots
        raise ValueError(f"Unknown Product Import worker role: {role}")


def load_product_import_resource_budget() -> ProductImportResourceBudget:
    queue_min = _positive_int("PRODUCT_IMPORT_QUEUE_POOL_MIN", 1)
    queue_max = _positive_int("PRODUCT_IMPORT_QUEUE_POOL_MAX", 2)
    execution = _positive_int("PRODUCT_IMPORT_WORKER_SLOTS_PER_PROCESS", 2)
    control = _positive_int("PRODUCT_IMPORT_CONTROL_WORKER_SLOTS", 1)
    maintenance = _positive_int("PRODUCT_IMPORT_MAINTENANCE_WORKER_SLOTS", 1)
    budget = _positive_int(
        "PRODUCT_IMPORT_DB_CONNECTION_BUDGET",
        int(Config.PRODUCT_IMPORT_DB_CONNECTION_BUDGET),
    )

    if queue_min > queue_max:
        raise RuntimeError("PRODUCT_IMPORT_QUEUE_POOL_MIN cannot exceed MAX.")
    if execution > int(Config.DB_POOL_SIZE):
        raise RuntimeError(
            "Product Import execution slots cannot exceed DB_POOL_SIZE; "
            "each concurrent import can require a tenant SQLAlchemy checkout."
        )
    if maintenance > int(Config.DB_POOL_SIZE):
        raise RuntimeError(
            "Product Import maintenance slots cannot exceed DB_POOL_SIZE."
        )

    # Conservative topology envelope:
    # - every role may reach queue_pool_max queue metadata connections;
    # - execution slots may each require tenant SQL + one direct source/control
    #   connection during phase transitions;
    # - maintenance slots may require tenant SQL + direct global metrics;
    # - each control slot may require one direct recovery/health connection.
    estimated = (
        (3 * queue_max)
        + (2 * execution)
        + (2 * maintenance)
        + control
    )
    if estimated > budget:
        raise RuntimeError(
            "Product Import DB connection envelope exceeds its explicit budget: "
            f"{estimated} > {budget}. Reduce worker slots/pool sizes or raise "
            "the reviewed PRODUCT_IMPORT_DB_CONNECTION_BUDGET."
        )
    return ProductImportResourceBudget(
        queue_pool_min=queue_min,
        queue_pool_max=queue_max,
        execution_slots=execution,
        control_slots=control,
        maintenance_slots=maintenance,
        connection_budget=budget,
        estimated_peak_connections=estimated,
    )


RESOURCE_BUDGET = load_product_import_resource_budget()
