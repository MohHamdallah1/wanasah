"""Public application entry point for Product Import."""

from .state_machine import (
    record_runtime_failure as mark_import_runtime_failure,
)
from .worker import (
    run_product_import_job,
)

__all__ = (
    "mark_import_runtime_failure",
    "run_product_import_job",
)
