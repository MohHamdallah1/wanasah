import {
  describe,
  expect,
  it,
} from "vitest";

import {
  isProductImportProgressEvent,
  productImportBackoffDelay,
} from "../pages/products/import/useImportProductPolling";


describe(
  "Product Import Phase 13 realtime transport",
  () => {
    it(
      "uses bounded exponential reconnect and polling backoff with jitter",
      () => {
        expect(
          productImportBackoffDelay(
            0,
            0,
          ),
        ).toBe(1500);
        expect(
          productImportBackoffDelay(
            1,
            0,
          ),
        ).toBe(3000);
        expect(
          productImportBackoffDelay(
            8,
            1,
          ),
        ).toBe(30500);
        expect(
          productImportBackoffDelay(
            2,
            0.5,
            1000,
          ),
        ).toBe(4250);
      },
    );

    it(
      "accepts push events only for the exact observed job",
      () => {
        const jobId =
          "11111111-1111-4111-8111-111111111111";
        expect(
          isProductImportProgressEvent(
            {
              event:
                "PRODUCT_IMPORT_PROGRESS",
              job_id: jobId,
            },
            jobId,
          ),
        ).toBe(true);

        expect(
          isProductImportProgressEvent(
            {
              event:
                "PRODUCT_IMPORT_PROGRESS",
              job_id:
                "22222222-2222-4222-8222-222222222222",
            },
            jobId,
          ),
        ).toBe(false);

        expect(
          isProductImportProgressEvent(
            {
              event: "OTHER_EVENT",
              job_id: jobId,
            },
            jobId,
          ),
        ).toBe(false);
      },
    );
  },
);
