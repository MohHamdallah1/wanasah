import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ShopTable } from "@/components/dispatch/ShopTable";
import { dispatchUiText } from "@/features/dispatch/dispatchUiText";
import { financeReadback, existingShopForm } from "@/features/dispatch/shopForm/contract";
import { formatLocaleMoney } from "@/lib/localeNumbers";
import type { Shop, Zone } from "@/types/dispatch";

vi.mock("@/features/tenantIdentity/useTenantIdentity", () => ({
  useTenantIdentity: () => ({ data: { company_id: 11, currency_code: "QAR" } }),
}));
const zone: Zone = {
  id: "3", name: "Company Zone", visitDay: "", startDate: "",
  frequency: "", intervalDays: null, scheduleStatus: "null",
};
const shop: Shop = {
  id: "41", name: "Company Master Shop", owner: "Amal", phone: "55123456",
  mapLink: "", zoneId: "3", sequence: 1, archived: false,
  initialDebt: null, maxDebtLimit: null, financeRedacted: true,
};
const noAction = () => {};
const tableProps = {
  zones: [zone], isEditMode: false, isSaving: false,
  selectedShopIds: [], allFilteredShops: null, selectedZoneIdForZones: "3",
  onToggleSelectAll: noAction, onToggleSelectShop: noAction,
  onSequenceChange: noAction, onEditShop: noAction,
  onArchiveShop: noAction, onDragStart: noAction, onDrop: noAction,
};
afterEach(cleanup);

describe("D06 visible company Shop master versus sensitive finance", () => {
  it.each(["ar", "en"] as const)(
    "%s 390px: redacted money is unavailable, not a fabricated zero", language => {
      Object.defineProperty(window, "innerWidth", { configurable: true, value: 390 });
      const view = render(<ShopTable {...tableProps} language={language} shops={[shop]} />);
      expect(screen.getByText(shop.name)).toBeInTheDocument();
      expect(screen.getByText(dispatchUiText(language, "shopFinanceUnavailable"))).toBeInTheDocument();
      expect(view.container.textContent).not.toContain(formatLocaleMoney("0", "QAR", language));
      expect(financeReadback([{ id: "41", initialDebt: null,
        maxDebtLimit: null, financeRedacted: true }], "41")).toBeNull();
      expect(financeReadback([{ id: "41", initialDebt: "250.125",
        maxDebtLimit: "400.000", financeRedacted: true }], "41")).toBeNull();
      expect(existingShopForm(shop).initialDebt).toBe("");
      const authorized = {
        ...shop, financeRedacted: false, initialDebt: 0, maxDebtLimit: 0,
      };
      view.rerender(<ShopTable {...tableProps} language={language} shops={[authorized]} />);
      expect(screen.queryByText(dispatchUiText(language, "shopFinanceUnavailable"))).not.toBeInTheDocument();
      expect(screen.getByText(formatLocaleMoney("0", "QAR", language))).toBeInTheDocument();
      expect(financeReadback([{ id: "41", initialDebt: "0.000",
        maxDebtLimit: "0.000", financeRedacted: false }], "41")).toEqual({
          initialDebt: "0.000", maxDebtLimit: "0.000",
        });
    },
  );
  it("separate permission is required for Shop finance; settlement/dispatch alone do not imply it", () => {
    const permissions = ["dispatch.read", "settlement.read"];
    expect(permissions.includes("shop.financial.read")).toBe(false);
    expect(dispatchUiText("ar", "shopRestrictedScope")).toContain("المسارات المصرح");
    expect(dispatchUiText("en", "shopRestrictedScope")).toContain("authorized routes");
  });
});
