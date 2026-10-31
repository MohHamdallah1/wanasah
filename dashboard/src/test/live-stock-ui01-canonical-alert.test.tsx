import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LiveStockTable } from "@/pages/inventory/liveStock/LiveStockTable";
import { LiveStockMobileCards } from "@/pages/inventory/liveStock/LiveStockMobileCards";
import { parseLiveStockPage, type WarehouseProduct } from "@/pages/inventory/liveStock/contracts";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, opts?: { defaultValue?: string }) => opts?.defaultValue ?? key,
    i18n: { language: "en", resolvedLanguage: "en", dir: () => "ltr" },
  }),
}));
afterEach(cleanup);

const basic: WarehouseProduct = {
  id: 1, name: "Policy item", sku: "SKU-1", product_id: 1, family_name: "Family",
  base_uom_id: 1, base_uom_code: "EA", base_uom_name: "Each",
  display_uom_id: 1, display_uom_code: "EA", display_uom_name: "Each",
  display_factor_to_base: "1", currency_code: "JOD",
  average_cost_display: null, last_purchase_cost: null,
  last_purchase_uom_code: null, last_purchase_date: null,
  quantity_scale: 0, quantity_step: "1", on_hand_quantity: "10",
  reserved_quantity: "0", available_for_sale_quantity: "10",
  unavailable_quantity: "0", vehicle_quantity_scope: "COMPANY_WIDE" as const, vehicle_quantity: "0", recalled_quantity: "0",
  available_quantity: "10", blocked_quantity: "0", total_quantity_scope: "WAREHOUSE_PHYSICAL" as const, total_quantity: "10",
  damaged_quantity: "0", minimum_quantity: "10", is_low_stock: true,
};

function renderPair(p: WarehouseProduct) {
  render(
    <>
      <LiveStockTable products={[p]} loading={false} onOpen={vi.fn()} />
      <LiveStockMobileCards products={[p]} onOpen={vi.fn()} />
    </>,
  );
  return {
    row: document.querySelector(".live-stock-row") as HTMLElement,
    card: screen.getByRole("listitem"),
  };
}

describe("UI-01 server-owned low-stock alerts", () => {
  it.each([
    ["ACTIVE at boundary", "10", "10", true],
    ["ACTIVE below threshold", "9", "10", true],
    ["ACTIVE above threshold", "11", "10", false],
    ["RETIRING with zero sellable", "0", "10", false],
    ["SALES_HOLD with zero sellable", "0", "10", false],
    ["RECALL with zero sellable", "0", "10", false],
    ["zero minimum", "0", "0", false],
  ])("obeys canonical flag on desktop and mobile: %s",
    (_scenario, sellable, minimum, flag) => {
      const { row, card } = renderPair({
        ...basic, available_for_sale_quantity: sellable,
        available_quantity: sellable, minimum_quantity: minimum,
        is_low_stock: flag,
      });
      expect(row).toHaveClass(flag ? "bg-red-50/45" : "bg-white");
      expect(card).toHaveClass(flag ? "border-red-200" : "border-slate-200");
      expect(row.querySelector('[aria-label="inventoryLive.atMinimum"]') !== null).toBe(flag);
      expect(card.querySelector('[aria-label="inventoryLive.atMinimum"]') !== null).toBe(flag);
    },
  );

  it("honors the authoritative flag even when local arithmetic would disagree", () => {
    const { row, card } = renderPair({
      ...basic, minimum_quantity: "99", available_for_sale_quantity: "0",
      is_low_stock: false,
    });
    expect(row).toHaveClass("bg-white");
    expect(card).toHaveClass("border-slate-200");
  });

  it("accepts a boolean flag and rejects omitted, null or string values", () => {
    const page = (flag: unknown) => ({
      items: [{ ...basic, is_low_stock: flag }],
      next_cursor: null,
      has_more: false,
      total: null,
      alert_count: null,
      alert_samples: [],
    });
    expect(parseLiveStockPage(page(true)).items[0].is_low_stock).toBe(true);
    expect(parseLiveStockPage(page(false)).items[0].is_low_stock).toBe(false);
    expect(() => parseLiveStockPage(page(null))).toThrow();
    expect(() => parseLiveStockPage(page("true"))).toThrow();
    expect(() => parseLiveStockPage(page(undefined))).toThrow();
  });
});
