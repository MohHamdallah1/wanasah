from __future__ import annotations

import unittest
from decimal import Decimal
from types import SimpleNamespace

from domains.simple_products.imports.application.execution_service import (
    build_product_spec,
)
from domains.simple_products.imports.application.state_machine import (
    ProductImportStateTransitionError,
    assert_job_transition,
    transition_job,
    transition_row,
)
from domains.simple_products.imports.application.validation_service import (
    collect_row_validation,
    validation_outcome,
)
from domains.simple_products.imports.domain.errors import (
    ImportErrorKind,
    ProductImportTerminalError,
    classify_import_error,
    runtime_failure_summary,
)
from domains.simple_products.imports.domain.normalization import (
    normalize_raw_row,
)
from domains.simple_products.imports.infrastructure.parsers import (
    SourceParser,
    open_source,
)
from domains.simple_products.service import (
    SimpleProductError,
)


class StateMachineTests(
    unittest.TestCase
):
    def test_legal_and_illegal_job_transitions(
        self,
    ) -> None:
        job = SimpleNamespace(
            status="QUEUED",
            version=1,
            updated_at=None,
        )
        transition_job(
            job,
            "PARSING",
        )
        self.assertEqual(
            job.status,
            "PARSING",
        )
        self.assertEqual(
            job.version,
            2,
        )
        self.assertIsNotNone(
            job.updated_at
        )

        with self.assertRaises(
            ProductImportStateTransitionError
        ):
            assert_job_transition(
                "COMPLETED",
                "IMPORTING",
            )

    def test_row_transitions_fail_closed(
        self,
    ) -> None:
        row = SimpleNamespace(
            status="STAGED",
            version=1,
        )
        transition_row(
            row,
            "VALID",
            error_code=None,
        )
        self.assertEqual(
            row.status,
            "VALID",
        )
        self.assertEqual(
            row.version,
            2,
        )

        with self.assertRaises(
            ProductImportStateTransitionError
        ):
            transition_row(
                row,
                "FAILED",
            )


class NormalizationTests(
    unittest.TestCase
):
    def test_explicit_no_package_is_unit_only(
        self,
    ) -> None:
        normalized = normalize_raw_row(
            {
                "Product": "Coffee",
                "Package Type": "No outer package",
                "Units per Package": None,
                "Unit Price": "2.500",
            },
            {
                "name": "Product",
                "package_uom": "Package Type",
                "units_per_package": "Units per Package",
                "unit_price": "Unit Price",
            },
            default_lot_control_mode="OPTIONAL",
            default_expiry_control_mode="NONE",
        )
        self.assertIsNone(
            normalized[
                "package_uom_code"
            ]
        )
        self.assertEqual(
            normalized[
                "units_per_package"
            ],
            1,
        )

    def test_blank_mapped_package_choice_is_rejected(
        self,
    ) -> None:
        with self.assertRaises(
            SimpleProductError
        ) as context:
            normalize_raw_row(
                {
                    "Product": "Coffee",
                    "Package Type": None,
                    "Units per Package": None,
                    "Unit Price": "2.500",
                },
                {
                    "name": "Product",
                    "package_uom": "Package Type",
                    "units_per_package": "Units per Package",
                    "unit_price": "Unit Price",
                },
                default_lot_control_mode="OPTIONAL",
                default_expiry_control_mode="NONE",
            )
        self.assertEqual(
            context.exception.code,
            "IMPORT_PACKAGE_SELECTION_REQUIRED",
        )

    def test_outer_package_requires_base_unit_count(
        self,
    ) -> None:
        with self.assertRaises(
            SimpleProductError
        ) as context:
            normalize_raw_row(
                {
                    "Product": "Coffee",
                    "Package Type": "Carton",
                    "Units per Package": None,
                    "Unit Price": "2.500",
                },
                {
                    "name": "Product",
                    "package_uom": "Package Type",
                    "units_per_package": "Units per Package",
                    "unit_price": "Unit Price",
                },
                default_lot_control_mode="OPTIONAL",
                default_expiry_control_mode="NONE",
            )
        self.assertEqual(
            context.exception.code,
            "IMPORT_PACKAGING_REQUIRED",
        )

    def test_package_units_without_package_type_are_rejected(
        self,
    ) -> None:
        with self.assertRaises(
            SimpleProductError
        ) as context:
            normalize_raw_row(
                {
                    "Product": "Coffee",
                    "Units per Package": "12",
                    "Unit Price": "2.500",
                },
                {
                    "name": "Product",
                    "units_per_package": "Units per Package",
                    "unit_price": "Unit Price",
                },
                default_lot_control_mode="OPTIONAL",
                default_expiry_control_mode="NONE",
            )
        self.assertEqual(
            context.exception.code,
            "IMPORT_PACKAGE_TYPE_REQUIRED",
        )

    def test_no_package_rejects_multiple_units(
        self,
    ) -> None:
        with self.assertRaises(
            SimpleProductError
        ) as context:
            normalize_raw_row(
                {
                    "Product": "Coffee",
                    "Package Type": "No outer package",
                    "Units per Package": "12",
                    "Unit Price": "2.500",
                },
                {
                    "name": "Product",
                    "package_uom": "Package Type",
                    "units_per_package": "Units per Package",
                    "unit_price": "Unit Price",
                },
                default_lot_control_mode="OPTIONAL",
                default_expiry_control_mode="NONE",
            )
        self.assertEqual(
            context.exception.code,
            "IMPORT_NO_PACKAGE_UNITS_INVALID",
        )

    def test_unit_only_row_uses_tracking_defaults(
        self,
    ) -> None:
        normalized = normalize_raw_row(
            {
                "Product": "Coffee",
                "Unit Price": "2.500",
            },
            {
                "name": "Product",
                "unit_price": "Unit Price",
            },
            default_lot_control_mode="OPTIONAL",
            default_expiry_control_mode="NONE",
        )
        self.assertEqual(
            normalized[
                "package_uom_code"
            ],
            None,
        )
        self.assertEqual(
            normalized[
                "units_per_package"
            ],
            1,
        )
        self.assertEqual(
            normalized[
                "lot_control_mode"
            ],
            "OPTIONAL",
        )
        self.assertEqual(
            normalized[
                "expiry_control_mode"
            ],
            "NONE",
        )


class ValidationServiceTests(
    unittest.TestCase
):
    def test_collects_valid_and_invalid_rows_without_changing_policy(
        self,
    ) -> None:
        rows = [
            SimpleNamespace(
                id=1,
                raw_data={
                    "Product": "Tea",
                    "Price": "1.250",
                    "Barcode": "10001",
                },
            ),
            SimpleNamespace(
                id=2,
                raw_data={
                    "Product": "",
                    "Price": "2.000",
                },
            ),
        ]
        (
            normalized,
            errors,
        ) = collect_row_validation(
            rows,
            mapping={
                "name": "Product",
                "unit_price": "Price",
                "unit_barcode": "Barcode",
            },
            default_lot_control_mode="NONE",
            default_expiry_control_mode="OPTIONAL",
        )

        self.assertIn(
            1,
            normalized,
        )
        self.assertNotIn(
            1,
            errors,
        )
        self.assertEqual(
            errors[2][0],
            "IMPORT_NAME_REQUIRED",
        )


    def test_validation_outcome_preserves_phase7_best_effort_policy(
        self,
    ) -> None:
        self.assertEqual(
            validation_outcome(
                1,
                1,
            ),
            (
                "IMPORTING",
                True,
            ),
        )
        self.assertEqual(
            validation_outcome(
                0,
                1,
            ),
            (
                "VALIDATION_FAILED",
                False,
            ),
        )


class ExecutionServiceTests(
    unittest.TestCase
):
    def test_build_product_spec_preserves_normalized_contract(
        self,
    ) -> None:
        spec = build_product_spec(
            {
                "name": "Juice",
                "family_name": "Drinks",
                "package_uom_code": "CARTON",
                "units_per_package": 12,
                "package_price": "12.000",
                "unit_price": "1.000",
                "unit_barcode": "111",
                "package_barcode": "222",
                "lot_control_mode": "REQUIRED",
                "expiry_control_mode": "OPTIONAL",
            }
        )
        self.assertEqual(
            spec.name,
            "Juice",
        )
        self.assertEqual(
            spec.package_price,
            Decimal("12.000"),
        )
        self.assertEqual(
            spec.unit_price,
            Decimal("1.000"),
        )
        self.assertEqual(
            spec.lot_control_mode,
            "REQUIRED",
        )
        self.assertEqual(
            spec.expiry_control_mode,
            "OPTIONAL",
        )


class ErrorClassificationTests(
    unittest.TestCase
):
    def test_deterministic_and_transient_errors_are_distinct(
        self,
    ) -> None:
        deterministic = (
            classify_import_error(
                ProductImportTerminalError(
                    "bad file"
                )
            )
        )
        transient = (
            classify_import_error(
                RuntimeError(
                    "temporary"
                )
            )
        )

        self.assertIs(
            deterministic.kind,
            ImportErrorKind.DETERMINISTIC_JOB,
        )
        self.assertFalse(
            deterministic.retryable
        )
        self.assertIs(
            transient.kind,
            ImportErrorKind.TRANSIENT_SYSTEM,
        )
        self.assertTrue(
            transient.retryable
        )

    def test_retry_summary_keeps_existing_semantics(
        self,
    ) -> None:
        summary = runtime_failure_summary(
            message="temporary",
            final_attempt=False,
            retryable=True,
            resume_status="IMPORTING",
        )
        self.assertEqual(
            summary["code"],
            "PRODUCT_IMPORT_RETRYING",
        )
        self.assertFalse(
            summary["retryable"]
        )
        self.assertEqual(
            summary[
                "resume_status"
            ],
            "IMPORTING",
        )


class ParserInterfaceTests(
    unittest.TestCase
):
    def test_parse_source_matches_parser_contract(
        self,
    ) -> None:
        parser: SourceParser = open_source
        with parser(
            "products.csv",
            b"Product,Unit Price\nTea,1.250\n",
        ) as source:
            rows = list(
                source.rows
            )

        self.assertEqual(
            source.headers,
            [
                "Product",
                "Unit Price",
            ],
        )
        self.assertEqual(
            rows[0].row_number,
            2,
        )
        self.assertEqual(
            rows[0].raw["Product"],
            "Tea",
        )


if __name__ == "__main__":
    unittest.main()
