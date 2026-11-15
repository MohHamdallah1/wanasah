import { lazy, Suspense } from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter, Outlet, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { OperationsSidebar } from "./OperationsSidebar";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { dir: () => "rtl", language: "ar", resolvedLanguage: "ar" },
  }),
}));
vi.mock("@/hooks/useInventoryAccess", () => ({
  useInventoryAccess: () => ({
    isCompanyOwner: true,
    can: () => true,
    canAny: () => true,
  }),
}));
vi.mock("@/features/tenantIdentity/useTenantIdentity", () => ({
  useTenantIdentity: () => ({
    data: { timezone: "Asia/Amman", display_location: "Test warehouse" },
  }),
}));

const otherPages = [
  ["/", "nav.home"],
  ["/dispatch", "nav.dispatch"],
  ["/inventory", "nav.inventory"],
  ["/representatives-vehicles", "representativesVehicles.title"],
] as const;

describe("Operations sidebar when navigating from any page to Products", () => {
  it.each(otherPages)(
    "keeps the previous %s label present while Products module is pending",
    async (initial, priorLabel) => {
      const SlowProducts = lazy(() => new Promise<{ default: () => JSX.Element }>(() => {}));
      function Shell() {
        return (
          <>
            <OperationsSidebar
              open={false}
              collapsed={false}
              onClose={() => {}}
              onToggleCollapsed={() => {}}
            />
            <Suspense fallback={<p data-testid="page-loading">Loading Products</p>}>
              <Outlet />
            </Suspense>
          </>
        );
      }
      render(
        <MemoryRouter initialEntries={[initial]}>
          <Routes>
            <Route element={<Shell />}>
              <Route path="/" element={<p>Home</p>} />
              <Route path="/dispatch" element={<p>Dispatch</p>} />
              <Route path="/inventory" element={<p>Inventory</p>} />
              <Route path="/representatives-vehicles" element={<p>Operations</p>} />
              <Route path="/products" element={<SlowProducts />} />
            </Route>
          </Routes>
        </MemoryRouter>,
      );
      const previousButton = screen.getByRole("button", { name: priorLabel });
      expect(previousButton).toHaveAttribute("data-active", "true");
      expect(previousButton).toHaveClass("transition-none");
      expect(previousButton).toBeVisible();

      fireEvent.click(screen.getByRole("button", { name: "nav.products" }));
      await waitFor(() => expect(screen.getByTestId("page-loading")).toBeInTheDocument());

      expect(screen.getByRole("button", { name: priorLabel })).toBe(previousButton);
      expect(previousButton).toBeVisible();
      expect(previousButton).toHaveAttribute("data-active", "false");
      expect(screen.getByRole("button", { name: "nav.products" })).toHaveAttribute("data-active", "true");
      expect(screen.getByRole("button", { name: "nav.products" })).toHaveClass("transition-none");
    },
  );

  it("does not interpolate previous label colors/background during the route switch", () => {
    const css = readFileSync(
      resolve(process.cwd(), "src/components/operations/dashboard.css"), "utf8",
    );
    const source = readFileSync(
      resolve(process.cwd(), "src/components/operations/OperationsSidebar.tsx"), "utf8",
    );
    expect(source).toContain("operations-nav-item flex items-center gap-3 rounded-xl px-4 py-3 text-sm font-medium transition-none");
    expect(source).toContain("key={item.path}");
    expect(source).toContain("{t(item.labelKey)}");
    expect(css).toContain('.operations-nav-item[data-active="true"]');
    expect(css).toContain("background: var(--dashboard-gold)");
  });
});
