import { describe, expect, it } from "vitest";

import { resources } from "@/i18n/resources";

import { parseTransferDetail, parseOverrideOptions } from "@/pages/inventory/transfers/parsers";
import {
  parseCountSheet,
  parseCycleBatchPage,
  parseStocktakeReview,
  parseStocktakeSessionPage,
} from "@/pages/inventory/stocktake/parsers";
import { parseQualityBatchCandidatePage } from "@/pages/inventory/quality/qualityBatchCandidatesContract";
import { parseProductQualityPage } from "@/features/inventory/quality/wholeProductQualityContract";
import { formatPublicBatchNumber, parsePublicBatchNumber } from "@/pages/inventory/publicBatchNumber";
import { parseLedgerPage } from "@/pages/inventory/ledger/contracts";

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

const transferLine = (batch_number: unknown) => ({
  id: 701,
  product_variant_id: 10,
  product_name: "Product",
  batch_id: 99,
  batch_number,
  expiry_date: "2030-01-01",
  quantity: "1",
  uom_id: 1,
  fefo_override_reason_id: null,
  fefo_overridden_by: null,
  fefo_override_note: null,
});

const qualityPage = (batch_number: unknown) => ({
  product_variant_id: 10,
  base_uom_id: 1,
  base_uom_code: "EA",
  operational_hold: "RECALL",
  batches: [{
    batch_id: 99,
    product_variant_id: 10,
    batch_number,
    expiry_date: null,
    base_uom_id: 1,
    base_uom_code: "EA",
    sources: [{
      location_id: 5,
      location_name: "Main",
      location_type: "WAREHOUSE",
      statuses: [{
        stock_status: "AVAILABLE",
        on_hand_quantity: "1",
        reserved_quantity: "0",
        movable_quantity: "1",
        special_actions: [],
        terminal_actions: [],
      }],
    }],
  }],
  next_cursor: null,
  has_more: false,
});

describe("public ProductBatch number parity", () => {
  it("provides one explicit AR/EN no-lot presentation label", () => {
    expect(resources.ar.translation.inventoryLive.noLotSupplied).toBe("بدون رقم تشغيلة");
    expect(resources.en.translation.inventoryLive.noLotSupplied).toBe("No lot supplied");
  });

  it("accepts only null or a non-empty real lot and preserves the real lot", () => {
    const invalid = () => { throw new Error("invalid"); };
    expect(parsePublicBatchNumber(null, invalid)).toBeNull();
    expect(parsePublicBatchNumber("REAL-LOT-7", invalid)).toBe("REAL-LOT-7");
    expect(() => parsePublicBatchNumber("", invalid)).toThrow("invalid");
    expect(() => parsePublicBatchNumber(undefined, invalid)).toThrow("invalid");
    expect(formatPublicBatchNumber(null, "No lot supplied")).toBe("No lot supplied");
  });

  it("keeps transfer actions identified by batch_id when the public lot is null", () => {
    const parsed = parseTransferDetail({
      transfer: transferHeader,
      lines: [transferLine(null)],
    });
    expect(parsed.lines[0]).toMatchObject({ batch_id: 99, batch_number: null });

    const real = parseTransferDetail({
      transfer: transferHeader,
      lines: [transferLine("REAL-LOT-9")],
    });
    expect(real.lines[0].batch_number).toBe("REAL-LOT-9");

    expect(() => parseTransferDetail({
      transfer: transferHeader,
      lines: [transferLine("")],
    })).toThrow();
  });

  it("accepts null in transfer FEFO override options without losing opaque batch id", () => {
    const parsed = parseOverrideOptions({
      location_id: 5,
      product_variant_id: 10,
      fefo_batch_id: 99,
      batches: [{
        id: 99,
        batch_number: null,
        production_date: null,
        expiry_date: "2030-01-01",
        available_quantity: "4",
        is_fefo_head: true,
      }],
      reasons: [],
    }, 5, 10);
    expect(parsed.batches[0]).toMatchObject({ id: 99, batch_number: null });
  });

  it("keeps an anonymous stocktake batch countable by batch id", () => {
    const parsed = parseCycleBatchPage({
      items: [{
        id: 99,
        product_variant_id: 10,
        batch_number: null,
        production_date: null,
        expiry_date: "2030-01-01",
        is_active: true,
      }],
      next_cursor: null,
      has_more: false,
      total: 1,
    }, 10);
    expect(parsed.items[0]).toMatchObject({ id: 99, batch_number: null });

    expect(() => parseCycleBatchPage({
      items: [{ ...parsed.items[0], batch_number: "" }],
      next_cursor: null,
      has_more: false,
      total: 1,
    }, 10)).toThrow();
  });

  it("accepts null in quality batch candidates while preserving batch_id", () => {
    const parsed = parseQualityBatchCandidatePage({
      product_variant_id: 10,
      base_uom_id: 1,
      base_uom_code: "EA",
      items: [{
        batch_id: 99,
        batch_number: null,
        production_date: null,
        expiry_date: null,
        disposition: "RELEASED",
        disposition_reason: null,
        total_on_hand_quantity: "1",
        total_reserved_quantity: "0",
        source_count: 1,
        sources_preview: [{
          location_id: 5,
          location_name: "Main",
          location_type: "WAREHOUSE",
          on_hand_quantity: "1",
          reserved_quantity: "0",
        }],
        sources_truncated: false,
      }],
      next_cursor: null,
      has_more: false,
    });
    expect(parsed.items[0]).toMatchObject({ batch_id: 99, batch_number: null });
  });

  it("keeps product-quality actions available for an anonymous batch", () => {
    const parsed = parseProductQualityPage(qualityPage(null));
    expect(parsed.batches[0]).toMatchObject({ batchId: 99, batchNumber: null });
    expect(parsed.batches[0].sources[0].statuses[0].movableQuantity).toBe("1");

    expect(parseProductQualityPage(qualityPage("REAL-LOT-Q")).batches[0].batchNumber).toBe("REAL-LOT-Q");
    expect(() => parseProductQualityPage(qualityPage(""))).toThrow("PRODUCT_QUALITY_ACTIONS_RESPONSE_INVALID");
  });

  it("accepts null but not missing batch numbers across stocktake count/review/session responses", () => {
    const countItem = {
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
      expiry_date: null,
    };
    expect(parseCountSheet([countItem])[0]).toMatchObject({ batch_id: 99, batch_number: null });
    const missingCount = { ...countItem } as Record<string, unknown>;
    delete missingCount.batch_number;
    expect(() => parseCountSheet([missingCount])).toThrow();

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
    const reviewLine = {
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
      expiry_date: null,
      expected_quantity: "1",
      actual_quantity: "1",
      variance_quantity: "0",
      notes: null,
    };
    const review = parseStocktakeReview({
      session_id: 1,
      reference_number: "ST-1",
      stocktake_type: "CYCLE_COUNT",
      status: "PENDING_REVIEW",
      location_id: 5,
      independent_recount_satisfied: false,
      latest_attempt: attempt,
      attempt_history: [attempt],
      lines: [reviewLine],
    });
    expect(review.lines[0]).toMatchObject({ batch_id: 99, batch_number: null });

    const session = {
      id: 1,
      reference_number: "ST-1",
      stocktake_type: "CYCLE_COUNT",
      status: "COUNTING",
      location_id: 5,
      scope_product_variant_id: 10,
      scope_product_name: "Product",
      scope_batch_id: 99,
      scope_batch_number: null,
      related_work_session_id: null,
      started_by: 1,
      started_by_name: "Counter",
      pending_independent_recount_required: false,
      snapshot_cutoff_at: null,
      created_at: "2026-10-15T10:00:00Z",
      updated_at: "2026-10-15T10:00:00Z",
    };
    expect(parseStocktakeSessionPage({
      items: [session],
      next_cursor: null,
      has_more: false,
      total: 1,
    }, 5).items[0]).toMatchObject({ scope_batch_id: 99, scope_batch_number: null });
  });


  it("keeps Ledger public lots nullable while rejecting empty API values", () => {
    const entry = {
      id: 44,
      product_variant_id: 10,
      product_name: "Product",
      base_uom_id: 1,
      base_uom_code: "EA",
      quantity_scale: 0,
      quantity_step: "1",
      type: "INBOUND_SUPPLIER",
      quantity: "1",
      balance_before: "0",
      balance_after: "1",
      balance_scope: "PRODUCT_LOCATION",
      batch_number: null,
      display_uom_id: 1,
      display_uom_code: "EA",
      display_uom_name: "Each",
      display_factor_to_base: "1",
      currency_code: "JOD",
      cost_method: null,
      input_quantity: null,
      input_uom_code: null,
      input_uom_name: null,
      input_unit_cost: null,
      total_cost: null,
      average_cost_after: null,
      average_cost_uom_code: null,
      average_cost_uom_name: null,
      admin_name: "Operator",
      reference: "INV-1",
      notes: null,
      supplier_name: null,
      supplier_code: null,
      supplier_id: null,
      date: "2026-10-15T10:00:00+03:00",
    };
    const page = (batch_number: unknown) => ({
      items: [{ ...entry, batch_number }],
      next_cursor: null,
      has_more: false,
      total: 1,
      available_types: ["INBOUND_SUPPLIER"],
    });
    expect(parseLedgerPage(page(null)).items[0].batch_number).toBeNull();
    expect(parseLedgerPage(page("REAL-LOT-L")).items[0].batch_number).toBe("REAL-LOT-L");
    expect(() => parseLedgerPage(page(""))).toThrow();
  });

});
