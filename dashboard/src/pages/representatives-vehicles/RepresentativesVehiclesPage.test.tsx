import type { ReactNode } from "react";
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

let direction: "rtl" | "ltr" = "rtl";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { dir: () => direction },
  }),
}));
vi.mock("@/components/dashboard/WorkspaceTopBar", () => ({
  WorkspaceTopBar: ({ children }: { children: ReactNode }) => <div data-testid="workspace-top-bar">{children}</div>,
}));
vi.mock("./representatives/RepresentativesTab", () => ({
  RepresentativesTab: () => <div data-testid="representatives-workflow" />,
}));

import RepresentativesVehiclesPage from "./RepresentativesVehiclesPage";

afterEach(() => {
  cleanup();
  direction = "rtl";
});

describe("RepresentativesVehiclesPage", () => {
  it("keeps the active Representatives and gated Vehicles tabs inside the blue top bar", () => {
    render(<RepresentativesVehiclesPage />);

    const topBar = screen.getByTestId("workspace-top-bar");
    const tablist = within(topBar).getByRole("tablist");
    const tabs = within(tablist).getAllByRole("tab");

    expect(tabs).toHaveLength(2);
    expect(tabs[0]?.getAttribute("aria-selected")).toBe("true");
    expect((tabs[1] as HTMLButtonElement).disabled).toBe(true);
    expect(tabs[1]?.getAttribute("aria-disabled")).toBe("true");
    expect(screen.getByTestId("representatives-workflow")).toBeTruthy();
  });

  it("follows i18n direction in both Arabic RTL and English LTR modes", () => {
    const { container, rerender } = render(<RepresentativesVehiclesPage />);
    expect(container.querySelector("main")?.getAttribute("dir")).toBe("rtl");

    direction = "ltr";
    rerender(<RepresentativesVehiclesPage />);
    expect(container.querySelector("main")?.getAttribute("dir")).toBe("ltr");
  });
});
