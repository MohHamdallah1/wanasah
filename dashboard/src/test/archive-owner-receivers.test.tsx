import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { useDispatchOwnerNavigation } from "@/features/dispatch/useOwnerNavigation";
import { useStocktakeLifecycle } from "@/pages/inventory/stocktake/hooks/useStocktakeLifecycle";
import type { DispatchNavigationIntent } from "@/features/dispatch/navigation";
import type { PendingRoute } from "@/types/dispatch";
import { useSettlementOwnerNavigation } from "@/features/operations/useSettlementOwnerNavigation";
import { FINANCIAL_SETTLEMENT_READY_STATUS, SESSION_STATUS, type DriverData } from "@/data/operations-data";

const mocks = vi.hoisted(() => ({ fetch: vi.fn(), error: vi.fn() }));
vi.mock("@/hooks/useAuthFetch", () => ({ useAuthFetch: () => mocks.fetch }));
vi.mock("sonner", () => ({ toast: { error: mocks.error, success: vi.fn() } }));
beforeEach(() => { mocks.fetch.mockReset(); mocks.error.mockReset(); localStorage.clear(); });
afterEach(cleanup);

const route: PendingRoute = { id: "70", zoneId: "1", zoneName: "Zone", driverId: "4", driverName: "Driver", vehicleId: "7", shopsRemaining: 2, status: "active", sessionEnded: false, sessionBound: true, can_execute: true, commercial_context: null };

const driver: DriverData = {
  session: { session_id: 80, driver_name: "Driver", start_time: null, is_authorized_to_sell: false, is_on_break: false, vehicle_label: null },
  settlement: { driver_name: "Driver", status: FINANCIAL_SETTLEMENT_READY_STATUS,
    financials: { expected_cash_in_hand: "0", cash_from_sales: "0", cash_from_debts: "0", inventory_shortage_cash: "0" },
    visits: { completed_total: 0, successful_sales: 0, pending_remaining: 0 }, inventory: [] },
};

describe("Operations revalidates exact custody settlement ownership", () => {
  it("opens the existing settlement only after a fresh bounded session read", async () => {
    mocks.fetch.mockResolvedValue([driver]);
    const onReady = vi.fn(), onConsumed = vi.fn();
    renderHook(() => useSettlementOwnerNavigation({ intent: { version: 1, kind: "settlement-owner", sessionId: 80 }, onReady, onConsumed }));
    await waitFor(() => expect(onConsumed).toHaveBeenCalledOnce());
    expect(mocks.fetch).toHaveBeenCalledWith("/admin/sessions/today?session_id=80", expect.objectContaining({ signal: expect.any(AbortSignal) }));
    expect(onReady).toHaveBeenCalledWith(driver);
  });

  it.each([[], [{ ...driver, session: { ...driver.session, session_id: 81 } }], [{ ...driver, settlement: { ...driver.settlement, status: SESSION_STATUS.AWAITING_INVENTORY_RECONCILIATION } }]])("rejects missing, mismatched or unready custody sessions", async (response) => {
    mocks.fetch.mockResolvedValue(response);
    const onReady = vi.fn(), onConsumed = vi.fn();
    renderHook(() => useSettlementOwnerNavigation({ intent: { version: 1, kind: "settlement-owner", sessionId: 80 }, onReady, onConsumed }));
    await waitFor(() => expect(onConsumed).toHaveBeenCalledOnce());
    expect(onReady).not.toHaveBeenCalled(); expect(mocks.error).toHaveBeenCalledOnce();
  });

  it("retains owner API denial and request identity", async () => {
    mocks.fetch.mockRejectedValue(Object.assign(new Error("denied"), { status: 403, code: "PERMISSION_DENIED", requestId: "settlement-owner-42" }));
    const onReady = vi.fn(), onConsumed = vi.fn();
    renderHook(() => useSettlementOwnerNavigation({ intent: { version: 1, kind: "settlement-owner", sessionId: 80 }, onReady, onConsumed }));
    await waitFor(() => expect(onConsumed).toHaveBeenCalledOnce());
    expect(onReady).not.toHaveBeenCalled(); expect(mocks.error.mock.calls[0][0]).toContain("settlement-owner-42");
  });
});

describe("Dispatch consumes identity through fresh owning reads", () => {
  it("retains exact handshake identity and explicit cancellation intent after fresh route lookup", async () => {
    mocks.fetch.mockResolvedValue([route]);
    const focus: DispatchNavigationIntent = { version: 1, kind: "reservation-owner", routeId: 70, transferId: 21, openCancel: false };
    const onRoute = vi.fn(), onConsumed = vi.fn();
    renderHook(() => useDispatchOwnerNavigation({ focus, onRoute, onShortage: vi.fn(), onConsumed }));
    await waitFor(() => expect(onConsumed).toHaveBeenCalledOnce());
    expect(onRoute).toHaveBeenCalledWith(route, focus);
    expect(mocks.fetch).toHaveBeenCalledWith("/dispatch/active_routes?route_id=70", expect.anything());
  });

  it("fetches current route evidence before opening its owner workflow", async () => {
    mocks.fetch.mockResolvedValue([route]);
    const onRoute = vi.fn(), onShortage = vi.fn(), onConsumed = vi.fn();
    renderHook(() => useDispatchOwnerNavigation({ focus: { version: 1, kind: "route-load", routeId: 70 }, onRoute, onShortage, onConsumed }));
    await waitFor(() => expect(onConsumed).toHaveBeenCalledOnce());
    expect(mocks.fetch).toHaveBeenCalledWith("/dispatch/active_routes?route_id=70", expect.objectContaining({ signal: expect.any(AbortSignal) }));
    expect(onRoute).toHaveBeenCalledWith(route, expect.objectContaining({ routeId: 70 }));
    expect(onShortage).not.toHaveBeenCalled();
  });

  it.each([[], [{ ...route, can_execute: false }]])("rejects missing or no-longer-executable routes", async (response) => {
    mocks.fetch.mockResolvedValue(response);
    const onRoute = vi.fn(), onConsumed = vi.fn();
    renderHook(() => useDispatchOwnerNavigation({ focus: { version: 1, kind: "route-load", routeId: 70 }, onRoute, onShortage: vi.fn(), onConsumed }));
    await waitFor(() => expect(onConsumed).toHaveBeenCalledOnce());
    expect(onRoute).not.toHaveBeenCalled(); expect(mocks.error).toHaveBeenCalledOnce();
  });

  it("opens only the exact pending shortage from the current admin endpoint", async () => {
    const shortage = { id: "90", productId: "101", status: "pending" };
    mocks.fetch.mockResolvedValue([shortage, { id: "91", status: "pending" }]);
    const onShortage = vi.fn(), onConsumed = vi.fn();
    renderHook(() => useDispatchOwnerNavigation({ focus: { version: 1, kind: "shortage-owner", shortageId: 90 }, onRoute: vi.fn(), onShortage, onConsumed }));
    await waitFor(() => expect(onConsumed).toHaveBeenCalledOnce());
    expect(mocks.fetch).toHaveBeenCalledWith("/dispatch/shortages?shortage_id=90", expect.anything());
    expect(onShortage).toHaveBeenCalledWith(expect.any(Array), shortage);
  });

  it("does not interpret navigation as permission after an owner API denial", async () => {
    mocks.fetch.mockRejectedValue(Object.assign(new Error("denied"), { status: 403, code: "PERMISSION_DENIED", requestId: "owner-request-42" }));
    const onRoute = vi.fn(), onShortage = vi.fn(), onConsumed = vi.fn();
    const focus: DispatchNavigationIntent = { version: 1, kind: "shortage-owner", shortageId: 90 };
    renderHook(() => useDispatchOwnerNavigation({ focus, onRoute, onShortage, onConsumed }));
    await waitFor(() => expect(onConsumed).toHaveBeenCalledOnce());
    expect(onRoute).not.toHaveBeenCalled(); expect(onShortage).not.toHaveBeenCalled();
    expect(mocks.error.mock.calls[0][0]).toContain("owner-request-42");
  });
});

const context = (status = "COUNTING") => ({ session_id: 30, stocktake_type: "CYCLE_COUNT", status, location_id: 1, source_location_id: 1, related_work_session_id: null });
const stocktakeArgs = () => ({
  locationId: 1, focusSessionId: 30, sessionKey: "test-session", phaseKey: "test-phase", sessionId: null, sessionLocationId: null,
  activeSessions: [], activeSessionsTotal: 0, sessionsLoading: false, sessionsLoadFailed: false,
  authenticatedFetch: mocks.fetch, loadCountSheet: vi.fn().mockResolvedValue(undefined), loadReview: vi.fn().mockResolvedValue(undefined),
  setSessionId: vi.fn(), setSessionLocationId: vi.fn(), setPhase: vi.fn(), clearRows: vi.fn(), clearReview: vi.fn(),
  notifyStocktakeChanged: vi.fn().mockResolvedValue(undefined), onFocusUnavailable: vi.fn(),
});

describe("Stocktake owner focus retains current authority and saved drafts", () => {
  it.each(["COUNTING", "PENDING_REVIEW", "RECOUNT_REQUIRED"])("re-reads exact context and opens the existing %s workflow", async (status) => {
    mocks.fetch.mockResolvedValue(context(status));
    const args = stocktakeArgs();
    renderHook(() => useStocktakeLifecycle(args));
    await waitFor(() => expect(status === "PENDING_REVIEW" ? args.loadReview : args.loadCountSheet).toHaveBeenCalledWith("30", 1));
    expect(mocks.fetch).toHaveBeenCalledWith("/warehouse/unified/stocktake/30/context?anchor_location_id=1");
    expect(args.onFocusUnavailable).not.toHaveBeenCalled();
  });

  it.each(["DRAFT", "APPROVED", "POSTED", "CANCELLED"])("fails closed for stale %s navigation without overwriting another session", async (status) => {
    localStorage.setItem("test-session", "29"); localStorage.setItem("test-phase", "WAITING_INDEPENDENT");
    localStorage.setItem("saved-count-draft", "keep");
    mocks.fetch.mockResolvedValue(context(status));
    const args = stocktakeArgs();
    renderHook(() => useStocktakeLifecycle(args));
    await waitFor(() => expect(args.onFocusUnavailable).toHaveBeenCalledOnce());
    expect(args.loadCountSheet).not.toHaveBeenCalled(); expect(args.loadReview).not.toHaveBeenCalled();
    expect(args.setSessionId).not.toHaveBeenCalledWith("30");
    expect(localStorage.getItem("test-session")).toBe("29");
    expect(localStorage.getItem("test-phase")).toBe("WAITING_INDEPENDENT");
    expect(localStorage.getItem("saved-count-draft")).toBe("keep");
  });

  it("restores the previous resume pointer if a subsequent owner read is denied", async () => {
    localStorage.setItem("test-session", "29");
    localStorage.setItem("test-phase", "WAITING_INDEPENDENT");
    mocks.fetch.mockResolvedValue(context("RECOUNT_REQUIRED"));
    const args = stocktakeArgs(); args.loadCountSheet.mockRejectedValue(new Error("count denied"));
    renderHook(() => useStocktakeLifecycle(args));
    await waitFor(() => expect(args.onFocusUnavailable).toHaveBeenCalledOnce());
    expect(localStorage.getItem("test-session")).toBe("29");
  });

  it("consumes focus once rather than reopening a completed session", async () => {
    mocks.fetch.mockResolvedValue(context());
    const args = stocktakeArgs();
    const hook = renderHook((props) => useStocktakeLifecycle(props), { initialProps: args });
    await waitFor(() => expect(args.loadCountSheet).toHaveBeenCalledOnce());
    await act(async () => { localStorage.removeItem("test-session"); hook.rerender({ ...args, loadCountSheet: vi.fn().mockResolvedValue(undefined) }); });
    expect(mocks.fetch).toHaveBeenCalledOnce();
  });
});
