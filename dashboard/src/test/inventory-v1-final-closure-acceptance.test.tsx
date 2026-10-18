import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "@/i18n";
import { SettlementModal } from "@/components/operations/SettlementModal";
import { Tab3Stocktake } from "@/pages/inventory/Tab3Stocktake";
import {
  FINANCIAL_SETTLEMENT_READY_STATUS,
  type DriverData,
  type SessionSettlementReport,
} from "@/data/operations-data";

const access = vi.hoisted(() => ({
  data: { company_id: 41, backoffice_user_id: 77 },
  can: () => true,
  canAny: () => true,
}));
vi.mock("@/hooks/useInventoryAccess", () => ({
  useInventoryAccess: () => access,
}));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

const inventory = [{
  product_id: 13, product_name: "Acceptance product",
  starting_quantity: 10, sold_quantity: 0, remaining_quantity: 10,
  packs_per_carton: 6, starting_cartons: 1, starting_loose_packs: 4,
  sold_cartons: 0, sold_loose_packs: 0, remaining_cartons: 1, remaining_loose_packs: 4,
}];
const report: SessionSettlementReport = {
  driver_name: "Acceptance representative", session_date: "2026-10-18",
  status: FINANCIAL_SETTLEMENT_READY_STATUS,
  financials: {
    expected_cash_in_hand: "10.000", cash_from_sales: "10.000",
    cash_from_debts: "0.000", inventory_shortage_cash: "0.000",
  },
  visits: { completed_total: 1, successful_sales: 1, pending_remaining: 0 },
  inventory, samples_given: [],
};
const driver: DriverData = {
  session: {
    session_id: 19, driver_name: report.driver_name, start_time: null,
    is_authorized_to_sell: false, is_on_break: false, vehicle_label: "Acceptance vehicle",
  },
  settlement: report,
};

beforeEach(() => localStorage.clear());
afterEach(cleanup);

describe("Independent Inventory V1 final closure", () => {
  it.each(["en", "ar"])("Stocktake has no second representative start (%s)", async language => {
    await i18n.changeLanguage(language);
    const authenticatedFetch = vi.fn().mockResolvedValue({
      items: [], total: 0, next_cursor: null, has_more: false,
    });
    render(<Tab3Stocktake
      locationId={7} companyId="41" isAuditLocked={false}
      authenticatedFetch={authenticatedFetch} onStocktakeChanged={vi.fn()}
    />);
    await waitFor(() => expect(authenticatedFetch).toHaveBeenCalled());
    expect(screen.queryByRole("button", {
      name: /Vehicle recon|تسوية سيارة|Custody receipt|استلام العهدة/i,
    })).toBeNull();
    // Keep normal warehouse counting available; no removal of Stocktake itself.
    expect(screen.getAllByRole("button").length).toBeGreaterThan(0);
  });

  it.each(["en", "ar"])("financial close has cash input but no second stock count (%s)", async language => {
    await i18n.changeLanguage(language);
    render(<SettlementModal
      isOpen onClose={vi.fn()} driver={driver} report={report}
      isReportLoading={false} reportError={null} onRetryReport={vi.fn()}
      isSubmitting={false} onConfirmSettlement={vi.fn()}
    />);
    const dialog = await screen.findByRole("dialog");
    // Cash is the only editable numeric value. Sealed stock may be displayed read-only.
    const editableNumbers = Array.from(dialog.querySelectorAll<HTMLInputElement>(
      'input[type="number"], input[inputmode="numeric"], input[inputmode="decimal"]',
    )).filter(input => !input.readOnly && !input.disabled);
    expect(editableNumbers).toHaveLength(1);
    expect(editableNumbers[0]).toHaveValue(10);
  });
});
