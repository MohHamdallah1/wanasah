"""Workload isolation within the existing public-schema queue application."""

EXECUTION_QUEUE = "product-import"
CONTROL_QUEUE = "product-import-control"
MAINTENANCE_QUEUE = "product-import-maintenance"

ROLE_QUEUES = {
    "execution": EXECUTION_QUEUE,
    "control": CONTROL_QUEUE,
    "maintenance": MAINTENANCE_QUEUE,
}


def is_execution_consumer(context) -> bool:
    # Fail closed for unspecified/all-queue and mixed-role workers. A control
    # heartbeat must never register its own worker as import execution capacity.
    return tuple(context.worker_queues or ()) == (EXECUTION_QUEUE,)
