import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { soleVerifiedActiveStocktake, useStocktakeSessions } from "./hooks/useStocktakeSessions";
import { useStocktakeLifecycle } from "./hooks/useStocktakeLifecycle";
import type { StocktakeAuthFetch, StocktakeSessionSummary } from "./types";

vi.mock("./copy", () => ({
  useStocktakeCopy: () => ({ copy: {
    generic: { sessionsFailed: "Failed to read server sessions", sessionOpenFailed: "Cannot open session" },
    lifecycle: { unsupportedState: (state: string) => state },
  }}),
}));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

const session = (id: number, warehouse = 3, status = "COUNTING"): StocktakeSessionSummary => ({
  id, reference_number: `STK-${id}`, stocktake_type: "FULL_COUNT", status: status as StocktakeSessionSummary["status"],
  location_id: warehouse, scope_product_variant_id: null, scope_product_name: null,
  scope_batch_id: null, scope_batch_number: null, related_work_session_id: null,
  started_by: 7, started_by_name: "Stocktake owner", pending_independent_recount_required: false,
  snapshot_cutoff_at: null, created_at: "2026-11-14T00:00:00Z",
  updated_at: "2026-11-14T00:00:00Z",
});
const page = (item: StocktakeSessionSummary | null) => ({
  items: item ? [item] : [], total: item ? 1 : 0,
  next_cursor: null, has_more: false,
});
const context = (id: number, warehouse: number) => ({
  session_id: id, stocktake_type: "FULL_COUNT", status: "COUNTING",
  location_id: warehouse, source_location_id: warehouse,
  related_work_session_id: null,
});
beforeEach(() => localStorage.clear());

describe("Stocktake signed-server recovery after browser logout", () => {
  it("allows one exact authorized server session without relying on a lost local key", () => {
    expect(localStorage.length).toBe(0);
    expect(soleVerifiedActiveStocktake([session(10)], 1, 3, 3)?.reference_number).toBe("STK-10");
    expect(soleVerifiedActiveStocktake([session(10)], 1, null, 3)).toBeNull();
    expect(soleVerifiedActiveStocktake([session(10)], 1, 3, 1)).toBeNull();
    expect(soleVerifiedActiveStocktake([session(10, 1)], 1, 3, 3)).toBeNull();
    expect(soleVerifiedActiveStocktake([session(10), session(11)], 2, 3, 3)).toBeNull();
    expect(soleVerifiedActiveStocktake([session(10, 3, "CANCELLED")], 1, 3, 3)).toBeNull();
  });

  it("only marks the returned warehouse verified after a successful signed list", async () => {
    let reply!: (value: unknown) => void;
    const pending = new Promise<unknown>((resolve) => { reply = resolve; });
    const fetch: StocktakeAuthFetch = vi.fn(() => pending);
    const hook = renderHook(() => useStocktakeSessions({ enabled: true, locationId: 3, authenticatedFetch: fetch }));
    expect(hook.result.current.verifiedLocationId).toBeNull();
    await act(async () => { reply(page(session(10))); await pending; });
    await waitFor(() => expect(hook.result.current.verifiedLocationId).toBe(3));
    expect(hook.result.current.sessions[0].id).toBe(10);
    hook.unmount();
  });

  it("does not certify a failed or cross-warehouse active list", async () => {
    const fetch: StocktakeAuthFetch = vi.fn(async () => page(session(10, 1)));
    const hook = renderHook(() => useStocktakeSessions({ enabled: true, locationId: 3, authenticatedFetch: fetch }));
    await waitFor(() => expect(hook.result.current.loadFailed).toBe(true));
    expect(hook.result.current.verifiedLocationId).toBeNull();
    expect(hook.result.current.sessions).toEqual([]);
    hook.unmount();
  });

  it("verifies cancellation context by server without fetching count-sheet or changing quantities", async () => {
    const fetch: StocktakeAuthFetch = vi.fn(async () => context(10, 3));
    const setSessionId = vi.fn();
    const setSessionLocationId = vi.fn();
    const loadCountSheet = vi.fn();
    const hook = renderHook(() => useStocktakeLifecycle({
      active: false, durableIdentity: { companyId: 1, backofficeUserId: 9 },
      locationId: 3, sessionKey: "stocktake:test:company1:3",
      phaseKey: "stocktake:test:phase:company1:3",
      sessionId: null, sessionLocationId: null,
      activeSessions: [session(10)], activeSessionsTotal: 1, sessionsLoading: false,
      sessionsLoadFailed: false, authenticatedFetch: fetch, loadCountSheet,
      loadReview: vi.fn(), setSessionId, setSessionLocationId,
      setPhase: vi.fn(), clearRows: vi.fn(), clearReview: vi.fn(),
      notifyStocktakeChanged: vi.fn(async () => {}),
    }));
    await act(async () => expect(await hook.result.current.prepareCancellation(session(10))).toBe(true));
    expect(fetch).toHaveBeenCalledWith("/warehouse/unified/stocktake/10/context?anchor_location_id=3");
    expect(loadCountSheet).not.toHaveBeenCalled();
    expect(setSessionId).toHaveBeenCalledWith("10");
    expect(setSessionLocationId).toHaveBeenCalledWith(3);
    expect(localStorage.getItem("stocktake:test:company1:3")).toBe("10");
    hook.unmount();
  });

  it("refuses wrong-warehouse or terminal session context before cancellation", async () => {
    const fetch: StocktakeAuthFetch = vi.fn(async () => context(10, 1));
    const setSessionId = vi.fn();
    const props = {
      active: false, durableIdentity: null, locationId: 3,
      sessionKey: "stocktake:test:company1:3", phaseKey: "stocktake:test:phase:company1:3",
      sessionId: null, sessionLocationId: null, activeSessions: [session(10)],
      activeSessionsTotal: 1, sessionsLoading: false, sessionsLoadFailed: false,
      authenticatedFetch: fetch, loadCountSheet: vi.fn(), loadReview: vi.fn(),
      setSessionId, setSessionLocationId: vi.fn(), setPhase: vi.fn(),
      clearRows: vi.fn(), clearReview: vi.fn(), notifyStocktakeChanged: vi.fn(async () => {}),
    };
    const hook = renderHook(() => useStocktakeLifecycle(props));
    await expect(hook.result.current.prepareCancellation(session(10))).rejects.toThrow();
    expect(setSessionId).not.toHaveBeenCalled();
    expect(localStorage.getItem(props.sessionKey)).toBeNull();
    hook.unmount();
  });
});
