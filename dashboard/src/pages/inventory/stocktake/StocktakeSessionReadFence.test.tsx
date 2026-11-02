import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useStocktakeLifecycle } from "./hooks/useStocktakeLifecycle";
import { useStocktakeCounting } from "./hooks/useStocktakeCounting";
import type { StocktakeAuthFetch } from "./types";

vi.mock("@/hooks/useInventoryAccess", () => ({
  parseInventoryCapabilities: (raw: unknown) => raw,
  hasInventoryPermission: () => true,
}));

const deferred = <T,>() => {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((finish) => { resolve = finish; });
  return { promise, resolve };
};

const context = (id: number) => ({
  session_id: id,
  stocktake_type: "CYCLE_COUNT",
  status: "COUNTING",
  location_id: 5,
  source_location_id: 5,
  related_work_session_id: null,
});

beforeEach(() => localStorage.clear());

describe("Stocktake V1 latest authorized session wins", () => {
  it("ignores A context after operator opens B in the same warehouse", async () => {
    const lateA = deferred<unknown>();
    const fetch: StocktakeAuthFetch = vi.fn(async (url) =>
      url.includes("/11/context") ? lateA.promise : context(12));
    const setSessionId = vi.fn();
    const loadCountSheet = vi.fn(async (_sid: string, _location?: number, _isCurrent?: () => boolean) => {});
    const args = {
      active: true,
      durableIdentity: { companyId: 3, backofficeUserId: 7 },
      locationId: 5,
      sessionKey: "test:stocktake:session",
      phaseKey: "test:stocktake:phase",
      sessionId: null,
      sessionLocationId: null,
      activeSessions: [],
      activeSessionsTotal: 0,
      sessionsLoading: false,
      sessionsLoadFailed: false,
      authenticatedFetch: fetch,
      loadCountSheet,
      loadReview: vi.fn(async () => {}),
      setSessionId,
      setSessionLocationId: vi.fn(),
      setPhase: vi.fn(),
      clearRows: vi.fn(),
      clearReview: vi.fn(),
      notifyStocktakeChanged: vi.fn(async () => {}),
    };
    const hook = renderHook(() => useStocktakeLifecycle(args));
    const openingA = hook.result.current.openSessionById("11");
    await act(async () => {
      await hook.result.current.openSessionById("12");
    });
    expect(loadCountSheet).toHaveBeenCalledTimes(1);
    expect(loadCountSheet.mock.calls[0][0]).toBe("12");
    expect(localStorage.getItem(args.sessionKey)).toBe("12");

    await act(async () => {
      lateA.resolve(context(11));
      await openingA;
    });
    expect(loadCountSheet).toHaveBeenCalledTimes(1);
    expect(setSessionId).not.toHaveBeenCalledWith("11");
    expect(localStorage.getItem(args.sessionKey)).toBe("12");
    hook.unmount();
  });

  it("ignores a delayed A count-sheet after B is selected", async () => {
    const lateA = deferred<unknown>();
    const row = (id: number) => ({
      product_variant_id: id, batch_id: id,
      stock_status: "AVAILABLE", product_name: `Product ${id}`,
      batch_number: `LOT-${id}`, expiry_date: null,
      base_uom_id: 1, base_uom_code: "EACH",
      base_uom_name: "Each", quantity_scale: 0, quantity_step: "1",
    });
    const fetch: StocktakeAuthFetch = vi.fn(async (url) => {
      if (url.startsWith("/inventory/access/me")) {
        return { location_id: 5 };
      }
      if (url.endsWith("/11/count-sheet")) return lateA.promise;
      if (url.endsWith("/12/count-sheet")) return [row(12)];
      throw new Error(`Unexpected request: ${url}`);
    });
    const setRows = vi.fn();
    const args = {
      durableIdentity: { companyId: 3, backofficeUserId: 7 },
      companyScope: "3:7", phaseKey: "test:stocktake:phase",
      phase: "REVIEW" as const,
      sessionId: null, sessionLocationId: 5, draftKey: null,
      authenticatedFetch: fetch, rows: [],
      setRows, setReview: vi.fn(), setSessionId: vi.fn(),
      setSessionLocationId: vi.fn(), setPhase: vi.fn(),
      onSubmitted: vi.fn(async () => {}),
    };
    const hook = renderHook(() => useStocktakeCounting(args));
    let allowA = true;
    const openingA = hook.result.current.loadCountSheet("11", 5, () => allowA);
    await waitFor(() => expect(fetch).toHaveBeenCalledWith("/warehouse/unified/stocktake/11/count-sheet"));
    allowA = false;
    await act(async () => {
      await hook.result.current.loadCountSheet("12", 5, () => true);
    });
    const callsAfterB = setRows.mock.calls.length;
    expect(setRows.mock.lastCall?.[0][0].product_variant_id).toBe(12);
    await act(async () => {
      lateA.resolve([row(11)]);
      await openingA;
    });
    expect(setRows).toHaveBeenCalledTimes(callsAfterB);
    expect(setRows.mock.lastCall?.[0][0].product_variant_id).toBe(12);
    hook.unmount();
  });
});
