import { resources } from "@/i18n/resources";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { WarehouseProduct } from "@/pages/inventory/liveStock/contracts";
import { BatchDetailPanel } from "@/pages/inventory/liveStock/BatchDetailPanel";
import { getLiveStockCp7Copy } from "@/pages/inventory/liveStock/i18n";
import { LiveStockMobileCards } from "@/pages/inventory/liveStock/LiveStockMobileCards";
import { LiveStockTable } from "@/pages/inventory/liveStock/LiveStockTable";
import { resolveAppLocale } from "@/lib/locale";
import { formatMoneyDisplay, formatMoneyExact } from "@/lib/money";
import { parseLiveStockWarehouseSource, type LiveStockReservationEvidence } from "@/pages/inventory/liveStock/sourceContract";

const mocks = vi.hoisted(() => ({
  language: "en",
  t: (key: string, options?: { unit?: string; defaultValue?: string }) => {
    if (key.startsWith("uom.")) return key.slice(4);
    if (key.startsWith("inventoryLive.vehicleScopes.")) {
      const scope = key.split(".").at(-1) as "COMPANY_WIDE" | "AUTHORIZED_LOCATIONS" | "NO_ACCESS";
      return resources[mocks.language === "ar" ? "ar" : "en"].translation.inventoryLive.vehicleScopes[scope];
    }
    if (key === "inventoryLive.perUnit") {
      return `${mocks.language === "ar" ? "لكل" : "per"} ${options?.unit ?? ""}`;
    }
    return options?.defaultValue ?? key;
  },
}));

vi.mock("react-i18next", () => ({
  initReactI18next: { type: "3rdParty", init: () => undefined },
  useTranslation: () => ({
    t: mocks.t,
    i18n: {
      language: mocks.language,
      resolvedLanguage: mocks.language,
      dir: () => (mocks.language === "ar" ? "rtl" : "ltr"),
    },
  }),
}));

vi.mock("framer-motion", () => ({
  AnimatePresence: ({ children }: { children: React.ReactNode }) => children,
  motion: {
    div: ({ children, ...props }: React.HTMLAttributes<HTMLDivElement>) => (
      <div {...props}>{children}</div>
    ),
  },
}));

afterEach(() => {
  cleanup();
  mocks.language = "en";
});

const product: WarehouseProduct = {
  id: 41,
  name: "Product 41",
  sku: "SKU-41",
  product_id: 4,
  family_name: "Family",
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
  available_for_sale_quantity: "2",
  unavailable_quantity: "0",
  vehicle_quantity_scope: "COMPANY_WIDE" as const, vehicle_quantity: "0",
  recalled_quantity: "0",
  available_quantity: "2",
  blocked_quantity: "0",
  total_quantity_scope: "WAREHOUSE_PHYSICAL" as const, total_quantity: "2.500001",
  damaged_quantity: "0",
  minimum_quantity: "1",
  is_low_stock: false,
};

const sourcePayload = () => ({
  location_id: 11,
  location_name: "Warehouse A1",
  product_variant_id: 41,
  batch_id: 71,
  statuses: [
    {
      stock_status: "AVAILABLE",
      on_hand_quantity: "2.500001",
      reserved_quantity: "0.500001",
      movable_quantity: "2",
      reservation_evidence: {
        coverage: "COMPLETE",
        reason: null,
        owners: [
          {
            owner_type: "DISPATCH_HANDSHAKE",
            module: "DISPATCH",
            transfer_id: 91,
            reference_number: "TR-91",
            transfer_purpose: "ROUTE_LOAD",
            work_session_id: 31,
            route_id: 21,
            expected_receiver_id: 51,
            created_by: 61,
            quantity: "0.500001",
            operation_status: "PENDING",
            navigation_target: "DISPATCH_ROUTE_TRANSFERS",
            action: null,
          },
        ],
        unattributed_quantity: "0",
        owners_truncated: false,
      },
    },
  ],
});

const batch = {
  batch_id: 71,
  batch_number: null,
  production_date: null,
  expiry_date: null,
  disposition: "RELEASED" as const,
  disposition_reason: null,
  disposition_revision: 1,
  allowed_disposition_targets: ["QUARANTINED", "BLOCKED", "RECALLED"] as const,
  days_to_expiry: null,
  quantity_scale: 6,
  quantity_step: "0.000001" as const,
  on_hand_quantity: "2.500001" as const,
  reserved_quantity: "0.500001" as const,
  available_for_sale_quantity: "2" as const,
  unavailable_quantity: "0" as const,
  quarantined_quantity: "0" as const,
  blocked_quantity: "0" as const,
  recalled_quantity: "0" as const,
  damaged_quantity: "0" as const,
  disposal_pending_quantity: "0" as const,
  total_cost: "3.125001",
  average_cost: "1.250000",
  latest_purchase_unit_cost: "1.500000",
  latest_purchase_date: "2026-10-15",
  purchase_count: 1,
};

const source = (...parts: string[]) =>
  readFileSync(resolve(process.cwd(), ...parts), "utf8");

describe("CP7 Live Stock Dashboard closure", () => {
  it("has exact Arabic anonymous-lot presentation", () => {
    expect(getLiveStockCp7Copy("ar").noLot).toBe("بدون رقم تشغيلة");
  });

  it("has exact English anonymous-lot presentation", () => {
    expect(getLiveStockCp7Copy("en").noLot).toBe("No lot supplied");
  });

  it("never places the internal no-lot token in feature copy", () => {
    expect(JSON.stringify(getLiveStockCp7Copy("ar"))).not.toContain("__WANASAH_NOLOT__");
    expect(JSON.stringify(getLiveStockCp7Copy("en"))).not.toContain("__WANASAH_NOLOT__");
  });

  it("parses exact decimal warehouse source evidence without float conversion", () => {
    const parsed = parseLiveStockWarehouseSource(sourcePayload());
    expect(parsed.statuses[0].on_hand_quantity).toBe("2.500001");
    expect(parsed.statuses[0].reserved_quantity).toBe("0.500001");
    expect(parsed.statuses[0].movable_quantity).toBe("2");
  });

  it("rejects floating-point quantity business data", () => {
    const payload = sourcePayload();
    payload.statuses[0].on_hand_quantity = 2.5 as never;
    expect(() => parseLiveStockWarehouseSource(payload)).toThrow(
      "LIVE_STOCK_SOURCE_RESPONSE_INVALID",
    );
  });

  it("rejects duplicate source status identities", () => {
    const payload = sourcePayload();
    payload.statuses.push({ ...payload.statuses[0] });
    expect(() => parseLiveStockWarehouseSource(payload)).toThrow();
  });

  it("rejects reservation quantity larger than on-hand", () => {
    const payload = sourcePayload();
    payload.statuses[0].reserved_quantity = "9";
    expect(() => parseLiveStockWarehouseSource(payload)).toThrow();
  });

  it("preserves bounded reservation owner identity evidence", () => {
    const parsed = parseLiveStockWarehouseSource(sourcePayload());
    expect(parsed.statuses[0].reservation_evidence.owners).toEqual([
      { transfer_id: 91, reference_number: "TR-91", quantity: "0.500001" },
    ]);
  });

  it("renders a bounded mobile card rather than a desktop table", () => {
    render(<LiveStockMobileCards products={[product]} onOpen={vi.fn()} />);
    expect(screen.getByTestId("live-stock-mobile-cards")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("opens batch detail from the mobile card with a keyboard-native button", () => {
    const open = vi.fn();
    render(<LiveStockMobileCards products={[product]} onOpen={open} />);
    fireEvent.click(screen.getByRole("button"));
    expect(open).toHaveBeenCalledWith(product);
  });

  it("renders exact decimal quantities on mobile", () => {
    render(<LiveStockMobileCards products={[product]} onOpen={vi.fn()} />);
    expect(screen.getByText(/2\.500001/)).toBeInTheDocument();
  });

  it("renders anonymous lot without leaking internal identity in batch detail", () => {
    render(
      <BatchDetailPanel
        product={product}
        batches={[batch]}
        hasMore={false}
        loading={false}
        error={null}
        sourceByBatch={{}}
        sourceLoadingId={null}
        sourceErrorId={null}
        onClose={vi.fn()}
        onRetry={vi.fn()}
        onLoadMore={vi.fn()}
        onLoadSource={vi.fn()}
      />,
    );
    expect(screen.getByText("No lot supplied")).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("__WANASAH_NOLOT__");
  });

  it("renders Arabic detail copy and RTL through the shared modal", () => {
    mocks.language = "ar";
    render(
      <BatchDetailPanel
        product={product}
        batches={[batch]}
        hasMore={false}
        loading={false}
        error={null}
        sourceByBatch={{}}
        sourceLoadingId={null}
        sourceErrorId={null}
        onClose={vi.fn()}
        onRetry={vi.fn()}
        onLoadMore={vi.fn()}
        onLoadSource={vi.fn()}
      />,
    );
    expect(screen.getByText("بدون رقم تشغيلة")).toBeInTheDocument();
    expect(screen.getByRole("dialog").closest(".app-modal")).toHaveAttribute("dir", "rtl");
  });

  it("renders English detail copy and LTR", () => {
    render(
      <BatchDetailPanel
        product={product}
        batches={[batch]}
        hasMore={false}
        loading={false}
        error={null}
        sourceByBatch={{}}
        sourceLoadingId={null}
        sourceErrorId={null}
        onClose={vi.fn()}
        onRetry={vi.fn()}
        onLoadMore={vi.fn()}
        onLoadSource={vi.fn()}
      />,
    );
    expect(screen.getByRole("dialog").closest(".app-modal")).toHaveAttribute("dir", "ltr");
  });

  it("requests warehouse-scoped source evidence from a normal button", () => {
    const loadSource = vi.fn();
    render(
      <BatchDetailPanel
        product={product}
        batches={[batch]}
        hasMore={false}
        loading={false}
        error={null}
        sourceByBatch={{}}
        sourceLoadingId={null}
        sourceErrorId={null}
        onClose={vi.fn()}
        onRetry={vi.fn()}
        onLoadMore={vi.fn()}
        onLoadSource={loadSource}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Stock source and reservations" }));
    expect(loadSource).toHaveBeenCalledWith(71);
  });

  it("shows read-only source and reservation evidence without CP3 mutation controls", () => {
    const parsed = parseLiveStockWarehouseSource(sourcePayload());
    render(
      <BatchDetailPanel
        product={product}
        batches={[batch]}
        hasMore={false}
        loading={false}
        error={null}
        sourceByBatch={{ 71: parsed }}
        sourceOpenId={71}
        sourceLoadingId={null}
        sourceErrorId={null}
        onClose={vi.fn()}
        onRetry={vi.fn()}
        onLoadMore={vi.fn()}
        onLoadSource={vi.fn()}
      />,
    );
    expect(screen.getByText(/Warehouse A1/)).toBeInTheDocument();
    expect(screen.getByText("Movable quantity")).toBeInTheDocument();
    expect(screen.getByText(/Known reservations/)).toBeInTheDocument();
    expect(
      screen.queryAllByRole("button", {
        name: /dispose|recall|quarantine|return to vendor/i,
      }),
    ).toHaveLength(0);
  });

  it("uses shared Modal focus/Escape/focus-restore authority", () => {
    const panel = source("src/pages/inventory/liveStock/BatchDetailPanel.tsx");
    const modal = source("src/components/ui/modal.tsx");
    expect(panel).toContain('import { Modal } from "@/components/ui/modal"');
    expect(modal).toContain("useDialogFocusTrap");
    expect(modal).toContain("onClose");
  });

  it("keeps phone and desktop presentation separate without business-logic duplication", () => {
    const tab = source("src/pages/inventory/Tab1LiveStock.tsx");
    const desktop = source("src/pages/inventory/liveStock/LiveStockTable.tsx");
    const mobile = source("src/pages/inventory/liveStock/LiveStockMobileCards.tsx");
    expect(tab).toContain("<LiveStockTable");
    expect(tab).toContain("<LiveStockMobileCards");
    expect(desktop).toContain("hidden md:table");
    expect(mobile).toContain("md:hidden");
    expect(mobile).not.toContain("available_for_sale_quantity =");
  });

  it("keeps no-permission Live Stock requests fail-closed in MainInventory", () => {
    const main = source("src/pages/inventory/MainInventory.tsx");
    expect(main).toContain("if (selectedLocationId === null || !canReadStock) return;");
    expect(main).toContain("const canReadStock = locationAccess.can('inventory.read')");
  });

  it("guards stale warehouse responses with request sequence and abort", () => {
    const main = source("src/pages/inventory/MainInventory.tsx");
    expect(main).toContain("const requestSeq = ++stockRequestSeq.current");
    expect(main).toContain("stockAbortRef.current?.abort()");
    expect(main).toContain("if (requestSeq !== stockRequestSeq.current) return;");
  });

  it("resets rows and continuation before search/filter/family changes", () => {
    const main = source("src/pages/inventory/MainInventory.tsx");
    expect(main).toContain("const resetStockPagination = useCallback");
    expect(main).toContain("setStockCursor(null)");
    expect(main).toContain("setStockNextCursor(null)");
    expect(main).toContain("handleStockSearchChange");
    expect(main).toContain("handleStockStateChange");
    expect(main).toContain("handleStockIndicatorsChange");
    expect(main).toContain("handleStockFamilyChange");
  });

  it("deduplicates continuation rows by authoritative variant identity", () => {
    const main = source("src/pages/inventory/MainInventory.tsx");
    expect(main).toContain("stockItemsRef.current.map((item) => item.id)");
    expect(main).toContain("!seen.has(item.id)");
  });

  it("keeps summary request independent from cursor continuation", () => {
    const main = source("src/pages/inventory/MainInventory.tsx");
    expect(main).toContain("const fetchStockSummary = useCallback");
    expect(main).toContain("/warehouse/inventory/summary?location_id=");
    expect(main).toContain("stockSummaryRequestSeq.current");
  });

  it("retries the failed continuation cursor without clearing rows or rerunning summary", () => {
    const main = source("src/pages/inventory/MainInventory.tsx");
    const cp7Tab = source("src/pages/inventory/Tab1LiveStock.tsx");
    expect(main).toContain("const [stockPageRetryKey, setStockPageRetryKey] = useState(0)");
    expect(main).toContain("const retryStockPage = useCallback");
    expect(main).toContain("setStockPageRetryKey((value) => value + 1)");
    expect(main).toContain('if (activeTab === "live" && selectedLocationId !== null)');
    expect(main).toContain("stockPageRetryKey");
    expect(main).toContain("[activeTab, selectedLocationId, fetchStockSummary, stockRefreshKey]");
    expect(main).toContain("onRetryPage={retryStockPage}");
    expect(cp7Tab).toContain("onClick={onRetryPage}");
  });

  it("keeps CP3 mutations out of the CP7 feature modules", () => {
    const files = [
      "BatchDetailPanel.tsx",
      "LiveStockFilters.tsx",
      "LiveStockMobileCards.tsx",
      "LiveStockTable.tsx",
      "LiveStockWarehouseContext.tsx",
      "useLiveStockBatchDetail.ts",
    ].map((name) => source("src/pages/inventory/liveStock", name));
    for (const text of files) {
      expect(text).not.toContain("/warehouse/quality/stage");
      expect(text).not.toContain("/warehouse/quality/disposal/confirm");
      expect(text).not.toContain("/warehouse/quality/vendor-return/confirm");
    }
  });
});

describe("UI-05 mobile cost parity", () => {
  const cost = (metric: "last-purchase" | "average") => {
    const result = document.querySelector<HTMLElement>(`[data-live-stock-mobile-cost="${metric}"]`);
    expect(result).not.toBeNull();
    return result!;
  };

  it("renders distinct purchase/display units with desktop currency and exact-cost parity", () => {
    const item: WarehouseProduct = {
      ...product, last_purchase_cost: "1.500001", last_purchase_uom_code: "CT",
      average_cost_display: "0.125001", display_uom_code: "PK",
      display_factor_to_base: "8", currency_code: "JOD",
    };
    render(<><LiveStockTable products={[item]} loading={false} onOpen={vi.fn()} />
      <LiveStockMobileCards products={[item]} onOpen={vi.fn()} /></>);
    const locale = resolveAppLocale("en");
    const purchase = cost("last-purchase");
    const average = cost("average");
    expect(purchase.querySelector("[dir=auto]")?.textContent).toBe(formatMoneyDisplay(item.last_purchase_cost!, "JOD", locale));
    expect(average.querySelector("[dir=auto]")?.textContent).toBe(formatMoneyDisplay(item.average_cost_display!, "JOD", locale));
    expect(purchase).toHaveTextContent("per CT");
    expect(average).toHaveTextContent("per PK");
    expect(purchase).not.toHaveTextContent("per PK");
    expect(average).not.toHaveTextContent("per CT");
    expect(purchase.querySelector("[title]")).toHaveAttribute("title",
      `${formatMoneyExact(item.last_purchase_cost!, "JOD", locale)} · per CT`);
    expect(average.querySelector("[title]")).toHaveAttribute("title",
      `${formatMoneyExact(item.average_cost_display!, "JOD", locale)} · per PK`);
    expect(purchase.querySelector(".sr-only")?.textContent).toBe(
      `${formatMoneyExact(item.last_purchase_cost!, "JOD", locale)} · per CT`);
    const desktopCells = document.querySelectorAll<HTMLTableCellElement>(".live-stock-row td");
    expect(desktopCells[8].textContent).toBe(formatMoneyDisplay(item.last_purchase_cost!, "JOD", locale));
    expect(desktopCells[9].textContent).toBe(formatMoneyDisplay(item.average_cost_display!, "JOD", locale));
    expect(document.querySelectorAll('[data-testid="live-stock-mobile-cards"] [data-cp13-quantity]')).toHaveLength(5);
  });

  it("renders null costs as unknown, never zero or a fabricated per-unit amount", () => {
    render(<LiveStockMobileCards products={[{
      ...product, last_purchase_cost: null, last_purchase_uom_code: null,
      last_purchase_date: null, average_cost_display: null,
    }]} onOpen={vi.fn()} />);
    for (const metric of ["last-purchase", "average"] as const) {
      expect(cost(metric)).toHaveTextContent("—");
      expect(cost(metric)).not.toHaveTextContent("0");
      expect(cost(metric).querySelector(".sr-only")).toBeNull();
    }
    expect(document.querySelectorAll('[data-testid="live-stock-mobile-cards"] [data-cp13-quantity]')).toHaveLength(5);
  });

  it("preserves real zero values, Arabic locale, and separate purchase/display UOM", () => {
    mocks.language = "ar";
    const item: WarehouseProduct = {
      ...product, currency_code: "JOD", last_purchase_cost: "0",
      last_purchase_uom_code: "CT", average_cost_display: "0", display_uom_code: "PK",
    };
    render(<LiveStockMobileCards products={[item]} onOpen={vi.fn()} />);
    const display = formatMoneyDisplay("0", "JOD", resolveAppLocale("ar"));
    expect(cost("last-purchase").querySelector("[dir=auto]")?.textContent).toBe(display);
    expect(cost("average").querySelector("[dir=auto]")?.textContent).toBe(display);
    expect(cost("last-purchase")).toHaveTextContent("لكل CT");
    expect(cost("average")).toHaveTextContent("لكل PK");
    expect(cost("last-purchase")).not.toHaveTextContent("—");
    expect(cost("average")).not.toHaveTextContent("—");
    expect(cost("last-purchase").querySelector("[dir=auto]")).toBeInTheDocument();
  });

  it("keeps window positions and measures the taller first mobile card", () => {
    const onExtent = vi.fn();
    const measurement = vi.spyOn(HTMLElement.prototype, "getBoundingClientRect")
      .mockReturnValue({ height: 168, width: 300, x: 0, y: 0, top: 0, right: 300,
        bottom: 168, left: 0, toJSON: () => ({}) });
    try {
      const { container } = render(<LiveStockMobileCards
        products={[product, { ...product, id: 42 }]} totalCount={5000} startIndex={50}
        topSpacerHeight={1400} bottomSpacerHeight={2200}
        onItemMeasure={onExtent} onOpen={vi.fn()} />);
      expect(container.querySelectorAll("[data-cp13-stock-card]")).toHaveLength(2);
      expect(container.querySelectorAll("[data-cp13-quantity]")).toHaveLength(10);
      const cards = screen.getAllByRole("listitem");
      expect(cards[0]).toHaveAttribute("aria-posinset", "51");
      expect(cards[1]).toHaveAttribute("aria-posinset", "52");
      expect(cards[0]).toHaveAttribute("aria-setsize", "5000");
      expect(container.querySelector("[data-live-stock-window-spacer=top]")).toHaveStyle({ height: "1400px" });
      expect(container.querySelector("[data-live-stock-window-spacer=bottom]")).toHaveStyle({ height: "2200px" });
      expect(onExtent).toHaveBeenCalledWith(41, 174);
      expect(onExtent).toHaveBeenCalledWith(42, 174);
    } finally { measurement.mockRestore(); }
  });
});

describe("UI-06 bounded reservation evidence disclosure", () => {
  const completeOwners: LiveStockReservationEvidence["owners"] = [
    { transfer_id: 701, reference_number: "ROUTE-701", quantity: "16" },
    { transfer_id: 702, reference_number: "ROUTE-702", quantity: "10" },
  ];
  const evidence = (changes: Partial<LiveStockReservationEvidence> = {}): LiveStockReservationEvidence => ({
    coverage: "COMPLETE", owners: completeOwners, unattributed_quantity: "0",
    owners_truncated: false, ...changes,
  });
  const renderSource = (reservation: LiveStockReservationEvidence) => {
    const stock = parseLiveStockWarehouseSource({
      location_id: 11, location_name: "Warehouse A1",
      product_variant_id: 41, batch_id: 71,
      statuses: [{
        stock_status: "AVAILABLE", on_hand_quantity: "40",
        reserved_quantity: reservation.coverage === "NONE" ? "0" : "26",
        movable_quantity: reservation.coverage === "NONE" ? "40" : "14",
        reservation_evidence: reservation,
      }],
    });
    const onLoadSource = vi.fn();
    const props = {
      product: { ...product, display_uom_code: "CT", display_factor_to_base: "8" },
      batches: [{
        ...batch, allowed_disposition_targets: [...batch.allowed_disposition_targets],
        on_hand_quantity: "40", reserved_quantity: "26",
        restricted_quantity: "0", expiry_unavailable_quantity: "0",
        latest_purchase_cost: null, latest_purchase_uom_code: null,
        purchase_event_count: 0,
      }],
      hasMore: false, loading: false, error: null, sourceByBatch: { 71: stock },
      sourceOpenId: 71, sourceLoadingId: null, sourceErrorId: null,
      onClose: vi.fn(), onRetry: vi.fn(), onLoadMore: vi.fn(), onLoadSource,
    };
    const view = render(<BatchDetailPanel {...props} />);
    return { ...view, props, onLoadSource };
  };

  it("shows only returned complete owner references with exact converted units", () => {
    renderSource(evidence());
    const list = screen.getByRole("list", { name: "Known reservations" });
    const rows = Array.from(list.querySelectorAll("li"));
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("ROUTE-701");
    expect(rows[0]).toHaveTextContent("2 CT");
    expect(rows[1]).toHaveTextContent("ROUTE-702");
    expect(rows[1]).toHaveTextContent("1 CT + 2 EA");
    expect(rows[1].querySelector("[title]")).toHaveAttribute("title", "10 EA");
    expect(screen.getByText("Reservation evidence complete")).toBeInTheDocument();
    expect(screen.queryByText(/Truncated list:/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Unattributed reserved quantity:/)).not.toBeInTheDocument();
    expect(list.querySelector("a, button")).toBeNull();
    expect(list.querySelector("[data-transfer-id]")).toBeNull();
  });

  it("separates partial known references from unattributed reserved quantity", () => {
    renderSource(evidence({ coverage: "PARTIAL", owners: completeOwners.slice(0, 1),
      unattributed_quantity: "10" }));
    expect(screen.getByText("Reservation evidence partial")).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Known reservations" }).querySelectorAll("li")).toHaveLength(1);
    expect(screen.getByText(/Unattributed reserved quantity:/)).toHaveTextContent("1 CT + 2 EA");
    expect(screen.queryByText("ROUTE-702")).not.toBeInTheDocument();
  });

  it("warns about truncated evidence and never renders beyond server-returned owners", () => {
    const owners = Array.from({ length: 20 }, (_, index) => ({
      transfer_id: 801 + index, reference_number: `LIMIT-${index + 1}`, quantity: "1",
    }));
    renderSource(evidence({ coverage: "PARTIAL", owners,
      unattributed_quantity: "6", owners_truncated: true }));
    const list = screen.getByRole("list", { name: "Known reservations" });
    expect(list.querySelectorAll("li")).toHaveLength(20);
    expect(screen.getByText(/Truncated list: additional known reservation owners/)).toBeInTheDocument();
    expect(screen.getByText("LIMIT-20")).toBeInTheDocument();
    expect(screen.queryByText("LIMIT-21")).not.toBeInTheDocument();
    expect(list.querySelector("a, button")).toBeNull();
    const overLimit = evidence({ owners: [...owners, {
      transfer_id: 1000, reference_number: "LIMIT-21", quantity: "1",
    }] });
    expect(() => parseLiveStockWarehouseSource({
      location_id: 11, location_name: "Warehouse A1", product_variant_id: 41, batch_id: 71,
      statuses: [{ stock_status: "AVAILABLE", on_hand_quantity: "40",
        reserved_quantity: "26", movable_quantity: "14", reservation_evidence: overLimit }],
    })).toThrow("LIVE_STOCK_SOURCE_RESPONSE_INVALID");
  });

  it("distinguishes unresolved evidence with no known owners from unattributed quantity", () => {
    renderSource(evidence({ coverage: "UNRESOLVED", owners: [],
      unattributed_quantity: "26" }));
    expect(screen.getByText("Reservation evidence unresolved")).toBeInTheDocument();
    expect(screen.getByText("No known reservation references in the returned evidence.")).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Known reservations" })).not.toBeInTheDocument();
    expect(screen.getByText(/Unattributed reserved quantity:/)).toHaveTextContent("3 CT + 2 EA");
  });

  it("keeps NONE/empty evidence empty without implying unreturned reservations", () => {
    renderSource(evidence({ coverage: "NONE", owners: [], unattributed_quantity: "0" }));
    expect(screen.getByText("No reservations")).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Known reservations" })).not.toBeInTheDocument();
    expect(screen.queryByText(/No known reservation references/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Unattributed reserved quantity:/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Truncated list:/)).not.toBeInTheDocument();
  });

  it("localizes Arabic evidence, keeps RTL and native keyboard source toggle", () => {
    mocks.language = "ar";
    const view = renderSource(evidence({ coverage: "PARTIAL",
      owners: completeOwners.slice(0, 1), unattributed_quantity: "10",
      owners_truncated: true }));
    expect(screen.getByRole("dialog").closest(".app-modal")).toHaveAttribute("dir", "rtl");
    expect(screen.getByRole("list", { name: "حجوزات معروفة" })).toBeInTheDocument();
    expect(screen.getByText(/مرجع الحجز:/)).toHaveTextContent("ROUTE-701");
    expect(screen.getByText(/القائمة مقتطعة:/)).toBeInTheDocument();
    expect(screen.getByText("دليل الحجز جزئي")).toBeInTheDocument();
    const toggle = screen.getByRole("button", { name: "مصدر الرصيد والحجوزات" });
    toggle.focus();
    expect(toggle).toHaveFocus();
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    fireEvent.click(toggle);
    expect(view.onLoadSource).toHaveBeenCalledWith(71);
    view.rerender(<BatchDetailPanel {...view.props} sourceOpenId={null} />);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText(/مرجع الحجز:/)).not.toBeInTheDocument();
    expect(toggle).toHaveFocus();
  });

  it("does not reveal cached references while source is loading or unavailable", () => {
    const view = renderSource(evidence());
    view.rerender(<BatchDetailPanel {...view.props} sourceByBatch={{}} sourceLoadingId={71} />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading source evidence");
    expect(screen.queryByText("ROUTE-701")).not.toBeInTheDocument();
    view.rerender(<BatchDetailPanel {...view.props} sourceByBatch={{}} sourceErrorId={71} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Source evidence could not be loaded");
    expect(screen.queryByText("ROUTE-701")).not.toBeInTheDocument();
  });
});

describe.each(["en", "ar"])("physical vehicle disclosure in %s", (language) => {
  it.each(["desktop", "mobile"])("renders all read scopes and preserves known zero in %s", (surface) => {
    mocks.language = language;
    const copy = resources[language === "ar" ? "ar" : "en"].translation.inventoryLive.vehicleScopes;
    const node = (item: WarehouseProduct) => surface === "desktop"
      ? <LiveStockTable products={[item]} loading={false} onOpen={vi.fn()} />
      : <LiveStockMobileCards products={[item]} onOpen={vi.fn()} />;
    const view = render(node({ ...product, vehicle_quantity: "8", vehicle_quantity_scope: "COMPANY_WIDE" }));
    const cell = () => view.container.querySelector('[data-cp13-quantity="vehicle"]')!;
    expect(cell()).toHaveTextContent("8 EA");
    expect(cell()).toHaveTextContent(copy.COMPANY_WIDE);
    view.rerender(node({ ...product, vehicle_quantity: "0", vehicle_quantity_scope: "AUTHORIZED_LOCATIONS" }));
    expect(cell()).toHaveTextContent("0 EA");
    expect(cell()).toHaveTextContent(copy.AUTHORIZED_LOCATIONS);
    view.rerender(node({ ...product, vehicle_quantity: null, vehicle_quantity_scope: "NO_ACCESS" }));
    expect(cell()).toHaveTextContent(copy.NO_ACCESS);
    expect(cell()).not.toHaveTextContent("0 EA");
    expect(cell()).not.toHaveTextContent("8 EA");
    expect(view.container.querySelector('[data-cp13-quantity="on-hand"]')).toHaveTextContent("2.500001 EA");
    expect(cell().querySelector('[data-vehicle-scope="NO_ACCESS"]')).toHaveAttribute("dir", language === "ar" ? "rtl" : "ltr");
  });
});
