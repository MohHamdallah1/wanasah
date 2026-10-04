import { describe, expect, it } from "vitest";

import { parseBatchStockSources } from "@/pages/inventory/batches/batchStockSourcesContract";

const response = {
  batch_id: 41,
  product_variant_id: 118,
  batch_number: "LOT-41",
  production_date: "2026-09-01",
  expiry_date: "2027-09-01",
  disposition: "QUARANTINED",
  disposition_reason: "اشتباه في تاريخ الصلاحية",
  disposition_revision: 3,
  days_to_expiry: 332,
  base_uom_id: 7,
  base_uom_code: "EA",
  operational_hold: "NONE",
  sources: [
    {
      location_id: 901,
      location_name: "Vehicle 12",
      location_type: "VEHICLE",
      can_send: true,
      statuses: [
        {
          stock_status: "QUARANTINED",
          on_hand_quantity: "12.000000",
          reserved_quantity: "2.000000",
          movable_quantity: "10.000000",
        },
      ],
    },
  ],
};

describe("batch stock-source action contract", () => {
  it("carries authoritative batch metadata even when the only physical source is a vehicle", () => {
    const parsed = parseBatchStockSources(response);

    expect(parsed.batch).toEqual({
      batch_id: 41,
      batch_number: "LOT-41",
      production_date: "2026-09-01",
      expiry_date: "2027-09-01",
      disposition: "QUARANTINED",
      disposition_reason: "اشتباه في تاريخ الصلاحية",
      disposition_revision: 3,
      days_to_expiry: 332,
    });
    expect(parsed.base_uom_code).toBe("EA");
    expect(parsed.sources).toHaveLength(1);
    expect(parsed.sources[0].location_type).toBe("VEHICLE");
    expect(parsed.sources[0].statuses[0]).toMatchObject({
      on_hand_quantity: "12",
      reserved_quantity: "2",
      movable_quantity: "10",
    });
  });

  it("fails closed when action-critical batch revision or metadata is invalid", () => {
    expect(() =>
      parseBatchStockSources({ ...response, disposition_revision: 0 }),
    ).toThrow("BATCH_STOCK_SOURCES_RESPONSE_INVALID");
    expect(() =>
      parseBatchStockSources({ ...response, batch_number: "" }),
    ).toThrow("BATCH_STOCK_SOURCES_RESPONSE_INVALID");
    expect(() =>
      parseBatchStockSources({ ...response, base_uom_code: "" }),
    ).toThrow("BATCH_STOCK_SOURCES_RESPONSE_INVALID");
  });
});
