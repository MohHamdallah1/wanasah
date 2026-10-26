import type { ReactNode } from "react";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, useLocation } from "react-router-dom";

let direction: "rtl" | "ltr" = "rtl";
let owner = false;
let permissions = new Set<string>();
let companyId: number | undefined = 7;
let principalId: number | undefined = 11;
let loading = false;

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { dir: () => direction },
  }),
}));
vi.mock("@/components/dashboard/WorkspaceTopBar", () => ({
  WorkspaceTopBar: ({ children }: { children: ReactNode }) => <div data-testid="workspace-top-bar">{children}</div>,
}));
vi.mock("@/hooks/useInventoryAccess", () => ({
  useInventoryAccess: () => ({
    isLoading: loading,
    data: { company_id: companyId, principal_id: principalId },
    isCompanyOwner: owner,
    can: (capability: string) => permissions.has(capability),
  }),
}));
vi.mock("./representatives/RepresentativesTab", () => ({
  RepresentativesTab: () => <div data-testid="representatives-workflow" />,
}));
vi.mock("./vehicles/VehiclesTab", () => ({
  VehiclesTab: () => <div data-testid="vehicles-workflow" />,
}));
vi.mock("../suppliers/SuppliersPage", () => ({
  default: ({ embedded }: { embedded?: boolean }) => (
    <div data-testid="suppliers-workflow" data-embedded={embedded ? "true" : "false"} />
  ),
}));

import RepresentativesVehiclesPage from "./RepresentativesVehiclesPage";

function LocationProbe() {
  const location = useLocation();
  return <output data-testid="route-location">{`${location.pathname}${location.search}${location.hash}`}</output>;
}

const renderPage = (entry = "/representatives-vehicles") => render(
  <MemoryRouter initialEntries={[entry]}>
    <RepresentativesVehiclesPage />
    <LocationProbe />
  </MemoryRouter>,
);

afterEach(() => {
  cleanup();
  direction = "rtl";
  owner = false;
  permissions = new Set<string>();
  companyId = 7;
  principalId = 11;
  loading = false;
  vi.restoreAllMocks();
  localStorage.clear();
});

describe("RepresentativesVehiclesPage", () => {
  it.each(["vehicles", "suppliers"] as const)(
    "restores the last selected %s tab after leaving and remounting without a query",
    async (tab) => {
      permissions = new Set(["representative.read", "vehicle.read", "supplier.read"]);
      const first = renderPage();
      fireEvent.click(screen.getByRole("tab", { name: "representativesVehicles.tabs." + tab }));
      await waitFor(() => expect(screen.getByTestId("route-location").textContent).toBe(
        "/representatives-vehicles?tab=" + tab,
      ));
      first.unmount();

      renderPage();
      await waitFor(() => expect(screen.getByTestId("route-location").textContent).toBe(
        "/representatives-vehicles?tab=" + tab,
      ));
      expect(screen.getByRole("tab", { name: "representativesVehicles.tabs." + tab }))
        .toHaveAttribute("aria-selected", "true");
      expect(screen.getByTestId(tab + "-workflow")).toBeTruthy();
      expect(screen.queryByTestId("representatives-workflow")).toBeNull();
      expect(screen.queryByTestId((tab === "vehicles" ? "suppliers" : "vehicles") + "-workflow")).toBeNull();
    },
  );

  it("lets an explicit readable query override the stored Vehicles preference", async () => {
    permissions = new Set(["representative.read", "vehicle.read", "supplier.read"]);
    const first = renderPage();
    fireEvent.click(screen.getByRole("tab", { name: "representativesVehicles.tabs.vehicles" }));
    await waitFor(() => expect(screen.getByTestId("route-location").textContent).toBe(
      "/representatives-vehicles?tab=vehicles",
    ));
    first.unmount();

    renderPage("/representatives-vehicles?tab=representatives");
    expect(screen.getByRole("tab", { name: "representativesVehicles.tabs.representatives" }))
      .toHaveAttribute("aria-selected", "true");
    expect(screen.getByTestId("representatives-workflow")).toBeTruthy();
    expect(screen.queryByTestId("vehicles-workflow")).toBeNull();
    expect(screen.getByTestId("route-location").textContent).toBe(
      "/representatives-vehicles?tab=representatives",
    );
  });

  it.each(["", "?tab=vehicles", "?tab=invalid"])(
    "falls back safely when the stored tab loses access, with query %s",
    async (query) => {
      permissions = new Set(["representative.read", "vehicle.read", "supplier.read"]);
      const first = renderPage();
      fireEvent.click(screen.getByRole("tab", { name: "representativesVehicles.tabs.vehicles" }));
      first.unmount();

      permissions = new Set(["representative.read", "supplier.read"]);
      renderPage("/representatives-vehicles" + query);
      await waitFor(() => expect(screen.getByTestId("route-location").textContent).toBe(
        "/representatives-vehicles?tab=representatives",
      ));
      expect(screen.getByRole("tab", { name: "representativesVehicles.tabs.vehicles" })).toBeDisabled();
      expect(screen.queryByTestId("vehicles-workflow")).toBeNull();
      expect(screen.queryByTestId("suppliers-workflow")).toBeNull();
      expect(screen.getByTestId("representatives-workflow")).toBeTruthy();
    },
  );

  it.each([
    { company: 8, principal: 11 },
    { company: 7, principal: 12 },
  ])("isolates preferences for canonical company $company / principal $principal", async ({ company, principal }) => {
    permissions = new Set(["representative.read", "vehicle.read", "supplier.read"]);
    // Untrusted local identity hints must not replace the canonical access scope.
    localStorage.setItem("company_id", "99");
    localStorage.setItem("principal_id", "999");
    const first = renderPage();
    fireEvent.click(screen.getByRole("tab", { name: "representativesVehicles.tabs.vehicles" }));
    first.unmount();

    companyId = company;
    principalId = principal;
    const other = renderPage();
    expect(screen.getByRole("tab", { name: "representativesVehicles.tabs.representatives" }))
      .toHaveAttribute("aria-selected", "true");
    expect(screen.queryByTestId("vehicles-workflow")).toBeNull();
    fireEvent.click(screen.getByRole("tab", { name: "representativesVehicles.tabs.suppliers" }));
    other.unmount();

    companyId = 7;
    principalId = 11;
    renderPage();
    await waitFor(() => expect(screen.getByTestId("route-location").textContent).toBe(
      "/representatives-vehicles?tab=vehicles",
    ));
    expect(screen.queryByTestId("suppliers-workflow")).toBeNull();
  });

  it.each(["company", "principal"] as const)(
    "does not use a shared preference when canonical %s identity is unavailable",
    async (missing) => {
      permissions = new Set(["representative.read", "vehicle.read"]);
      if (missing === "company") companyId = undefined;
      else principalId = undefined;
      const first = renderPage();
      fireEvent.click(screen.getByRole("tab", { name: "representativesVehicles.tabs.vehicles" }));
      await waitFor(() => expect(screen.getByTestId("route-location").textContent).toBe(
        "/representatives-vehicles?tab=vehicles",
      ));
      expect(localStorage.length).toBe(0);
      first.unmount();

      renderPage();
      expect(screen.getByRole("tab", { name: "representativesVehicles.tabs.representatives" }))
        .toHaveAttribute("aria-selected", "true");
      expect(screen.queryByTestId("vehicles-workflow")).toBeNull();
    },
  );

  it("restores a readable preference for an invalid query and preserves other URL state", async () => {
    permissions = new Set(["representative.read", "vehicle.read", "supplier.read"]);
    const first = renderPage();
    fireEvent.click(screen.getByRole("tab", { name: "representativesVehicles.tabs.suppliers" }));
    first.unmount();

    renderPage("/representatives-vehicles?tab=invalid&filter=recent#workspace");
    await waitFor(() => expect(screen.getByTestId("route-location").textContent).toBe(
      "/representatives-vehicles?tab=suppliers&filter=recent#workspace",
    ));
    expect(screen.queryByTestId("representatives-workflow")).toBeNull();
    expect(screen.queryByTestId("vehicles-workflow")).toBeNull();
  });

  it("waits for access to load before restoring or replacing the stored preference", async () => {
    permissions = new Set(["representative.read", "vehicle.read", "supplier.read"]);
    const first = renderPage();
    fireEvent.click(screen.getByRole("tab", { name: "representativesVehicles.tabs.vehicles" }));
    first.unmount();

    loading = true;
    const pending = renderPage();
    expect(screen.getByText("common.loading")).toBeTruthy();
    expect(screen.getByTestId("route-location").textContent).toBe("/representatives-vehicles");
    expect(screen.queryByTestId("vehicles-workflow")).toBeNull();
    loading = false;
    pending.rerender(
      <MemoryRouter initialEntries={["/representatives-vehicles"]}>
        <RepresentativesVehiclesPage />
        <LocationProbe />
      </MemoryRouter>,
    );
    await waitFor(() => expect(screen.getByTestId("route-location").textContent).toBe(
      "/representatives-vehicles?tab=vehicles",
    ));
    expect(screen.queryByTestId("representatives-workflow")).toBeNull();
  });

  it.each(["getItem", "setItem"] as const)(
    "keeps tab navigation usable when preference storage %s fails",
    async (method) => {
      permissions = new Set(["representative.read", "vehicle.read"]);
      vi.spyOn(Storage.prototype, method).mockImplementation(() => {
        throw new DOMException("Storage unavailable", "SecurityError");
      });
      renderPage();
      fireEvent.click(screen.getByRole("tab", { name: "representativesVehicles.tabs.vehicles" }));
      await waitFor(() => expect(screen.getByTestId("route-location").textContent).toBe(
        "/representatives-vehicles?tab=vehicles",
      ));
      expect(screen.getByTestId("vehicles-workflow")).toBeTruthy();
    },
  );

  it("lets a user with all read capabilities switch between all three real tabs", async () => {
    permissions = new Set(["representative.read", "vehicle.read", "supplier.read"]);
    renderPage();
    const tabs = within(screen.getByRole("tablist")).getAllByRole("tab");
    expect(tabs).toHaveLength(3);
    expect(tabs[0]?.getAttribute("aria-selected")).toBe("true");
    expect(tabs[0]?.className).toContain("bg-amber-400");
    expect(tabs[1]?.className).toContain("bg-white/[0.06]");
    expect(screen.getByTestId("representatives-workflow")).toBeTruthy();

    fireEvent.click(tabs[1]!);
    await waitFor(() => expect(tabs[1]?.getAttribute("aria-selected")).toBe("true"));
    expect(tabs[1]?.className).toContain("bg-amber-400");
    expect(tabs[0]?.className).toContain("bg-white/[0.06]");
    expect(screen.getByTestId("vehicles-workflow")).toBeTruthy();
  });

  it("keeps Suppliers inside the same three-tab workspace", async () => {
    permissions = new Set(["representative.read", "vehicle.read", "supplier.read"]);
    renderPage();

    const tabs = within(screen.getByRole("tablist")).getAllByRole("tab");
    expect(tabs).toHaveLength(3);
    fireEvent.click(tabs[2]!);

    await waitFor(() => expect(screen.getByTestId("route-location").textContent).toBe(
      "/representatives-vehicles?tab=suppliers",
    ));
    expect(tabs[2]?.getAttribute("aria-selected")).toBe("true");
    expect(screen.getByTestId("suppliers-workflow").getAttribute("data-embedded")).toBe("true");
  });

  it("opens the Suppliers tab directly for a supplier-only backoffice user", async () => {
    permissions = new Set(["supplier.read"]);
    renderPage();

    const tabs = within(screen.getByRole("tablist")).getAllByRole("tab");
    await waitFor(() => expect(screen.getByTestId("route-location").textContent).toBe(
      "/representatives-vehicles?tab=suppliers",
    ));
    expect((tabs[0] as HTMLButtonElement).disabled).toBe(true);
    expect((tabs[1] as HTMLButtonElement).disabled).toBe(true);
    expect((tabs[2] as HTMLButtonElement).disabled).toBe(false);
    expect(screen.getByTestId("suppliers-workflow")).toBeTruthy();
  });

  it("allows vehicle-only users to reach the page without representative.read", async () => {
    permissions = new Set(["vehicle.read"]);
    renderPage();
    const tabs = within(screen.getByRole("tablist")).getAllByRole("tab");
    await waitFor(() => expect(tabs[1]?.getAttribute("aria-selected")).toBe("true"));
    expect((tabs[0] as HTMLButtonElement).disabled).toBe(true);
    expect((tabs[1] as HTMLButtonElement).disabled).toBe(false);
    expect(screen.queryByTestId("representatives-workflow")).toBeNull();
    expect(screen.getByTestId("vehicles-workflow")).toBeTruthy();
  });

  it("does not let representative.read grant vehicle access", () => {
    permissions = new Set(["representative.read"]);
    renderPage();
    const tabs = within(screen.getByRole("tablist")).getAllByRole("tab");
    expect((tabs[0] as HTMLButtonElement).disabled).toBe(false);
    expect((tabs[1] as HTMLButtonElement).disabled).toBe(true);
    expect(screen.queryByTestId("vehicles-workflow")).toBeNull();
  });

  it("shows a fail-closed page when neither read capability exists", () => {
    renderPage();
    expect(screen.getByText("representativesVehicles.noAccess")).toBeTruthy();
    expect(screen.queryByTestId("representatives-workflow")).toBeNull();
    expect(screen.queryByTestId("vehicles-workflow")).toBeNull();
    expect(screen.queryByTestId("suppliers-workflow")).toBeNull();
  });

  it("follows i18n direction in Arabic RTL and English LTR", () => {
    permissions = new Set(["representative.read"]);
    const { container, rerender } = renderPage();
    expect(container.querySelector("main")?.getAttribute("dir")).toBe("rtl");
    direction = "ltr";
    rerender(
      <MemoryRouter initialEntries={["/representatives-vehicles?tab=representatives"]}>
        <RepresentativesVehiclesPage />
        <LocationProbe />
      </MemoryRouter>,
    );
    expect(container.querySelector("main")?.getAttribute("dir")).toBe("ltr");
  });

  it("restores Vehicles directly from ?tab=vehicles and Representatives from ?tab=representatives", async () => {
    permissions = new Set(["representative.read", "vehicle.read"]);
    const first = renderPage("/representatives-vehicles?tab=vehicles");
    let tabs = within(screen.getByRole("tablist")).getAllByRole("tab");
    expect(tabs[1]?.getAttribute("aria-selected")).toBe("true");
    await waitFor(() => expect(screen.getByTestId("vehicles-workflow")).toBeTruthy());
    first.unmount();

    renderPage("/representatives-vehicles?tab=representatives");
    tabs = within(screen.getByRole("tablist")).getAllByRole("tab");
    expect(tabs[0]?.getAttribute("aria-selected")).toBe("true");
    await waitFor(() => expect(screen.getByTestId("representatives-workflow")).toBeTruthy());
  });

  it("fails unauthorized ?tab=vehicles over to the first readable tab and normalizes the URL", async () => {
    permissions = new Set(["representative.read"]);
    renderPage("/representatives-vehicles?tab=vehicles");

    await waitFor(() => expect(screen.getByTestId("route-location").textContent).toBe(
      "/representatives-vehicles?tab=representatives",
    ));
    expect(screen.queryByTestId("vehicles-workflow")).toBeNull();
    expect(screen.getByTestId("representatives-workflow")).toBeTruthy();
  });

  it("normalizes an invalid tab and switches tabs through router navigation without losing loaded tabs", async () => {
    permissions = new Set(["representative.read", "vehicle.read"]);
    renderPage("/representatives-vehicles?tab=garbage");
    await waitFor(() => expect(screen.getByTestId("route-location").textContent).toBe(
      "/representatives-vehicles?tab=representatives",
    ));

    const tabs = within(screen.getByRole("tablist")).getAllByRole("tab");
    fireEvent.click(tabs[1]!);
    await waitFor(() => expect(screen.getByTestId("route-location").textContent).toBe(
      "/representatives-vehicles?tab=vehicles",
    ));
    expect(screen.getByTestId("representatives-workflow")).toBeTruthy();
    expect(screen.getByTestId("vehicles-workflow")).toBeTruthy();
  });
});
