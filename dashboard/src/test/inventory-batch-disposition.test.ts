import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import { parseAllowedBatchDispositionTargets } from "@/pages/inventory/batches/batchStockSourcesContract";
import { parseBatchDispositionMutation } from "@/pages/inventory/batches/contracts";

describe("batch disposition controls", () => {
  it("renders server-provided disposition targets instead of owning a transition matrix", () => {
    expect(
      parseAllowedBatchDispositionTargets([
        "RELEASED",
        "BLOCKED",
        "RECALLED",
      ]),
    ).toEqual(["RELEASED", "BLOCKED", "RECALLED"]);
    expect(() =>
      parseAllowedBatchDispositionTargets(["RECALLED", "RECALLED"]),
    ).toThrow("BATCH_STOCK_SOURCES_RESPONSE_INVALID");

    const manager = readFileSync(
      new URL(
        "../pages/inventory/batches/BatchDispositionManager.tsx",
        import.meta.url,
      ),
      "utf8",
    );
    expect(manager).toContain("batch?.allowed_disposition_targets ?? []");
    expect(manager).not.toContain("allowedBatchDispositionTargets");
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
