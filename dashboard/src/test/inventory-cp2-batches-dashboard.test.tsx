import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  appendUniqueBatchItems,
  buildBatchIndexCursorParams,
  buildBatchIndexSummaryParams,
  DEFAULT_BATCH_INDEX_FILTERS,
  parseBatchIndexCursorPage,
  type WarehouseBatchIndexItem,
} from "@/pages/inventory/batches/batchIndexContracts";

const mocks = vi.hoisted(() => ({
  authFetch: vi.fn(),
  language: "en",
}));

vi.mock("@/hooks/useAuthFetch", () => ({
  useAuthFetch: () => mocks.authFetch,
}));

vi.mock("@/hooks/useInventoryAccess", () => ({
  useInventoryAccess: () => ({
    isCompanyOwner: true,
    can: () => true,
    data: {
      company_id: 1,
      principal_id: 7,
      backoffice_user_id: 17,
      is_company_owner: true,
      location_id: null,
      permissions: ["inventory.read", "batch.disposition"],
      any_permissions: [],
      location_permissions: [],
    },
  }),
}));

vi.mock("sonner", () => ({
  toast: { error: vi.fn() },
}));

vi.mock("react-i18next", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-i18next")>();
  const translate = (key: string, options?: Record<string, unknown>) => {
    let value = typeof options?.defaultValue === "string" ? options.defaultValue : key;
    for (const [name, candidate] of Object.entries(options ?? {})) {
      value = value.replaceAll(`{{${name}}}`, String(candidate));
    }
    return value;
  };
  return {
    ...actual,
    useTranslation: () => ({
      t: translate,
      i18n: {
        language: mocks.language,
        resolvedLanguage: mocks.language,
        dir: () => (mocks.language === "ar" ? "rtl" : "ltr"),
      },
    }),
  };
});

vi.mock("@/pages/inventory/batches/BatchDispositionManager", () => ({
  BatchDispositionManager: ({ batch }: { batch: { batch_id: number; batch_number: string | null } | null }) =>
    batch ? <div data-testid="batch-action-workspace">{batch.batch_number ?? "NO_LOT"}</div> : null,
}));

import { TabBatches } from "@/pages/inventory/TabBatches";

const item = (
  id: number,
  overrides: Partial<WarehouseBatchIndexItem> = {},
): WarehouseBatchIndexItem => ({
  batch_id: id,
  batch_number: `LOT-${id}`,
  production_date: "2026-01-01",
  expiry_date: "2026-12-31",
  disposition: "RELEASED",
  disposition_reason: null,
  disposition_revision: 1,
  allowed_disposition_targets: ["QUARANTINED", "BLOCKED", "RECALLED"],
  days_to_expiry: 76,
  product_id: 10,
  product_variant_id: 100 + id,
  product_name: `Product ${id}`,
  sku: `SKU-${id}`,
  family_name: "Family A",
  lot_control_mode: "REQUIRED",
  expiry_control_mode: "REQUIRED",
  minimum_remaining_shelf_life_days: 14,
  sellability_state: "SELLABLE",
  sellability_reason_codes: [],
  base_uom_id: 1,
  base_uom_code: "EACH",
  base_uom_name: "Each",
  display_uom_id: 1,
  display_uom_code: "EACH",
  display_uom_name: "Each",
  display_factor_to_base: "1",
  quantity_scale: 0,
  quantity_step: "1",
  on_hand_quantity: "10",
  reserved_quantity: "1",
  available_for_sale_quantity: "9",
  unavailable_quantity: "0",
  available_status_quantity: "10",
  quarantined_quantity: "0",
  blocked_quantity: "0",
  recalled_quantity: "0",
  damaged_quantity: "0",
  disposal_pending_quantity: "0",
  ...overrides,
});

const page = (
  items: WarehouseBatchIndexItem[],
  nextCursor: string | null = null,
) => ({
  location_id: 119,
  as_of_date: "2026-10-16",
  items,
  next_cursor: nextCursor,
  has_more: nextCursor !== null,
});

const summary = (overrides: Record<string, number> = {}) => ({
  location_id: 119,
  as_of_date: "2026-10-16",
  total_relevant_batches: 8,
  expired_count: 1,
  expiring_soon_count: 2,
  non_sellable_count: 3,
  quarantined_count: 1,
  blocked_count: 1,
  recalled_count: 1,
  damaged_or_disposal_attention_count: 1,
  ...overrides,
});

const renderPage = () =>
  render(
    <TabBatches
      locationId={119}
      onFocusConsumed={() => undefined}
      onOpenTransfers={() => undefined}
      onOpenReservationOwner={() => undefined}
    />,
  );

beforeEach(() => {
  mocks.authFetch.mockReset();
  mocks.language = "en";
  localStorage.clear();
  localStorage.setItem("company_id", "1");
  localStorage.setItem("principal_id", "7");
});

describe("CP2 Batches Dashboard batch-first contract", () => {
  it("loads warehouse-wide batches without product selection and keeps summary independent", async () => {
    mocks.authFetch.mockImplementation(async (path: string) => {
      if (path.startsWith("/warehouse/inventory/batches/cursor?")) return page([item(1)]);
      if (path.startsWith("/warehouse/inventory/batches/summary?")) return summary();
      throw new Error(`Unexpected request: ${path}`);
    });

    renderPage();

    expect(await screen.findByText("Product 1")).toBeInTheDocument();
    expect(screen.getByText("8")).toBeInTheDocument();
    const paths = mocks.authFetch.mock.calls.map(([path]) => String(path));
    expect(paths.some((path) => path.startsWith("/warehouse/inventory/batches/cursor?"))).toBe(true);
    expect(paths.some((path) => path.startsWith("/warehouse/inventory/batches/summary?"))).toBe(true);
    expect(paths.some((path) => path.includes("/warehouse/inventory/batch-products"))).toBe(false);
    expect(paths.some((path) => /\/warehouse\/inventory\/\d+\/batches/.test(path))).toBe(false);
  });

  it("maps expiry, sellability, disposition, attention, family, product, sort, and literal search exactly to backend params", () => {
    const filters = {
      ...DEFAULT_BATCH_INDEX_FILTERS,
      search: "% _ \\ literal",
      expiryState: "EXPIRING_SOON" as const,
      sellability: "NOT_SELLABLE" as const,
      disposition: "QUARANTINED" as const,
      attention: "DAMAGED" as const,
      familyId: 41,
      productVariantId: 211,
      sort: "UNAVAILABLE_DESC" as const,
    };
    const params = buildBatchIndexCursorParams(119, filters, 21, "cursor-x");
    expect(Object.fromEntries(params.entries())).toMatchObject({
      location_id: "119",
      search: "% _ \\ literal",
      expiry_state: "EXPIRING_SOON",
      expiry_warning_days: "21",
      sellability: "NOT_SELLABLE",
      disposition: "QUARANTINED",
      has_damaged: "true",
      family_id: "41",
      product_variant_id: "211",
      sort: "UNAVAILABLE_DESC",
      cursor: "cursor-x",
    });
    expect(params.has("minimum_remaining_shelf_life_days")).toBe(false);

    const summaryParams = buildBatchIndexSummaryParams(119, filters, 21);
    expect(summaryParams.get("expiry_warning_days")).toBe("21");
    expect(summaryParams.has("sellability")).toBe(false);
    expect(summaryParams.has("disposition")).toBe(false);
    expect(summaryParams.has("has_damaged")).toBe(false);
  });

  it("renders public nullable lot in English and Arabic and rejects internal no-lot leakage", async () => {
    mocks.authFetch.mockImplementation(async (path: string) => {
      if (path.startsWith("/warehouse/inventory/batches/cursor?")) return page([item(1, { batch_number: null })]);
      if (path.startsWith("/warehouse/inventory/batches/summary?")) return summary();
      throw new Error(`Unexpected request: ${path}`);
    });

    const english = renderPage();
    expect(await screen.findAllByText("No lot supplied")).not.toHaveLength(0);
    english.unmount();

    mocks.language = "ar";
    renderPage();
    expect(await screen.findAllByText("بدون رقم دفعة")).not.toHaveLength(0);
    expect(document.querySelector('[dir="rtl"]')).not.toBeNull();

    expect(() =>
      parseBatchIndexCursorPage(
        page([item(5, { batch_number: "__WANASAH_NOLOT__:SECRET" })]),
      ),
    ).toThrow("BATCH_INDEX_RESPONSE_INVALID");
  });

  it("appends continuation without duplicate batch_id and does not refresh summary", async () => {
    let cursorReads = 0;
    mocks.authFetch.mockImplementation(async (path: string) => {
      if (path.startsWith("/warehouse/inventory/batches/summary?")) return summary();
      if (path.startsWith("/warehouse/inventory/batches/cursor?")) {
        cursorReads += 1;
        return cursorReads === 1
          ? page([item(1)], "next-1")
          : page([item(1), item(2)]);
      }
      throw new Error(`Unexpected request: ${path}`);
    });

    renderPage();
    await screen.findByText("Product 1");
    fireEvent.click(screen.getByRole("button", { name: "Load more batches" }));
    expect(await screen.findByText("Product 2")).toBeInTheDocument();
    expect(screen.getAllByText("Product 1")).toHaveLength(1);
    const summaryReads = mocks.authFetch.mock.calls.filter(([path]) => String(path).startsWith("/warehouse/inventory/batches/summary?")).length;
    expect(summaryReads).toBe(1);
    expect(appendUniqueBatchItems([item(1)], [item(1), item(2)]).map((row) => row.batch_id)).toEqual([1, 2]);
  });

  it("keeps current rows and provides inline retry after continuation failure", async () => {
    let cursorReads = 0;
    mocks.authFetch.mockImplementation(async (path: string) => {
      if (path.startsWith("/warehouse/inventory/batches/summary?")) return summary();
      if (path.startsWith("/warehouse/inventory/batches/cursor?")) {
        cursorReads += 1;
        if (cursorReads === 1) return page([item(1)], "next-1");
        if (cursorReads === 2) throw new Error("network");
        return page([item(2)]);
      }
      throw new Error(`Unexpected request: ${path}`);
    });

    renderPage();
    await screen.findByText("Product 1");
    fireEvent.click(screen.getByRole("button", { name: "Load more batches" }));
    expect(await screen.findByText("Could not load the next page. Current results were kept.")).toBeInTheDocument();
    expect(screen.getByText("Product 1")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry loading more" }));
    expect(await screen.findByText("Product 2")).toBeInTheDocument();
  });

  it("protects newer sort queries from stale responses", async () => {
    let resolveOld: ((value: unknown) => void) | null = null;
    const oldPage = new Promise((resolve) => {
      resolveOld = resolve;
    });
    mocks.authFetch.mockImplementation(async (path: string) => {
      if (path.startsWith("/warehouse/inventory/batches/summary?")) return summary();
      if (path.includes("sort=EXPIRY_ASC")) return oldPage;
      if (path.includes("sort=PRODUCT_DESC")) return page([item(9, { product_name: "New Query" })]);
      throw new Error(`Unexpected request: ${path}`);
    });

    renderPage();
    fireEvent.change(screen.getByRole("combobox", { name: "Sort" }), {
      target: { value: "PRODUCT_DESC" },
    });
    expect(await screen.findByText("New Query")).toBeInTheDocument();
    resolveOld?.(page([item(8, { product_name: "Stale Query" })]));
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(screen.queryByText("Stale Query")).not.toBeInTheDocument();
  });

  it("refresh resets the cursor and reloads first-page data and summary", async () => {
    let firstPageReads = 0;
    mocks.authFetch.mockImplementation(async (path: string) => {
      if (path.startsWith("/warehouse/inventory/batches/summary?")) return summary();
      if (path.startsWith("/warehouse/inventory/batches/cursor?")) {
        const params = new URLSearchParams(path.split("?")[1]);
        if (params.has("cursor")) return page([item(2)]);
        firstPageReads += 1;
        return firstPageReads === 1
          ? page([item(1)], "next-1")
          : page([item(3, { product_name: "Refreshed Product" })]);
      }
      throw new Error(`Unexpected request: ${path}`);
    });

    renderPage();
    await screen.findByText("Product 1");
    fireEvent.click(screen.getByRole("button", { name: "Load more batches" }));
    await screen.findByText("Product 2");
    fireEvent.click(screen.getByRole("button", { name: "Refresh batches" }));
    expect(await screen.findByText("Refreshed Product")).toBeInTheDocument();
    expect(screen.queryByText("Product 1")).not.toBeInTheDocument();
    expect(screen.queryByText("Product 2")).not.toBeInTheDocument();
  });

  it("renders backend sellability reasons, summary counters, responsive treatment, and the existing action workspace", async () => {
    const blocked = item(1, {
      sellability_state: "NOT_SELLABLE",
      sellability_reason_codes: ["MINIMUM_REMAINING_SHELF_LIFE_NOT_MET"],
      unavailable_quantity: "9",
      available_for_sale_quantity: "0",
    });
    mocks.authFetch.mockImplementation(async (path: string) => {
      if (path.startsWith("/warehouse/inventory/batches/cursor?")) return page([blocked]);
      if (path.startsWith("/warehouse/inventory/batches/summary?")) return summary();
      throw new Error(`Unexpected request: ${path}`);
    });

    const { container } = renderPage();
    expect(await screen.findByText("Remaining shelf life is below the selling policy")).toBeInTheDocument();
    expect(screen.getByText("Relevant batches")).toBeInTheDocument();
    expect(screen.getByText("Damaged / disposal")).toBeInTheDocument();
    expect(container.querySelector(".md\\:hidden")).not.toBeNull();
    expect(container.querySelector(".hidden.md\\:block")).not.toBeNull();
    fireEvent.click(screen.getAllByRole("button", { name: "Manage batch status" })[0]);
    expect(screen.getByTestId("batch-action-workspace")).toHaveTextContent("LOT-1");
    expect(screen.getByRole("searchbox")).toBeInTheDocument();
    expect(screen.getAllByRole("combobox").length).toBeGreaterThanOrEqual(7);
  });
});