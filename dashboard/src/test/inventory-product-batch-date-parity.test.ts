import { describe, expect, it } from "vitest";

import { parsePublicBatchDate } from "@/pages/inventory/publicBatchDate";
import { parseOverrideOptions, parseTransferDetail } from "@/pages/inventory/transfers/parsers";
import { parseCountSheet, parseCycleBatchPage, parseStocktakeReview } from "@/pages/inventory/stocktake/parsers";

const transferHeader = {
  id: 70,
  reference_number: "TR-70",
  source_location_id: 5,
  source_location_name: "Main",
  destination_location_id: 6,
  destination_location_name: "Second",
  status: "POSTED",
  transfer_purpose: "REPLENISHMENT",
  dispatched_by: 1,
  dispatched_by_name: "Operator",
  received_by: null,
  received_by_name: null,
  cancelled_by: null,
  cancelled_by_name: null,
  line_count: 1,
  total_quantity: "1",
  notes: null,
  decision_reason: null,
  created_at: "2026-10-15T10:00:00Z",
  updated_at: "2026-10-15T10:00:00Z",
  accepted_at: null,
  rejected_at: null,
  cancelled_at: null,
  posted_at: "2026-10-15T10:00:00Z",
};

const transferLine = (expiry_date: unknown, batch_number: unknown = "LOT-99") => ({
  id: 701,
  product_variant_id: 10,
  product_name: "Product",
  batch_id: 99,
  batch_number,
  expiry_date,
  quantity: "1",
  uom_id: 1,
  fefo_override_reason_id: null,
  fefo_overridden_by: null,
  fefo_override_note: null,
});

const transferDetail = (line: Record<string, unknown>) => ({
  transfer: transferHeader,
  lines: [line],
});

const overrideBatch = (
  expiry_date: unknown,
  production_date: unknown = null,
  batch_number: unknown = "LOT-99",
) => ({
  id: 99,
  batch_number,
  production_date,
  expiry_date,
  available_quantity: "4",
  is_fefo_head: true,
});

const overrideOptions = (batch: Record<string, unknown>) => ({
  location_id: 5,
  product_variant_id: 10,
  fefo_batch_id: 99,
  batches: [batch],
  reasons: [],
});

const cycleBatch = (
  expiry_date: unknown,
  production_date: unknown = null,
  batch_number: unknown = "LOT-99",
) => ({
  id: 99,
  product_variant_id: 10,
  batch_number,
  production_date,
  expiry_date,
  is_active: true,
});

const cyclePage = (batch: Record<string, unknown>) => ({
  items: [batch],
  next_cursor: null,
  has_more: false,
  total: 1,
});

const countItem = (expiry_date: unknown) => ({
  product_variant_id: 10,
  batch_id: 99,
  stock_status: "AVAILABLE",
  product_name: "Product",
  base_uom_id: 1,
  base_uom_code: "EA",
  base_uom_name: "Each",
  quantity_scale: 0,
  quantity_step: "1",
  batch_number: null,
  expiry_date,
});

const attempt = {
  id: 1,
  attempt_number: 1,
  counted_by: 1,
  counted_by_name: "Counter",
  authorized_by: null,
  authorized_by_name: null,
  recount_of_attempt_id: null,
  recount_reason: null,
  requires_independent_recount: false,
  submitted_at: "2026-10-15T10:00:00Z",
};

const reviewLine = (expiry_date: unknown) => ({
  attempt_line_id: 1,
  product_variant_id: 10,
  batch_id: 99,
  stock_status: "AVAILABLE",
  line_origin: "SNAPSHOT",
  product_name: "Product",
  base_uom_id: 1,
  base_uom_code: "EA",
  base_uom_name: "Each",
  quantity_scale: 0,
  quantity_step: "1",
  batch_number: null,
  expiry_date,
  expected_quantity: "1",
  actual_quantity: "1",
  variance_quantity: "0",
  notes: null,
});

const reviewPayload = (line: Record<string, unknown>) => ({
  session_id: 1,
  reference_number: "ST-1",
  stocktake_type: "CYCLE_COUNT",
  status: "PENDING_REVIEW",
  location_id: 5,
  independent_recount_satisfied: false,
  latest_attempt: attempt,
  attempt_history: [attempt],
  lines: [line],
});

describe("public ProductBatch date parity", () => {
  it("accepts null and a real ISO date, and rejects empty/missing/wrong/invalid dates", () => {
    const invalid = () => { throw new Error("invalid"); };
    expect(parsePublicBatchDate(null, invalid)).toBeNull();
    expect(parsePublicBatchDate("2030-01-31", invalid)).toBe("2030-01-31");
    expect(() => parsePublicBatchDate("", invalid)).toThrow("invalid");
    expect(() => parsePublicBatchDate(undefined, invalid)).toThrow("invalid");
    expect(() => parsePublicBatchDate(20300131, invalid)).toThrow("invalid");
    expect(() => parsePublicBatchDate("2030-02-31", invalid)).toThrow("invalid");
  });

  it("Transfer detail accepts null expiry and retains batch-id action identity", () => {
    const parsed = parseTransferDetail(transferDetail(transferLine(null, null)));
    expect(parsed.lines[0]).toMatchObject({ batch_id: 99, batch_number: null, expiry_date: null });
  });

  it("Transfer detail preserves a real ISO expiry", () => {
    expect(parseTransferDetail(transferDetail(transferLine("2030-01-31"))).lines[0])
      .toMatchObject({ batch_id: 99, batch_number: "LOT-99", expiry_date: "2030-01-31" });
  });

  it("Transfer detail rejects empty and missing expiry_date", () => {
    expect(() => parseTransferDetail(transferDetail(transferLine("")))).toThrow();
    const missing = transferLine("2030-01-31") as Record<string, unknown>;
    delete missing.expiry_date;
    expect(() => parseTransferDetail(transferDetail(missing))).toThrow();
  });

  it("FEFO override accepts null expiry/production dates without losing batch identity", () => {
    const parsed = parseOverrideOptions(overrideOptions(overrideBatch(null, null, null)), 5, 10);
    expect(parsed.fefo_batch_id).toBe(99);
    expect(parsed.batches[0]).toMatchObject({
      id: 99,
      batch_number: null,
      production_date: null,
      expiry_date: null,
      is_fefo_head: true,
    });
  });

  it("FEFO override preserves real public dates and rejects missing public date fields", () => {
    const parsed = parseOverrideOptions(
      overrideOptions(overrideBatch("2030-01-31", "2029-01-31", "LOT-99")),
      5,
      10,
    );
    expect(parsed.batches[0]).toMatchObject({
      id: 99,
      batch_number: "LOT-99",
      production_date: "2029-01-31",
      expiry_date: "2030-01-31",
    });

    const missingExpiry = overrideBatch("2030-01-31") as Record<string, unknown>;
    delete missingExpiry.expiry_date;
    expect(() => parseOverrideOptions(overrideOptions(missingExpiry), 5, 10)).toThrow();

    const missingProduction = overrideBatch("2030-01-31") as Record<string, unknown>;
    delete missingProduction.production_date;
    expect(() => parseOverrideOptions(overrideOptions(missingProduction), 5, 10)).toThrow();
  });

  it("Stocktake cycle accepts null expiry with null lot and remains selectable by batch id", () => {
    const parsed = parseCycleBatchPage(cyclePage(cycleBatch(null, null, null)), 10);
    expect(parsed.items[0]).toMatchObject({
      id: 99,
      batch_number: null,
      production_date: null,
      expiry_date: null,
      is_active: true,
    });
  });

  it("Stocktake cycle preserves real dates and rejects empty/missing expiry", () => {
    const parsed = parseCycleBatchPage(cyclePage(cycleBatch("2030-01-31", "2029-01-31", "LOT-99")), 10);
    expect(parsed.items[0]).toMatchObject({
      id: 99,
      batch_number: "LOT-99",
      production_date: "2029-01-31",
      expiry_date: "2030-01-31",
    });

    expect(() => parseCycleBatchPage(cyclePage(cycleBatch("")), 10)).toThrow();
    const missing = cycleBatch("2030-01-31") as Record<string, unknown>;
    delete missing.expiry_date;
    expect(() => parseCycleBatchPage(cyclePage(missing), 10)).toThrow();
  });

  it("Stocktake cycle requires production_date shape while allowing null", () => {
    const missing = cycleBatch("2030-01-31") as Record<string, unknown>;
    delete missing.production_date;
    expect(() => parseCycleBatchPage(cyclePage(missing), 10)).toThrow();
    expect(() => parseCycleBatchPage(cyclePage(cycleBatch("2030-01-31", "")), 10)).toThrow();
  });

  it("Stocktake count/review treat expiry as required-shape nullable ProductBatch metadata", () => {
    expect(parseCountSheet([countItem(null)])[0]).toMatchObject({ batch_id: 99, expiry_date: null });
    const missingCount = countItem(null) as Record<string, unknown>;
    delete missingCount.expiry_date;
    expect(() => parseCountSheet([missingCount])).toThrow();

    expect(parseStocktakeReview(reviewPayload(reviewLine(null))).lines[0])
      .toMatchObject({ batch_id: 99, expiry_date: null });
    const missingReview = reviewLine(null) as Record<string, unknown>;
    delete missingReview.expiry_date;
    expect(() => parseStocktakeReview(reviewPayload(missingReview))).toThrow();
  });
});