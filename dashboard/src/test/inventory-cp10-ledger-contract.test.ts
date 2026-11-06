import { describe, expect, it, vi } from "vitest";

import {
  adjustmentDelta,
  parseLedgerPage,
} from "@/pages/inventory/ledger/contracts";
import { ledgerMovementLabel, ledgerStatusLabel } from "@/pages/inventory/ledger/ledgerI18n";
import { buildLedgerCursorUrl } from "@/pages/inventory/ledger/buildLedgerCursorUrl";
import { createStocktakeLedgerReferenceTarget, parseStocktakeLedgerReferenceQuery } from "@/pages/inventory/ledger/stocktakeLedgerNavigation";
import { parseInventoryNavigationState } from "@/features/inventory/navigation";
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
    for (const type of ["INBOUND_SUPPLIER", "TRANSFER", "STOCKTAKE", "STOCKTAKE_ADJUSTMENT", "AUDIT_ADJUSTMENT", "STATUS_CHANGE"]) {
      expect(ledgerMovementLabel(translate as never, "en", type)).not.toBe(type);
      expect(ledgerMovementLabel(translate as never, "ar", type)).not.toBe(type);
    }
  });

  it("renders canonical AUDIT_ADJUSTMENT as stocktake adjustment, not raw code", () => {
    const translate = vi.fn((_key: string, options?: Record<string, unknown>) => String(options?.defaultValue ?? _key));
    expect(ledgerMovementLabel(translate as never, "ar", "AUDIT_ADJUSTMENT")).toBe("تسوية جرد");
    expect(ledgerMovementLabel(translate as never, "en", "AUDIT_ADJUSTMENT")).toBe("Stocktake adjustment");
    expect(ledgerMovementLabel(translate as never, "ar", "TRANSFER_RECEIPT")).toBe("استلام حوالة");
    expect(ledgerMovementLabel(translate as never, "en", "VISIT_RETURN_IN")).toBe("Visit return in");
  });

  it("routes exact stocktake reference using the existing tab/warehouse authority", () => {
    const target = createStocktakeLedgerReferenceTarget({ locationId: 17, reference: "STK-AB12" });
    expect(target.pathname).toBe("/inventory");
    expect(parseStocktakeLedgerReferenceQuery(target.search)).toEqual({ locationId: 17, reference: "STK-AB12" });
    expect(parseInventoryNavigationState(target.state)).toEqual({
      version: 1, kind: "tab", tab: "ledger", locationId: 17,
    });
    expect(parseStocktakeLedgerReferenceQuery("?ledger_ref=STK-AB12&ledger_ref=STK-BAD&ledger_location=17")).toBeNull();
    expect(parseStocktakeLedgerReferenceQuery("?ledger_ref=STK-AB12&ledger_location=0")).toBeNull();
    expect(parseStocktakeLedgerReferenceQuery("?ledger_ref=STOCKTAKE_CANCELLED&ledger_location=17")).toBeNull();
    expect(() => createStocktakeLedgerReferenceTarget({locationId: -1, reference: "STK-AB12"})).toThrow();
  });

  it("queries one exact warehouse + STK reference, never fuzzy search or cancelled type", () => {
    const url = buildLedgerCursorUrl({ locationId: 17, referenceType: "AUDIT_ADJUSTMENT",
      referenceId: "STK-AB12", search: "some other product", limit: 20 });
    const params = new URL(url, "https://ledger.test").searchParams;
    expect(params.get("location_id")).toBe("17");
    expect(params.get("reference_type")).toBe("AUDIT_ADJUSTMENT");
    expect(params.get("reference_id")).toBe("STK-AB12");
    expect(params.get("search")).toBeNull();
    expect(params.get("cursor")).toBeNull();
  });
});
