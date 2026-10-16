import { describe, expect, it, vi } from "vitest";

import {
  adjustmentDelta,
  parseLedgerPage,
} from "@/pages/inventory/ledger/contracts";
import { ledgerMovementLabel } from "@/pages/inventory/ledger/ledgerI18n";

const rawEntry = (batchNumber: string | null = null) => ({
  id: 1,
  product_variant_id: 10,
  product_name: "Product",
  base_uom_id: 1,
  base_uom_code: "EACH",
  quantity_scale: 6,
  quantity_step: "0.000001",
  type: "INBOUND_SUPPLIER",
  reference_type: "INBOUND_SUPPLIER",
  movement_kind: "PHYSICAL",
  quantity: "1.000001",
  balance_before: "0",
  balance_after: "1.000001",
  balance_scope: "PRODUCT_LOCATION",
  batch_id: 5,
  batch_number: batchNumber,
  source_location_id: null,
  source_location_name: null,
  destination_location_id: 11,
  destination_location_name: "Warehouse",
  source_stock_status: null,
  destination_stock_status: "AVAILABLE",
  display_uom_id: 1,
  display_uom_code: "EACH",
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
  admin_name: "Actor",
  reference: "REF-1",
  notes: null,
  supplier_name: null,
  supplier_code: null,
  supplier_id: null,
  date: "2026-10-16T12:00:00+00:00",
});

const page = (batchNumber: string | null) => ({
  items: [rawEntry(batchNumber)],
  next_cursor: null,
  has_more: false,
  total: 1,
  available_types: ["INBOUND_SUPPLIER"],
});

describe("CP10 Ledger business contracts", () => {
  it("accepts public anonymous lot but rejects every internal no-lot identity", () => {
    expect(parseLedgerPage(page(null)).items[0].batch_number).toBeNull();
    expect(() => parseLedgerPage(page("__WANASAH_NOLOT__:SECRET"))).toThrow("LEDGER_INTERNAL_NO_LOT_LEAK");
  });

  it("keeps adjustment decimal math exact without Number conversion", () => {
    expect(adjustmentDelta("8.000001", "10.250001")).toBe("-2.25");
    expect(adjustmentDelta("10.250002", "10.250001")).toBe("0.000001");
  });

  it("identifies practical V1 cross-link movement evidence in both languages", () => {
    const translate = vi.fn((_key: string, options?: Record<string, unknown>) => String(options?.defaultValue ?? _key));
    for (const type of ["INBOUND_SUPPLIER", "TRANSFER", "STOCKTAKE", "STOCKTAKE_ADJUSTMENT", "STATUS_CHANGE"]) {
      expect(ledgerMovementLabel(translate as never, "en", type)).not.toBe(type);
      expect(ledgerMovementLabel(translate as never, "ar", type)).not.toBe(type);
    }
  });
});
