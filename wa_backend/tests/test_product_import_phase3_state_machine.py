from __future__ import annotations

import unittest

from domains.simple_products.imports.application.state_machine import (
    ALLOWED_JOB_TRANSITIONS,
    ALLOWED_ROW_TRANSITIONS,
    JOB_STATUSES,
    ROW_STATUSES,
    JobStatus,
    ProductImportStateTransitionError,
    RowStatus,
    assert_job_transition,
    assert_row_transition,
)
from domains.simple_products.imports.application.validation_service import (
    classify_row_error,
)
from domains.simple_products.imports.domain.errors import (
    ImportErrorKind,
    ImportFailureScope,
    ProductImportRowExecutionError,
    ProductImportRowValidationError,
    ProductImportTerminalError,
    classify_import_error,
)


class ExhaustiveJobTransitionTests(
    unittest.TestCase
):
    def test_canonical_job_vocabulary(
        self,
    ) -> None:
        self.assertEqual(
            JOB_STATUSES,
            {
                status.value
                for status in JobStatus
            },
        )
        self.assertIn(
            JobStatus.COMPLETED_WITH_ERRORS.value,
            JOB_STATUSES,
        )

    def test_every_job_state_pair(
        self,
    ) -> None:
        for current in JobStatus:
            for target in JobStatus:
                allowed = (
                    target
                    in ALLOWED_JOB_TRANSITIONS[
                        current
                    ]
                )
                with self.subTest(
                    current=current.value,
                    target=target.value,
                ):
                    if allowed:
                        assert_job_transition(
                            current,
                            target,
                        )
                    else:
                        with self.assertRaises(
                            ProductImportStateTransitionError
                        ):
                            assert_job_transition(
                                current,
                                target,
                            )

    def test_unknown_job_states_fail_closed(
        self,
    ) -> None:
        with self.assertRaises(
            ProductImportStateTransitionError
        ):
            assert_job_transition(
                "NOT_A_STATE",
                JobStatus.QUEUED,
            )
        with self.assertRaises(
            ProductImportStateTransitionError
        ):
            assert_job_transition(
                JobStatus.QUEUED,
                "NOT_A_STATE",
            )

    def test_terminal_job_states_have_no_exit(
        self,
    ) -> None:
        for terminal in (
            JobStatus.COMPLETED,
            JobStatus.COMPLETED_WITH_ERRORS,
            JobStatus.VALIDATION_FAILED,
        ):
            self.assertEqual(
                ALLOWED_JOB_TRANSITIONS[
                    terminal
                ],
                frozenset(),
            )


class ExhaustiveRowTransitionTests(
    unittest.TestCase
):
    def test_canonical_row_vocabulary(
        self,
    ) -> None:
        self.assertEqual(
            ROW_STATUSES,
            {
                status.value
                for status in RowStatus
            },
        )
        self.assertNotIn(
            "FAILED",
            ROW_STATUSES,
        )
        self.assertIn(
            RowStatus.INVALID.value,
            ROW_STATUSES,
        )
        self.assertIn(
            RowStatus.IMPORT_FAILED.value,
            ROW_STATUSES,
        )

    def test_every_row_state_pair(
        self,
    ) -> None:
        for current in RowStatus:
            for target in RowStatus:
                allowed = (
                    target
                    in ALLOWED_ROW_TRANSITIONS[
                        current
                    ]
                )
                with self.subTest(
                    current=current.value,
                    target=target.value,
                ):
                    if allowed:
                        assert_row_transition(
                            current,
                            target,
                        )
                    else:
                        with self.assertRaises(
                            ProductImportStateTransitionError
                        ):
                            assert_row_transition(
                                current,
                                target,
                            )

    def test_unknown_row_states_fail_closed(
        self,
    ) -> None:
        with self.assertRaises(
            ProductImportStateTransitionError
        ):
            assert_row_transition(
                "FAILED",
                RowStatus.INVALID,
            )
        with self.assertRaises(
            ProductImportStateTransitionError
        ):
            assert_row_transition(
                RowStatus.STAGED,
                "NOT_A_STATE",
            )

    def test_terminal_row_outcomes_have_no_exit(
        self,
    ) -> None:
        for terminal in (
            RowStatus.INVALID,
            RowStatus.IMPORT_FAILED,
            RowStatus.IMPORTED,
        ):
            self.assertEqual(
                ALLOWED_ROW_TRANSITIONS[
                    terminal
                ],
                frozenset(),
            )


class ErrorTaxonomyTests(
    unittest.TestCase
):
    def test_validation_error_is_deterministic_row_failure(
        self,
    ) -> None:
        classification = (
            classify_import_error(
                ProductImportRowValidationError(
                    "BAD_ROW",
                    "Bad row",
                )
            )
        )
        self.assertIs(
            classification.kind,
            ImportErrorKind.DETERMINISTIC_VALIDATION,
        )
        self.assertIs(
            classification.scope,
            ImportFailureScope.ROW,
        )
        self.assertFalse(
            classification.retryable
        )

    def test_execution_error_is_deterministic_row_failure(
        self,
    ) -> None:
        classification = (
            classify_import_error(
                ProductImportRowExecutionError(
                    "ROW_CONFLICT",
                    "Row conflict",
                )
            )
        )
        self.assertIs(
            classification.kind,
            ImportErrorKind.DETERMINISTIC_ROW_EXECUTION,
        )
        self.assertTrue(
            classification.row_failure
        )
        self.assertFalse(
            classification.retryable
        )

    def test_terminal_job_error_is_not_retryable(
        self,
    ) -> None:
        classification = (
            classify_import_error(
                ProductImportTerminalError(
                    "Terminal"
                )
            )
        )
        self.assertIs(
            classification.kind,
            ImportErrorKind.DETERMINISTIC_JOB,
        )
        self.assertIs(
            classification.scope,
            ImportFailureScope.JOB,
        )
        self.assertFalse(
            classification.retryable
        )

    def test_unknown_system_error_is_transient_job_failure(
        self,
    ) -> None:
        classification = (
            classify_import_error(
                RuntimeError(
                    "database unavailable"
                )
            )
        )
        self.assertIs(
            classification.kind,
            ImportErrorKind.TRANSIENT_SYSTEM,
        )
        self.assertIs(
            classification.scope,
            ImportFailureScope.JOB,
        )
        self.assertTrue(
            classification.retryable
        )

    def test_unknown_validation_exception_is_not_mislabeled_as_bad_row(
        self,
    ) -> None:
        error = RuntimeError(
            "programming defect"
        )
        with self.assertRaises(
            RuntimeError
        ) as raised:
            classify_row_error(
                error
            )
        self.assertIs(
            raised.exception,
            error,
        )


if __name__ == "__main__":
    unittest.main()
