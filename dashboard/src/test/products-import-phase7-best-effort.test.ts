import {
  describe,
  expect,
  it,
} from "vitest";

import {
  parseProductImportState,
} from "../pages/products/contracts";
import {
  calculateImportProgress,
} from "../pages/products/import/helpers";

describe(
  "Product Import Phase 7 best-effort contract",
  () => {
    it(
      "accepts partial-success state and exposes explicit counters",
      () => {
        const state =
          parseProductImportState({
            job_id:
              "123e4567-e89b-42d3-a456-426614174000",
            status:
              "COMPLETED_WITH_ERRORS",
            file_name:
              "products.csv",
            total_rows: 50_000,
            processed_rows: 49_999,
            valid_rows: 49_999,
            failed_rows: 1,
            imported_rows: 49_999,
            invalid_rows: 1,
            import_failed_rows: 0,
            pending_rows: 0,
            detected_headers: [
              "Product",
            ],
            suggested_mapping: {
              name: "Product",
            },
            column_mapping: {
              name: "Product",
            },
            default_lot_control_mode:
              "NONE",
            default_expiry_control_mode:
              "NONE",
            error_summary: {
              code:
                "PRODUCT_IMPORT_COMPLETED_WITH_ERRORS",
            },
            errors: [
              {
                row_number: 50_001,
                code:
                  "IMPORT_NAME_REQUIRED",
                message:
                  "Product name is required.",
              },
            ],
          });

        expect(
          state.status,
        ).toBe(
          "COMPLETED_WITH_ERRORS",
        );
        expect(
          state.imported_rows,
        ).toBe(49_999);
        expect(
          state.invalid_rows,
        ).toBe(1);
        expect(
          state.import_failed_rows,
        ).toBe(0);
        expect(
          state.pending_rows,
        ).toBe(0);
        expect(
          calculateImportProgress(
            state,
          ),
        ).toBe(100);
      },
    );

    it(
      "counts deterministic execution failures as processed progress",
      () => {
        const state =
          parseProductImportState({
            job_id:
              "123e4567-e89b-42d3-a456-426614174000",
            status: "IMPORTING",
            file_name:
              "products.csv",
            total_rows: 4,
            processed_rows: 2,
            valid_rows: 4,
            failed_rows: 0,
            imported_rows: 2,
            invalid_rows: 0,
            import_failed_rows: 1,
            pending_rows: 1,
            detected_headers: [],
            suggested_mapping: {},
            column_mapping: {},
            default_lot_control_mode:
              "NONE",
            default_expiry_control_mode:
              "NONE",
            error_summary: {},
            errors: [],
          });

        expect(
          calculateImportProgress(
            state,
          ),
        ).toBe(75);
      },
    );
  },
);
