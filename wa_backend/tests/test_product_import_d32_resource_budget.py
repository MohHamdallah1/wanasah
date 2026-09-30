from __future__ import annotations

import os
from unittest import TestCase
from unittest.mock import patch

from config import Config
from domains.simple_products.imports.infrastructure.resource_budget import (
    load_product_import_resource_budget,
)


class ProductImportD32ResourceBudgetTests(TestCase):
    def test_reviewed_default_is_two_bounded_execution_slots(self) -> None:
        with patch.dict(
            os.environ,
            {
                "PRODUCT_IMPORT_WORKER_SLOTS_PER_PROCESS": "2",
                "PRODUCT_IMPORT_CONTROL_WORKER_SLOTS": "1",
                "PRODUCT_IMPORT_MAINTENANCE_WORKER_SLOTS": "1",
                "PRODUCT_IMPORT_QUEUE_POOL_MIN": "1",
                "PRODUCT_IMPORT_QUEUE_POOL_MAX": "2",
                "PRODUCT_IMPORT_DB_CONNECTION_BUDGET": "16",
            },
            clear=False,
        ):
            budget = load_product_import_resource_budget()
        self.assertEqual(budget.execution_slots, 2)
        self.assertEqual(budget.queue_pool_min, 1)
        self.assertEqual(budget.queue_pool_max, 2)
        self.assertEqual(budget.estimated_peak_connections, 13)
        self.assertLessEqual(
            budget.estimated_peak_connections,
            budget.connection_budget,
        )

    def test_execution_slots_cannot_exceed_tenant_db_pool(self) -> None:
        with patch.dict(
            os.environ,
            {
                "PRODUCT_IMPORT_WORKER_SLOTS_PER_PROCESS": str(
                    int(Config.DB_POOL_SIZE) + 1
                )
            },
            clear=False,
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "cannot exceed DB_POOL_SIZE",
            ):
                load_product_import_resource_budget()

    def test_queue_pool_bounds_fail_closed(self) -> None:
        with patch.dict(
            os.environ,
            {
                "PRODUCT_IMPORT_QUEUE_POOL_MIN": "3",
                "PRODUCT_IMPORT_QUEUE_POOL_MAX": "2",
            },
            clear=False,
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "cannot exceed MAX",
            ):
                load_product_import_resource_budget()

    def test_subsystem_connection_envelope_cannot_exceed_budget(self) -> None:
        with patch.dict(
            os.environ,
            {
                "PRODUCT_IMPORT_WORKER_SLOTS_PER_PROCESS": "2",
                "PRODUCT_IMPORT_CONTROL_WORKER_SLOTS": "1",
                "PRODUCT_IMPORT_MAINTENANCE_WORKER_SLOTS": "1",
                "PRODUCT_IMPORT_QUEUE_POOL_MIN": "1",
                "PRODUCT_IMPORT_QUEUE_POOL_MAX": "2",
                "PRODUCT_IMPORT_DB_CONNECTION_BUDGET": "12",
            },
            clear=False,
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "exceeds its explicit budget",
            ):
                load_product_import_resource_budget()
