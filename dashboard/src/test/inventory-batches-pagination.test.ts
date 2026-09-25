import { describe, expect, it } from "vitest";

import { parseBatchDetailResponse } from "@/pages/inventory/liveStock/contracts";

const batch = (id: number) => ({
  batch_id: id,
  batch_number: `B-${id}`,
  production_date: "2026-01-01",
  expiry_date: "2030-01-01",
  disposition: "RELEASED",
  days_to_expiry: 100,
  on_hand_quantity: "1",
  reserved_quantity: "0",
  available_for_sale_quantity: "1",
  unavailable_quantity: "0",
  restricted_quantity: "0",
  expiry_unavailable_quantity: "0",
  quarantined_quantity: "0",
  blocked_quantity: "0",
  recalled_quantity: "0",
  damaged_quantity: "0",
  disposal_pending_quantity: "0",
  latest_purchase_cost: null,
  latest_purchase_uom_code: null,
  latest_purchase_date: null,
  purchase_event_count: 0,
});

const page = (overrides: Record<string, unknown> = {}) => ({
  location_id: 119,
  product_variant_id: 211352,
  currency_code: "JOD",
  batches: [batch(1)],
  next_cursor: null,
  has_more: false,
  ...overrides,
});

describe("inventory batch pagination contract", () => {
  it("accepts a bounded continuation page", () => {
    const parsed = parseBatchDetailResponse(
      page({
        batches: [batch(1), batch(2)],
        next_cursor: "cursor-2",
        has_more: true,
      }),
    );

    expect(parsed.batches.map((item) => item.batch_id)).toEqual([1, 2]);
    expect(parsed.next_cursor).toBe("cursor-2");
    expect(parsed.has_more).toBe(true);
  });

  it("accepts expiry as a restriction breakdown without changing disposition", () => {
    const parsed = parseBatchDetailResponse(
      page({
        batches: [
          {
            ...batch(1),
            disposition: "RELEASED",
            days_to_expiry: -1,
            available_for_sale_quantity: "0",
            unavailable_quantity: "8",
            restricted_quantity: "8",
            expiry_unavailable_quantity: "8",
          },
        ],
      }),
    );

    expect(parsed.batches[0]).toMatchObject({
      disposition: "RELEASED",
      days_to_expiry: -1,
      available_for_sale_quantity: "0",
      restricted_quantity: "8",
      expiry_unavailable_quantity: "8",
    });
  });

  it("rejects expiry breakdown larger than the restricted partition", () => {
    expect(() =>
      parseBatchDetailResponse(
        page({
          batches: [
            {
              ...batch(1),
              restricted_quantity: "2",
              expiry_unavailable_quantity: "3",
            },
          ],
        }),
      ),
    ).toThrow("LIVE_STOCK_BATCH_RESPONSE_INVALID");
  });

  it("rejects inconsistent has_more and next_cursor state", () => {
    expect(() =>
      parseBatchDetailResponse(
        page({
          next_cursor: null,
          has_more: true,
        }),
      ),
    ).toThrow("LIVE_STOCK_BATCH_RESPONSE_INVALID");
  });

  it("rejects a response page larger than the backend hard bound", () => {
    expect(() =>
      parseBatchDetailResponse(
        page({
          batches: Array.from({ length: 201 }, (_, index) =>
            batch(index + 1),
          ),
        }),
      ),
    ).toThrow("LIVE_STOCK_BATCH_RESPONSE_INVALID");
  });
});
