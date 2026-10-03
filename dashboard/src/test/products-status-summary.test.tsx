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

const summary = {
  schema_version: 1 as const, company_id: 38, total: 1234, families: 82,
  available: 1000, retiring: 120, archived: 100, sales_restricted: 14,
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

describe("Product status: explicit product and sales dimensions", () => {
  for (const lifecycle_status of ["ACTIVE", "RETIRING", "ARCHIVED"] as const) {
    for (const operational_hold of ["NONE", "SALES_HOLD", "RECALL"] as const) {
      it(`${lifecycle_status} / ${operational_hold} keeps product and sales states separate`, () => {
        const status = productTableStatus({ lifecycle_status, operational_hold });
        expect(status.product.labelKey).toBe("products.tableStatus.productLabel");
        expect(status.product.valueKey).toBe(`products.tableStatus.lifecycle.${lifecycle_status}`);
        expect(status.sales.labelKey).toBe("products.tableStatus.salesLabel");
        expect(status.sales.valueKey).toBe(`products.tableStatus.sales.${operational_hold}`);
        if (operational_hold === "RECALL") expect(status.sales.tone).toBe("blocked");
      });
    }
  }
  it.each([["ar", "rtl", "المنتج", "البيع", "نشط", "موقوف لحين المعالجة"], ["en", "ltr", "Product", "Sales", "Active", "Paused pending resolution"]])("%s renders product and sales as two explicit lines", (language, dir, productLabel, salesLabel, active, stopped) => {
    const { Wrapper } = wrapper(language);
    const { container } = render(<ProductStatusBadges item={{ lifecycle_status: "ACTIVE", operational_hold: "RECALL" }} />, { wrapper: Wrapper });
    for (const label of [productLabel, salesLabel, active, stopped]) expect(screen.getByText(label)).toBeInTheDocument();
    expect(container.firstElementChild).toHaveAttribute("dir", dir);
  });
});

describe("Company catalog summary contract and compact presentation", () => {
  it("accepts company-wide counts, zero catalogs and overlapping hold counts", () => {
    expect(parseCatalogSummary(summary, 38)).toEqual(summary);
    expect(parseCatalogSummary({ ...summary, total: 0, families: 0, available: 0, retiring: 0, archived: 0, sales_restricted: 0 }, 38).total).toBe(0);
    expect(parseCatalogSummary({ ...summary, sales_restricted: 1234 }, 38).sales_restricted).toBe(1234);
  });
  it.each([
    { company_id: 39 }, { schema_version: 2 }, { total: -1 }, { total: "1234" },
    { available: null }, { families: -1 }, { retiring: 0.5 }, { total: Number.MAX_SAFE_INTEGER + 1 },
    { available: 1234, retiring: 1 }, { sales_restricted: 1235 },
  ])("rejects invalid/foreign-company summary data: %j", (invalid) => {
    expect(() => parseCatalogSummary({ ...summary, ...invalid }, 38)).toThrow("SIMPLE_PRODUCT_SUMMARY_CONTRACT_INVALID");
  });
  it.each([ ["ar", "rtl", "ملخص الكتالوج", "منتجات موقوفة"], ["en", "ltr", "Catalog summary", "Stopped products"] ])(
    "%s keeps Western digits and exposes only supported native filter buttons", (language, dir, title, retiring) => {
      const { Wrapper } = wrapper(language);
      const onChange = vi.fn();
      const { container, rerender } = render(<ProductsCatalogSummary data={summary} isFetching={false} error={null}
        lifecycleFilter="" onLifecycleFilterChange={onChange} onRetry={vi.fn()} />, { wrapper: Wrapper });
      expect(screen.getByRole("group", { name: title })).toHaveAttribute("dir", dir);
      expect(screen.getAllByRole("button")).toHaveLength(2);
      expect(container.textContent).toContain("1,234");
      expect(container.textContent).not.toMatch(/[٠-٩۰-۹]/);
      const button = screen.getByRole("button", { name: new RegExp(retiring) });
      button.focus();
      expect(button).toHaveFocus();
      expect(button.tabIndex).toBe(0);
      expect(button).toHaveAttribute("aria-pressed", "false");
      fireEvent.click(button);
      expect(onChange).toHaveBeenLastCalledWith("RETIRING");
      rerender(<ProductsCatalogSummary data={summary} isFetching={false} error={null} lifecycleFilter="RETIRING"
        onLifecycleFilterChange={onChange} onRetry={vi.fn()} />);
      expect(button).toHaveAttribute("aria-pressed", "true");
      fireEvent.click(button);
      expect(onChange).toHaveBeenLastCalledWith("");
    },
  );
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

describe("Summary shares catalog filters and identity/invalidation boundaries", () => {
  it("uses the existing lifecycle action, preserves other filters, resets cursors and keeps company totals independent of pages", async () => {
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
    fireEvent.click(screen.getByRole("button", { name: /Stopped products/ }));
    await waitFor(() => expect(result.current.section.filters.lifecycleFilter).toBe("RETIRING"));
    await waitFor(() => {
      const calls = authFetch.mock.calls.filter(([path]) => path.startsWith("/simple-products?"));
      const params = new URLSearchParams(calls[calls.length - 1][0].split("?")[1]);
      expect(params.get("lifecycle")).toBe("RETIRING");
      expect(params.get("has_barcode")).toBe("false");
      expect(params.has("cursor")).toBe(false);
    });
    view.rerender(<ProductsCatalogSummary {...result.current.section.summary} />);
    expect(screen.getByRole("button", { name: /Stopped products/ })).toHaveAttribute("aria-pressed", "true");
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
