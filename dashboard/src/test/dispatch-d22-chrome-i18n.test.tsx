import { useEffect } from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { setAppLanguage } from "@/i18n";
import {
  DispatchChrome, DispatchChromeHost, useDispatchChromeBridge,
} from "@/features/dispatch/stableUi/DispatchChrome";

vi.mock("@/hooks/useDashboardSession", () => ({
  useDashboardSession: () => ({ generation: 1, identity: "signed-owner" }),
}));
vi.mock("@/components/dispatch/PendingRoutesTable", () => ({
  PendingRoutesTable: () => <div data-testid="dispatch-empty-table" />,
}));

type View = Parameters<NonNullable<ReturnType<typeof useDispatchChromeBridge>>["publish"]>[0];

const routeActions = {
  onTabChange: vi.fn(),
  onShortages: vi.fn(),
  onBulkSchedule: vi.fn(),
};
const onShowPostponed = vi.fn();
const realRoutes = {
  table: <div data-testid="signed-route-cards">Signed route cards</div>,
  notices: null, accessNotice: null,
  postponedCount: 4, hasPostponed: true, onShowPostponed,
};
const admittedView: View = {
  activeTab: "routes",
  admitted: true, permissionKnown: true, readVisible: true,
  allowedTabs: ["routes", "launch", "zones"],
  canShortages: true, canZoneManage: true, hasShortages: true,
};

function PublishSignedView({ view }: { view: View }) {
  const bridge = useDispatchChromeBridge();
  useEffect(() => { bridge?.publish(view, routeActions, realRoutes); }, [bridge, view]);
  return null;
}

describe("D22 DispatchChrome public AR/EN translation and guards", () => {
  it("switches real hosted chrome in place without remounting signed route rows or changing count", async () => {
    await act(async () => { await setAppLanguage("ar"); });
    const { unmount } = render(
      <DispatchChromeHost active><PublishSignedView view={admittedView} /></DispatchChromeHost>,
    );

    const arHeading = await screen.findByText("مناطق قيد العمل (الخطوط النشطة)");
    expect(arHeading).toBeInTheDocument();
    expect(screen.getByRole("tablist", { name: "أقسام إدارة التوزيع" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "الخطوط النشطة" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "إطلاق خط جديد" })).toBeEnabled();
    expect(screen.getByRole("tab", { name: "هيكلة المناطق" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "طلبات ونواقص" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "عرض المؤجل (4)" })).toBeEnabled();

    const frame = screen.getByTestId("dispatch-shared-topbar");
    const routeCards = screen.getByTestId("signed-route-cards");
    const tabNodes = screen.getAllByRole("tab");

    await act(async () => { await setAppLanguage("en"); });
    await waitFor(() => {
      expect(screen.getByText("Zones in progress (active routes)")).toBeInTheDocument();
    });
    expect(screen.getByRole("tablist", { name: "Dispatch sections" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Active routes" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "Launch new route" })).toBeEnabled();
    expect(screen.getByRole("tab", { name: "Zone structure" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Requests & shortages" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Show postponed (4)" })).toBeEnabled();
    expect(screen.getByTestId("dispatch-shared-topbar")).toBe(frame);
    expect(screen.getByTestId("signed-route-cards")).toBe(routeCards);
    expect(screen.getAllByRole("tab")).toEqual(tabNodes);
    expect(frame.parentElement?.textContent).not.toMatch(/[\u0600-\u06FF]/);

    await act(async () => { await setAppLanguage("ar"); });
    expect(screen.getByText("مناطق قيد العمل (الخطوط النشطة)")).toBe(arHeading);
    expect(screen.getByRole("button", { name: "عرض المؤجل (4)" })).toBeEnabled();
    expect(screen.getByTestId("dispatch-shared-topbar")).toBe(frame);
    unmount();
  });

  it("keeps English tabs mounted and fail-closed across admission and access changes", async () => {
    await act(async () => { await setAppLanguage("en"); });
    const callbacks = {
      onTabChange: vi.fn(), onShortages: vi.fn(), onBulkSchedule: vi.fn(),
    };
    const base = {
      activeTab: "routes" as const,
      permissionKnown: false, allowedTabs: ["routes"] as const,
      canShortages: true, canZoneManage: true,
      ...callbacks,
    };
    const { rerender } = render(<DispatchChrome {...base} admitted={false} />);
    const tabs = screen.getAllByRole("tab");
    expect(tabs).toHaveLength(3);
    expect(tabs.every(tab => (tab as HTMLButtonElement).disabled)).toBe(true);
    expect(screen.getByRole("button", { name: "Requests & shortages" })).toBeDisabled();
    fireEvent.click(tabs[1]);
    expect(callbacks.onTabChange).not.toHaveBeenCalled();

    rerender(<DispatchChrome {...base} admitted permissionKnown />);
    expect(screen.getAllByRole("tab")).toEqual(tabs);
    expect(screen.getByRole("tab", { name: "Active routes" })).toBeEnabled();
    expect(screen.getByRole("tab", { name: "Launch new route" })).toBeDisabled();
    expect(screen.getByRole("tab", { name: "Zone structure" })).toBeDisabled();
    fireEvent.click(tabs[1]);
    expect(callbacks.onTabChange).not.toHaveBeenCalled();
    fireEvent.click(tabs[0]);
    expect(callbacks.onTabChange).toHaveBeenCalledOnce();
    expect(callbacks.onTabChange).toHaveBeenCalledWith("routes");

    rerender(<DispatchChrome {...base} activeTab="zones" admitted permissionKnown
      allowedTabs={["zones"]} canZoneManage={false} canShortages={false} />);
    expect(screen.getAllByRole("tab")).toEqual(tabs);
    expect(screen.getByRole("tab", { name: "Zone structure" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("button", { name: "Bulk scheduling" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Requests & shortages" })).toBeDisabled();

    rerender(<DispatchChrome {...base} activeTab="zones" admitted permissionKnown
      allowedTabs={["zones"]} canZoneManage canShortages />);
    fireEvent.click(screen.getByRole("button", { name: "Bulk scheduling" }));
    fireEvent.click(screen.getByRole("button", { name: "Requests & shortages" }));
    expect(callbacks.onBulkSchedule).toHaveBeenCalledOnce();
    expect(callbacks.onShortages).toHaveBeenCalledOnce();
  });
});
