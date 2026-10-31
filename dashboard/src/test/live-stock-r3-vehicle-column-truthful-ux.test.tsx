import { cleanup, render, screen } from "@testing-library/react";
import { createInstance } from "i18next";
import { I18nextProvider } from "react-i18next";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";

import { resources } from "@/i18n/resources";
import { LiveStockFilters } from "@/pages/inventory/liveStock/LiveStockFilters";
import { LiveStockMobileCards } from "@/pages/inventory/liveStock/LiveStockMobileCards";
import { LiveStockTable } from "@/pages/inventory/liveStock/LiveStockTable";
import type {
  LiveStockIndicator,
  LiveStockStockState,
  WarehouseProduct,
} from "@/pages/inventory/liveStock/contracts";

const mocks = vi.hoisted(() => ({
  authFetch: vi.fn(),
}));

vi.mock("@/hooks/useAuthFetch", () => ({
  useAuthFetch: () => mocks.authFetch,
}));

// The focused test verifies LiveStockFilters copy/accessibility, not Radix portal geometry.
vi.mock("@/components/ui/popover", () => ({
  Popover: ({ children }: { children: ReactNode }) => <>{children}</>,
  PopoverTrigger: ({ children }: { children: ReactNode }) => <>{children}</>,
  PopoverContent: ({
    children,
    dir,
    className,
  }: {
    children: ReactNode;
    dir?: string;
    className?: string;
  }) => (
    <div dir={dir} className={className}>
      {children}
    </div>
  ),
}));

const baseProduct: WarehouseProduct = {
  id: 41,
  name: "R3 Product",
  sku: "R3-SKU",
  product_id: 7,
  family_name: "R3 Family",
  base_uom_id: 1,
  base_uom_code: "EA",
  base_uom_name: "Each",
  display_uom_id: 1,
  display_uom_code: "EA",
  display_uom_name: "Each",
  display_factor_to_base: "1",
  currency_code: "JOD",
  average_cost_display: null,
  last_purchase_cost: null,
  last_purchase_uom_code: null,
  last_purchase_date: null,
  quantity_scale: 6,
  quantity_step: "0.000001",
  on_hand_quantity: "100",
  reserved_quantity: "0",
  available_for_sale_quantity: "100",
  unavailable_quantity: "0",
  vehicle_quantity: "12",
  recalled_quantity: "0",
  available_quantity: "100",
  blocked_quantity: "0",
  total_quantity: "112",
  damaged_quantity: "0",
  minimum_quantity: "0",
  is_low_stock: false,
};

const products: WarehouseProduct[] = [
  baseProduct,
  {
    ...baseProduct,
    id: 42,
    name: "R3 Zero Attribution",
    sku: "R3-ZERO",
    vehicle_quantity: "0",
    total_quantity: "100",
  },
];

function FilterHarness() {
  const stockState: LiveStockStockState = "all";
  const indicators: LiveStockIndicator[] = [];
  return (
    <LiveStockFilters
      locationId={11}
      alertCount={0}
      stockState={stockState}
      indicators={indicators}
      familyId={null}
      onSearchChange={() => undefined}
      onStockStateChange={() => undefined}
      onIndicatorsChange={() => undefined}
      onFamilyChange={() => undefined}
    />
  );
}

async function languageProvider(language: "ar" | "en") {
  const i18n = createInstance();
  await i18n.init({
    resources,
    lng: language,
    fallbackLng: "en",
    interpolation: { escapeValue: false },
  });
  return i18n;
}

function copy(language: "ar" | "en") {
  return resources[language].translation.inventoryLive;
}

beforeEach(() => {
  mocks.authFetch.mockReset();
  mocks.authFetch.mockResolvedValue({
    items: [],
    has_more: false,
    next_cursor: null,
  });
});

afterEach(cleanup);

describe("R3 truthful vehicle-column UX", () => {
  it.each(["ar", "en"] as const)(
    "renders truthful desktop/mobile attribution meaning and preserves positive/zero values in %s",
    async (language) => {
      const i18n = await languageProvider(language);
      const labels = copy(language);
      const { container } = render(
        <I18nextProvider i18n={i18n}>
          <LiveStockTable products={products} loading={false} onOpen={vi.fn()} />
          <LiveStockMobileCards products={products} onOpen={vi.fn()} />
        </I18nextProvider>,
      );

      const desktopNote = container.querySelector(
        '[data-live-stock-vehicle-attribution-note="desktop"]',
      );
      const mobileNote = container.querySelector(
        '[data-live-stock-vehicle-attribution-note="mobile"]',
      );
      expect(desktopNote).toHaveTextContent(labels.withVehiclesVisibleNote);
      expect(mobileNote).toHaveTextContent(labels.withVehiclesMobileDisclosure);

      expect(screen.getAllByText(labels.withVehicles).length).toBeGreaterThan(1);
      expect(labels.withVehiclesHint).toContain(
        language === "ar" ? "مستودع آخر" : "another warehouse",
      );
      expect(labels.withVehiclesHint).toContain(
        language === "ar" ? "بلا خط مؤهل" : "without a qualifying route",
      );
      expect(labels.withVehiclesHint).toContain(
        language === "ar" ? "الصفر يعني صفر كمية منسوبة" : "Zero means zero attributed quantity",
      );

      const desktopVehicleCells = Array.from(
        container.querySelectorAll<HTMLTableCellElement>(
          'td[data-cp13-quantity="vehicle"]',
        ),
      );
      expect(desktopVehicleCells).toHaveLength(2);
      expect(desktopVehicleCells[0]).toHaveTextContent("12");
      expect(desktopVehicleCells[1]).toHaveTextContent("0");
      expect(desktopVehicleCells[0].getAttribute("aria-label")).toContain("12");
      expect(desktopVehicleCells[1].getAttribute("aria-label")).toContain("0");

      const mobileVehicleValues = Array.from(
        container.querySelectorAll<HTMLElement>(
          '[data-testid="live-stock-mobile-cards"] [data-cp13-quantity="vehicle"] dd',
        ),
      );
      expect(mobileVehicleValues).toHaveLength(2);
      expect(mobileVehicleValues[0]).toHaveTextContent("12");
      expect(mobileVehicleValues[1]).toHaveTextContent("0");
      expect(mobileVehicleValues[0].getAttribute("aria-label")).toContain("12");
      expect(mobileVehicleValues[1].getAttribute("aria-label")).toContain("0");

      console.log(
        "R3_VEHICLE_COLUMN_RENDER_EVIDENCE",
        JSON.stringify({
          language,
          desktopLabel: labels.withVehicles,
          desktopVisibleNote: labels.withVehiclesVisibleNote,
          mobileDisclosure: labels.withVehiclesMobileDisclosure,
          positiveAttributedQuantity: "12",
          zeroAttributedQuantity: "0",
        }),
      );
    },
  );

  it.each(["ar", "en"] as const)(
    "uses truthful vehicle-filter copy as its accessible name in %s without changing filter membership",
    async (language) => {
      const i18n = await languageProvider(language);
      const labels = copy(language);
      render(
        <I18nextProvider i18n={i18n}>
          <FilterHarness />
        </I18nextProvider>,
      );

      const vehicleFilter = screen.getByRole("button", {
        name: labels.indicatorVehicle,
      });
      expect(vehicleFilter).toHaveAttribute("aria-pressed", "false");
      expect(vehicleFilter).toHaveAttribute("type", "button");
      vehicleFilter.focus();
      expect(vehicleFilter).toHaveFocus();

      // The canonical filter value remains "vehicle"; only its localized presentation changes.
      expect(labels.indicatorVehicle).toBe(
        language === "ar" ? "عهدة عبر آخر خط" : "Vehicle via latest route",
      );
    },
  );
});
