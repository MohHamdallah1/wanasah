import type { ReactNode } from "react";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { dir: () => "rtl" },
  }),
}));
vi.mock("@/components/dashboard/WorkspaceTopBar", () => ({
  WorkspaceTopBar: ({ children }: { children: ReactNode }) => <div>{children}</div>,
}));
vi.mock("./representatives/RepresentativesTab", () => ({
  RepresentativesTab: () => <div data-testid="representatives-workflow" />,
}));

import RepresentativesVehiclesPage from "./RepresentativesVehiclesPage";

afterEach(cleanup);

describe("RepresentativesVehiclesPage", () => {
  it("keeps Vehicles visibly gated and non-operational", () => {
    render(<RepresentativesVehiclesPage />);

    const vehicleLabel = screen.getByText("representativesVehicles.tabs.vehicles");
    const vehicleButton = vehicleLabel.closest("button") as HTMLButtonElement;

    expect(vehicleButton.disabled).toBe(true);
    expect(vehicleButton.getAttribute("aria-disabled")).toBe("true");
    expect(screen.getByTestId("representatives-workflow")).toBeTruthy();
  });
});
