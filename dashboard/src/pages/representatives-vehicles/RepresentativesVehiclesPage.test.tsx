import type { ReactNode } from "react";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, useLocation } from "react-router-dom";

let direction: "rtl" | "ltr" = "rtl";
let owner = false;
let permissions = new Set<string>();

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
    isLoading: false,
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

import RepresentativesVehiclesPage from "./RepresentativesVehiclesPage";

function LocationProbe() {
  const location = useLocation();
  return <output data-testid="route-location">{`${location.pathname}${location.search}`}</output>;
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
});

describe("RepresentativesVehiclesPage", () => {
  it("lets a user with both read capabilities switch between real tabs", async () => {
    permissions = new Set(["representative.read", "vehicle.read"]);
    renderPage();
    const tabs = within(screen.getByRole("tablist")).getAllByRole("tab");
    expect(tabs).toHaveLength(2);
    expect(tabs[0]?.getAttribute("aria-selected")).toBe("true");
    expect(screen.getByTestId("representatives-workflow")).toBeTruthy();

    fireEvent.click(tabs[1]!);
    await waitFor(() => expect(tabs[1]?.getAttribute("aria-selected")).toBe("true"));
    expect(screen.getByTestId("vehicles-workflow")).toBeTruthy();
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
