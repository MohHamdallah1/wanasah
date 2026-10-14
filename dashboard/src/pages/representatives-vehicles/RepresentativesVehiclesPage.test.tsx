import type { ReactNode } from "react";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

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

afterEach(() => {
  cleanup();
  direction = "rtl";
  owner = false;
  permissions = new Set<string>();
});

describe("RepresentativesVehiclesPage", () => {
  it("lets a user with both read capabilities switch between real tabs", async () => {
    permissions = new Set(["representative.read", "vehicle.read"]);
    render(<RepresentativesVehiclesPage />);
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
    render(<RepresentativesVehiclesPage />);
    const tabs = within(screen.getByRole("tablist")).getAllByRole("tab");
    await waitFor(() => expect(tabs[1]?.getAttribute("aria-selected")).toBe("true"));
    expect((tabs[0] as HTMLButtonElement).disabled).toBe(true);
    expect((tabs[1] as HTMLButtonElement).disabled).toBe(false);
    expect(screen.queryByTestId("representatives-workflow")).toBeNull();
    expect(screen.getByTestId("vehicles-workflow")).toBeTruthy();
  });

  it("does not let representative.read grant vehicle access", () => {
    permissions = new Set(["representative.read"]);
    render(<RepresentativesVehiclesPage />);
    const tabs = within(screen.getByRole("tablist")).getAllByRole("tab");
    expect((tabs[0] as HTMLButtonElement).disabled).toBe(false);
    expect((tabs[1] as HTMLButtonElement).disabled).toBe(true);
    expect(screen.queryByTestId("vehicles-workflow")).toBeNull();
  });

  it("shows a fail-closed page when neither read capability exists", () => {
    render(<RepresentativesVehiclesPage />);
    expect(screen.getByText("representativesVehicles.noAccess")).toBeTruthy();
    expect(screen.queryByTestId("representatives-workflow")).toBeNull();
    expect(screen.queryByTestId("vehicles-workflow")).toBeNull();
  });

  it("follows i18n direction in Arabic RTL and English LTR", () => {
    permissions = new Set(["representative.read"]);
    const { container, rerender } = render(<RepresentativesVehiclesPage />);
    expect(container.querySelector("main")?.getAttribute("dir")).toBe("rtl");
    direction = "ltr";
    rerender(<RepresentativesVehiclesPage />);
    expect(container.querySelector("main")?.getAttribute("dir")).toBe("ltr");
  });
});
