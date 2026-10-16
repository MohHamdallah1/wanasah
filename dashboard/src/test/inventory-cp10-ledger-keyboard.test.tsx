import { useState } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { LedgerAdjustmentModal } from "@/pages/inventory/ledger/LedgerAdjustmentModal";
import type { LedgerEntry } from "@/pages/inventory/ledger/contracts";
import type { LedgerAdjustmentController } from "@/pages/inventory/ledger/useLedgerAdjustment";

vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));
vi.mock("react-i18next", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-i18next")>();
  return {
    ...actual,
    useTranslation: () => ({
      t: (key: string, options?: Record<string, unknown>) => String(options?.defaultValue ?? key),
      i18n: { language: "en", resolvedLanguage: "en", dir: () => "ltr" },
    }),
  };
});

const entry: LedgerEntry = {
  id: 4,
  product_variant_id: 100,
  product_name: "Keyboard Product",
  base_uom_id: 1,
  base_uom_code: "EACH",
  quantity_scale: 6,
  quantity_step: "0.000001",
  type: "INBOUND_SUPPLIER",
  reference_type: "INBOUND_SUPPLIER",
  movement_kind: "PHYSICAL",
  quantity: "10",
  balance_before: "0",
  balance_after: "10",
  balance_scope: "PRODUCT_LOCATION",
  batch_id: 22,
  batch_number: "LOT-1",
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
  admin_name: "Operator",
  reference: "INV-1",
  notes: null,
  supplier_name: null,
  supplier_code: null,
  supplier_id: null,
  date: "2026-10-16T12:00:00+00:00",
};

const translate = (_key: string, options?: Record<string, unknown>) =>
  String(options?.defaultValue ?? _key);

function Host() {
  const [open, setOpen] = useState(false);
  const controller: LedgerAdjustmentController = {
    entry: open ? entry : null,
    state: open ? {
      entry_id: 4,
      reference: "INV-1",
      product_variant_id: 100,
      batch_id: 22,
      warehouse_location_id: 11,
      current_total_quantity: "10",
      base_uom_id: 1,
      base_uom_code: "EACH",
    } : null,
    newTotal: "10",
    setNewTotal: vi.fn(),
    password: "secret",
    setPassword: vi.fn(),
    delta: "0",
    loading: false,
    submitting: false,
    error: null,
    open: vi.fn(),
    retryState: vi.fn(),
    submit: vi.fn(async () => ({ message: "saved", recovered: false })),
    close: () => setOpen(false),
  };
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>Open adjustment</button>
      <LedgerAdjustmentModal
        t={translate as never}
        language="en"
        controller={controller}
        onChanged={() => undefined}
      />
    </>
  );
}

describe("CP10 Ledger keyboard/focus", () => {
  it("focuses the first useful field, traps Tab, closes on Escape, and returns focus", async () => {
    render(<Host />);
    const trigger = screen.getByRole("button", { name: "Open adjustment" });
    trigger.focus();
    expect(trigger).toHaveFocus();
    fireEvent.click(trigger);

    const quantity = await screen.findByRole("textbox", { name: "Requested correct total" });
    await waitFor(() => expect(quantity).toHaveFocus());

    const lastControl = screen.getByRole("button", { name: "Record correction" });
    lastControl.focus();
    fireEvent.keyDown(document, { key: "Tab" });
    expect(screen.getByRole("button", { name: "common.close" })).toHaveFocus();

    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await waitFor(() => expect(trigger).toHaveFocus());
  });
});
