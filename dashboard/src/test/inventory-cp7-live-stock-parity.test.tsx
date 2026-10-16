import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LiveStockTable } from "@/pages/inventory/liveStock/LiveStockTable";
import type { WarehouseProduct } from "@/pages/inventory/liveStock/contracts";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, options?: { defaultValue?: string; number?: number; unit?: string }) => {
      if (key === "inventoryLive.rowNumber") return `row ${options?.number}`;
      if (key === "inventoryLive.perUnit") return `per ${options?.unit}`;
      return options?.defaultValue ?? key;
    },
    i18n: {
      language: "en",
      resolvedLanguage: "en",
      dir: () => "ltr",
    },
  }),
}));

afterEach(cleanup);

const product: WarehouseProduct = {
  id: 41,
  name: "Parity Product",
  sku: "SKU-41",
  product_id: 4,
  family_name: "Parity Family",
  base_uom_id: 1,
  base_uom_code: "EA",
  base_uom_name: "Each",
  display_uom_id: 1,
  display_uom_code: "EA",
  display_uom_name: "Each",
  display_factor_to_base: "1",
  currency_code: "JOD",
  average_cost_display: "1.250000",
  last_purchase_cost: "1.500000",
  last_purchase_uom_code: "EA",
  last_purchase_date: "2026-10-15",
  quantity_scale: 6,
  quantity_step: "0.000001",
  on_hand_quantity: "2.500001",
  reserved_quantity: "0.500001",
  available_for_sale_quantity: "0.750001",
  unavailable_quantity: "1.25",
  vehicle_quantity: "0.125",
  recalled_quantity: "0",
  available_quantity: "0.750001",
  blocked_quantity: "0",
  total_quantity: "2.500001",
  damaged_quantity: "0",
  minimum_quantity: "1",
};

describe("CP7 Live Stock refactor parity", () => {
  it("preserves product identity, family, minimum stock and all quantity columns", () => {
    render(<LiveStockTable products={[product]} loading={false} onOpen={vi.fn()} />);

    expect(screen.getByText("Parity Product")).toBeInTheDocument();
    expect(screen.getByText("SKU-41")).toBeInTheDocument();
    expect(screen.getByText("Parity Family")).toBeInTheDocument();
    expect(screen.getByText(/inventoryLive.minimumStockLabel/)).toBeInTheDocument();
    expect(document.body.textContent).toContain("2.500001");
    expect(document.body.textContent).toContain("0.500001");
    expect(document.body.textContent).toContain("0.750001");
    expect(document.body.textContent).toContain("1.25");
    expect(document.body.textContent).toContain("0.125");
  });

  it("keeps keyboard-native detail reachability and row accessibility", () => {
    const open = vi.fn();
    render(<LiveStockTable products={[product]} loading={false} onOpen={open} />);

    const detail = screen.getByRole("button", { name: /View batch details: Parity Product/i });
    detail.focus();
    expect(detail).toHaveFocus();
    fireEvent.click(detail);
    expect(open).toHaveBeenCalledWith(product);
    expect(screen.getByLabelText("row 1")).toBeInTheDocument();
  });

  it("preserves accessible quantity and cost help affordances", () => {
    render(<LiveStockTable products={[product]} loading={false} onOpen={vi.fn()} />);

    expect(screen.getByRole("button", { name: "inventoryLive.onHandHint" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "inventoryLive.availableForSaleHint" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "inventoryLive.lastCompanyPurchaseHint" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "inventoryLive.companyAverageHint" })).toBeInTheDocument();
  });
});
