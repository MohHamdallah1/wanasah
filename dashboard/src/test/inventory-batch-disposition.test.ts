import { describe, expect, it } from "vitest";

import { allowedBatchDispositionTargets } from "@/pages/inventory/batches/batchDispositionRules";
import { parseBatchDispositionMutation } from "@/pages/inventory/batches/contracts";

describe("batch disposition controls", () => {
  it("mirrors the backend disposition transition matrix", () => {
    expect(allowedBatchDispositionTargets("RELEASED")).toEqual([
      "QUARANTINED",
      "BLOCKED",
      "RECALLED",
    ]);
    expect(allowedBatchDispositionTargets("QUARANTINED")).toEqual([
      "RELEASED",
      "BLOCKED",
      "RECALLED",
    ]);
    expect(allowedBatchDispositionTargets("BLOCKED")).toEqual([
      "RECALLED",
    ]);
    expect(allowedBatchDispositionTargets("RECALLED")).toEqual([]);
  });

  it("requires the server revision returned by a disposition mutation", () => {
    const parsed = parseBatchDispositionMutation({
      batch_id: 7,
      product_variant_id: 11,
      batch_number: "LOT-7",
      disposition: "QUARANTINED",
      disposition_reason: "Inspection",
      disposition_revision: 2,
      updated_at: "2026-10-03T12:00:00Z",
    });
    expect(parsed.disposition_revision).toBe(2);

    expect(() =>
      parseBatchDispositionMutation({
        ...parsed,
        disposition_revision: 0,
      }),
    ).toThrow("BATCH_DISPOSITION_RESPONSE_INVALID");
  });
});
