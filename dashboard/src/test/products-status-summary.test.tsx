import { act, cleanup, fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createInstance } from "i18next";
import { I18nextProvider } from "react-i18next";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";

import { resources } from "@/i18n/resources";
import { DEFAULT_PRODUCT_DISPLAY_PREFERENCES } from "@/lib/productDisplayPreferences";
import { ProductStatusBadges } from "@/pages/products/list/ProductStatusBadges";
import { ProductsCatalogSummary } from "@/pages/products/list/ProductsCatalogSummary";
import { parseCatalogSummary } from "@/pages/products/list/catalogSummaryContract";
import { productTableStatus } from "@/pages/products/list/productTableStatus";
import { useProductCatalogSummary } from "@/pages/products/list/useProductCatalogSummary";
import { useProductsListWorkflow } from "@/pages/products/list/useProductsListWorkflow";
import { productCommercialStatus } from "@/pages/products/status/productCommercialStatus";

const summary = {
  schema_version: 2 as const,
  company_id: 38,
  total: 1234,
  families: 82,
  available: 1000,
  stopped: 134,
  archived: 100,
};
const clients: QueryClient[] = [];
afterEach(() => { cleanup(); clients.splice(0).forEach((client) => client.clear()); });

function wrapper(language = "en") {
  const i18n = createInstance();
  void i18n.init({ lng: language, resources, initAsync: false });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  clients.push(client);
  return { client, Wrapper: ({ children }: { children: ReactNode }) => (
    <I18nextProvider i18n={i18n}><QueryClientProvider client={client}>{children}</QueryClientProvider></I18nextProvider>
  ) };
}

describe("Product status: one commercial state over the internal state machine", () => {
  it.each([
    ["ACTIVE", "NONE", "available", null],
    ["ACTIVE", "SALES_HOLD", "stopped", "temporary"],
    ["ACTIVE", "RECALL", "stopped", "requiresAction"],
    ["RETIRING", "NONE", "stopped", null],
    ["RETIRING", "SALES_HOLD", "stopped", "temporary"],
    ["RETIRING", "RECALL", "stopped", "requiresAction"],
    ["ARCHIVED", "NONE", "archived", null],
    ["DRAFT", "NONE", "stopped", "draft"],
  ] as const)("%s / %s -> %s (%s)", (lifecycle_status, operational_hold, state, reason) => {
    const status = productCommercialStatus({ lifecycle_status, operational_hold });
    expect(status.state).toBe(state);
    expect(status.reason).toBe(reason);
  });

  it("presents RETIRING as an already-complete out-of-use business state", () => {
    const status = productCommercialStatus({ lifecycle_status: "RETIRING", operational_hold: "NONE" });
    expect(status.state).toBe("stopped");
    expect(status.stateKey).toBe("products.commercialStatus.outOfUse");
    expect(status.hintKey).toBe("products.commercialStatus.hints.outOfUse");
    expect(status.reason).toBeNull();
  });

  it("keeps retiring as a secondary backend concern when a sales hold is active", () => {
    const status = productCommercialStatus({ lifecycle_status: "RETIRING", operational_hold: "RECALL" });
    expect(status.state).toBe("stopped");
    expect(status.reason).toBe("requiresAction");
    expect(status.secondaryReasonKey).toBe("products.commercialStatus.secondary.pendingArchive");
  });

  it.each([
    ["ar", "rtl", "موقوف", "يتطلب معالجة"],
    ["en", "ltr", "Stopped", "Requires resolution"],
  ])("%s renders one status with an optional reason", (language, dir, stopped, reason) => {
    const { Wrapper } = wrapper(language);
    const { container } = render(
      <ProductStatusBadges item={{ lifecycle_status: "ACTIVE", operational_hold: "RECALL" }} />,
      { wrapper: Wrapper },
    );
    expect(screen.getByText(stopped)).toBeInTheDocument();
    expect(screen.getByText(reason)).toBeInTheDocument();
    expect(container.firstElementChild).toHaveAttribute("dir", dir);
    expect(screen.queryByText(language === "ar" ? "المنتج" : "Product")).not.toBeInTheDocument();
    expect(screen.queryByText(language === "ar" ? "البيع" : "Sales")).not.toBeInTheDocument();
  });

  it("keeps the product available while warning about restricted batches and their real reason", () => {
    const { Wrapper } = wrapper("ar");
    render(
      <ProductStatusBadges
        item={{
          lifecycle_status: "ACTIVE",
          operational_hold: "NONE",
          batch_restrictions: {
            schema_version: 1,
            scope: "COMPANY",
            affected_batch_count: 2,
            affected_on_hand_quantity: "15.000000",
            quantity_unit: "BASE_STOCK_UNIT",
            counts_by_disposition: {
              QUARANTINED: 1,
              BLOCKED: 1,
              RECALLED: 0,
            },
            representative_reason: {
              selection: "LOWEST_BATCH_ID_WITH_CURRENT_REASON",
              batch_id: 41,
              disposition: "QUARANTINED",
              disposition_revision: 2,
              disposition_reason: "اشتباه في جودة المنتج",
            },
          },
        }}
      />,
      { wrapper: Wrapper },
    );

    expect(screen.getByText("متاح للبيع")).toBeInTheDocument();
    expect(
      screen.getByText("المنتج نشط، لكن 2 دفعة غير متاحة للبيع."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("السبب: اشتباه في جودة المنتج"),
    ).toBeInTheDocument();
  });

  it("table presentation delegates to the same commercial mapping", () => {
    expect(productTableStatus({ lifecycle_status: "ACTIVE", operational_hold: "NONE" })).toEqual({
      status: { valueKey: "products.commercialStatus.available", tone: "good" },
      reason: null,
    });
  });
});

describe("Company catalog summary contract and compact presentation", () => {
  it("accepts one company-wide partition across the three visible commercial states", () => {
    expect(parseCatalogSummary(summary, 38)).toEqual(summary);
    expect(parseCatalogSummary({ ...summary, total: 0, families: 0, available: 0, stopped: 0, archived: 0 }, 38).total).toBe(0);
  });

  it.each([
    { company_id: 39 },
    { schema_version: 1 },
    { total: -1 },
    { total: "1234" },
    { available: null },
    { families: -1 },
    { stopped: 0.5 },
    { total: Number.MAX_SAFE_INTEGER + 1 },
    { stopped: 135 },
  ])("rejects invalid/foreign-company summary data: %j", (invalid) => {
    expect(() => parseCatalogSummary({ ...summary, ...invalid }, 38)).toThrow("SIMPLE_PRODUCT_SUMMARY_CONTRACT_INVALID");
  });

  it.each([
    ["ar", "rtl", "ملخص الكتالوج", "موقوف"],
    ["en", "ltr", "Catalog summary", "Stopped"],
  ])("%s keeps Western digits and exposes only exactly supported filter buttons", (language, dir, title, stopped) => {
    const { Wrapper } = wrapper(language);
    const onChange = vi.fn();
    const { container, rerender } = render(
      <ProductsCatalogSummary data={summary} isFetching={false} error={null}
        lifecycleFilter="" onLifecycleFilterChange={onChange} onRetry={vi.fn()} />,
      { wrapper: Wrapper },
    );
    expect(screen.getByRole("group", { name: title })).toHaveAttribute("dir", dir);
    expect(screen.getAllByRole("button")).toHaveLength(1);
    expect(container.textContent).toContain("1,234");
    expect(container.textContent).toContain(stopped);
    expect(container.textContent).not.toMatch(/[٠-٩۰-۹]/);
    const archivedButton = screen.getByRole("button", { name: new RegExp(language === "ar" ? "مؤرشف" : "Archived") });
    archivedButton.focus();
    expect(archivedButton).toHaveFocus();
    expect(archivedButton).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(archivedButton);
    expect(onChange).toHaveBeenLastCalledWith("ARCHIVED");
    rerender(<ProductsCatalogSummary data={summary} isFetching={false} error={null} lifecycleFilter="ARCHIVED"
      onLifecycleFilterChange={onChange} onRetry={vi.fn()} />);
    expect(screen.getByRole("button", { name: new RegExp(language === "ar" ? "مؤرشف" : "Archived") })).toHaveAttribute("aria-pressed", "true");
  });

  it("does not present failed counters as zero or keep stale totals after an error", () => {
    const { Wrapper } = wrapper();
    const retry = vi.fn();
    render(<ProductsCatalogSummary data={summary} isFetching={false} error={new Error("offline")}
      lifecycleFilter="" onLifecycleFilterChange={vi.fn()} onRetry={retry} />, { wrapper: Wrapper });
    expect(screen.queryByText("1,234")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(retry).toHaveBeenCalledOnce();
  });
});

describe("Summary shares catalog identity/invalidation boundaries", () => {
  it("keeps company totals independent of pages and preserves existing filters", async () => {
    const authFetch = vi.fn(async (path: string) => path === "/simple-products/summary" ? summary : {
      currency_code: "JOD", pricing_visible: false, items: [], next_cursor: "next", has_more: true,
    });
    const { Wrapper, client } = wrapper();
    const { result } = renderHook(() => useProductsListWorkflow({ companyId: 38, driverId: 3, authFetch,
      canViewPricing: false, displayPreferences: DEFAULT_PRODUCT_DISPLAY_PREFERENCES, online: true }), { wrapper: Wrapper });
    await waitFor(() => expect(result.current.section.summary.data?.total).toBe(1234));
    act(() => result.current.section.filters.onBarcodeFilterChange("false"));
    await waitFor(() => expect(result.current.section.results.hasNext).toBe(true));
    act(() => result.current.section.results.onLoadMore());
    await waitFor(() => expect(authFetch.mock.calls.some(([path]) => path.includes("cursor=next"))).toBe(true));
    const view = render(<ProductsCatalogSummary {...result.current.section.summary} />, { wrapper: Wrapper });
    fireEvent.click(screen.getByRole("button", { name: /Archived/ }));
    await waitFor(() => expect(result.current.section.filters.lifecycleFilter).toBe("ARCHIVED"));
    await waitFor(() => {
      const calls = authFetch.mock.calls.filter(([path]) => path.startsWith("/simple-products?"));
      const params = new URLSearchParams(calls[calls.length - 1][0].split("?")[1]);
      expect(params.get("lifecycle")).toBe("ARCHIVED");
      expect(params.get("has_barcode")).toBe("false");
      expect(params.has("cursor")).toBe(false);
    });
    view.rerender(<ProductsCatalogSummary {...result.current.section.summary} />);
    expect(screen.getByRole("button", { name: /Archived/ })).toHaveAttribute("aria-pressed", "true");
    expect(result.current.section.summary.data.total).toBe(1234);
    expect(authFetch.mock.calls.filter(([path]) => path === "/simple-products/summary")).toHaveLength(1);
    await act(async () => { await client.invalidateQueries({ queryKey: ["simple-products"] }); });
    expect(authFetch.mock.calls.filter(([path]) => path === "/simple-products/summary")).toHaveLength(2);
  });

  it("does not fetch without an identity or show another company's summary while switching identity", async () => {
    const authFetch = vi.fn(async (_path: string, _opts?: RequestInit) => summary);
    const { Wrapper } = wrapper();
    const { result, rerender } = renderHook(({ companyId, driverId }) => useProductCatalogSummary({ companyId, driverId, authFetch }),
      { wrapper: Wrapper, initialProps: { companyId: null as number | null, driverId: null as number | null } });
    expect(authFetch).not.toHaveBeenCalled();
    rerender({ companyId: 38, driverId: 3 });
    await waitFor(() => expect(result.current.data?.total).toBe(1234));
    expect(authFetch.mock.calls[0]).toHaveLength(2);
    authFetch.mockImplementation(() => new Promise(() => {}));
    rerender({ companyId: 39, driverId: 4 });
    expect(result.current.data).toBeUndefined();
  });
});
