import { describe, expect, it, vi } from "vitest";

import {
  adjustmentDelta,
  parseLedgerPage,
} from "@/pages/inventory/ledger/contracts";
import { ledgerMovementLabel, ledgerStatusLabel } from "@/pages/inventory/ledger/ledgerI18n";
import { ledgerBalance, ledgerLocationEvidence, ledgerQuantityMeaning } from "@/pages/inventory/ledger/ledgerPresentation";

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

  it("never presents reservation or stock-status movement as physical on-hand change", () => {
    const t = vi.fn((_key: string, options?: Record<string, unknown>) => String(options?.defaultValue ?? _key));
    const base = parseLedgerPage(page(null)).items[0];
    const reservation = { ...base, movement_kind: "RESERVATION", quantity: "-3",
      balance_before: "10", balance_after: "10" } as const;
    const statusChange = { ...base, movement_kind: "STATUS_CHANGE", quantity: "-3",
      balance_before: "10", balance_after: "10", source_stock_status: "AVAILABLE",
      destination_stock_status: "DAMAGED" } as const;
    expect(ledgerBalance(reservation, reservation.balance_before, code => code)).toBe("10 EACH");
    expect(ledgerBalance(reservation, reservation.balance_after, code => code)).toBe("10 EACH");
    expect(ledgerQuantityMeaning(t as never, "en", reservation)).toContain("no physical movement");
    expect(ledgerQuantityMeaning(t as never, "ar", reservation)).toContain("دون نقل بضاعة");
    expect(ledgerQuantityMeaning(t as never, "en", statusChange)).toContain("no physical stock added");
    expect(ledgerQuantityMeaning(t as never, "ar", statusChange)).toContain("دون إضافة");
    expect(ledgerStatusLabel(t as never, "ar", "DAMAGED")).toBe("تالف");
    expect(ledgerStatusLabel(t as never, "ar", "RECALLED")).toBe("مسحوب من البيع");
    expect(ledgerQuantityMeaning(t as never, "en", base)).toContain("Physical");
    const vehicle = { ...base, source_location_type: "VEHICLE",
      source_location_name: "V-7", destination_location_type: "IN_TRANSIT",
      destination_location_name: "Transit custody" };
    const evidence = ledgerLocationEvidence(t as never, "ar", vehicle);
    expect(evidence.source).toContain("مركبة");
    expect(evidence.destination).toContain("عهدة عبور");
  });

  it("identifies practical V1 cross-link movement evidence in both languages", () => {
    const translate = vi.fn((_key: string, options?: Record<string, unknown>) => String(options?.defaultValue ?? _key));
    for (const type of ["INBOUND_SUPPLIER", "TRANSFER", "STOCKTAKE", "STOCKTAKE_ADJUSTMENT", "STATUS_CHANGE"]) {
      expect(ledgerMovementLabel(translate as never, "en", type)).not.toBe(type);
      expect(ledgerMovementLabel(translate as never, "ar", type)).not.toBe(type);
    }
  });
});
