import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DEFAULT_BATCH_INDEX_FILTERS, type BatchIndexFilters } from "./batchIndexContracts";
import { useBatchIndex } from "./useBatchIndex";

const mocks = vi.hoisted(() => ({ fetch: vi.fn() }));
vi.mock("@/hooks/useAuthFetch", () => ({ useAuthFetch: () => mocks.fetch }));

const batch = (id: number) => ({
  batch_id: id,
  batch_number: `LOT-${id}`,
  production_date: null,
  expiry_date: null,
  disposition: "RELEASED",
  disposition_reason: null,
  disposition_revision: 1,
  allowed_disposition_targets: [],
  days_to_expiry: null,
  product_id: id,
  product_variant_id: id,
  product_name: `Product ${id}`,
  sku: `SKU-${id}`,
  family_name: "Family",
  lot_control_mode: "OPTIONAL",
  expiry_control_mode: "OPTIONAL",
  minimum_remaining_shelf_life_days: 0,
  sellability_state: "SELLABLE",
  sellability_reason_codes: [],
  base_uom_id: 1,
  base_uom_code: "EACH",
  base_uom_name: "Each",
  display_uom_id: 1,
  display_uom_code: "EACH",
  display_uom_name: "Each",
  display_factor_to_base: "1",
  quantity_scale: 0,
  quantity_step: "1",
  on_hand_quantity: "8",
  reserved_quantity: "0",
  available_for_sale_quantity: "8",
  unavailable_quantity: "0",
  available_status_quantity: "8",
  quarantined_quantity: "0",
  blocked_quantity: "0",
  recalled_quantity: "0",
  damaged_quantity: "0",
  disposal_pending_quantity: "0",
});
const page = (locationId: number, ids: number[]) => ({
  location_id: locationId, as_of_date: "2026-11-02",
  items: ids.map(batch), next_cursor: null, has_more: false,
});
const summary = (locationId: number, total: number) => ({
  location_id: locationId, as_of_date: "2026-11-02",
  total_relevant_batches: total, expired_count: 0, expiring_soon_count: 0,
  non_sellable_count: 0, quarantined_count: 0, blocked_count: 0,
  recalled_count: 0, damaged_or_disposal_attention_count: 0,
});
const deferred = <T,>() => {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
};
type Args = { locationId: number; filters: BatchIndexFilters; active: boolean };
const initial: Args = { locationId: 11, filters: DEFAULT_BATCH_INDEX_FILTERS, active: true };
const mount = () => renderHook(
  ({ locationId, filters, active }: Args) =>
    useBatchIndex({ locationId, filters, expiryWarningDays: 30, active }),
  { initialProps: initial },
);
const calls = (suffix: "cursor" | "summary") =>
  mocks.fetch.mock.calls.filter(([url]) => String(url).includes(`/batches/${suffix}?`));

beforeEach(() => mocks.fetch.mockReset());
afterEach(cleanup);

describe("IT-03/IT-04 batch reentry and scoped revalidation", () => {
  it("loads on the first frame without falsely painting an empty result", async () => {
    const first = deferred<unknown>();
    mocks.fetch.mockImplementation((url: string) =>
      String(url).includes("/cursor?") ? first.promise : Promise.resolve(summary(11, 1)));
    const hook = mount();
    expect(hook.result.current.loading).toBe(true);
    expect(hook.result.current.items).toEqual([]);
    await act(async () => first.resolve(page(11, [41])));
    await waitFor(() => expect(hook.result.current.items.map((item) => item.batch_id)).toEqual([41]));
    // A missing request path must not be silently accepted by our API mock.
    expect(mocks.fetch.mock.calls.every(([url]) => typeof url === "string")).toBe(true);
    expect(hook.result.current.loading).toBe(false);
  });

  it("keeps identical-query rows and summary visible but marked updating until two fresh reads arrive", async () => {
    const nextList = deferred<unknown>();
    const nextSummary = deferred<unknown>();
    let listCount = 0;
    let summaryCount = 0;
    mocks.fetch.mockImplementation((url: string) => {
      if (String(url).includes("/cursor?")) return ++listCount === 1 ? page(11, [41]) : nextList.promise;
      return ++summaryCount === 1 ? summary(11, 1) : nextSummary.promise;
    });
    const hook = mount();
    await waitFor(() => expect(hook.result.current.items).toHaveLength(1));
    await waitFor(() => expect(hook.result.current.summary?.total_relevant_batches).toBe(1));

    act(() => { void hook.result.current.refresh(); });
    await waitFor(() => expect(hook.result.current.loading && hook.result.current.summaryLoading).toBe(true));
    expect(hook.result.current.items.map((item) => item.batch_id)).toEqual([41]);
    expect(hook.result.current.summary?.total_relevant_batches).toBe(1);
    expect(hook.result.current.hasMore).toBe(false);

    await act(async () => {
      nextList.resolve(page(11, [42]));
      nextSummary.resolve(summary(11, 2));
    });
    await waitFor(() => expect(hook.result.current.items.map((item) => item.batch_id)).toEqual([42]));
    expect(hook.result.current.summary?.total_relevant_batches).toBe(2);
    expect(hook.result.current.loading).toBe(false);
  });

  it("hides A synchronously for a different location/filter and ignores delayed A responses", async () => {
    const oldList = deferred<unknown>();
    const oldSummary = deferred<unknown>();
    const newList = deferred<unknown>();
    const newSummary = deferred<unknown>();
    mocks.fetch.mockImplementation((url: string) => {
      const u = new URL(String(url), "http://local");
      const loc = Number(u.searchParams.get("location_id"));
      if (u.pathname.endsWith("/cursor")) return loc === 11 ? oldList.promise : newList.promise;
      return loc === 11 ? oldSummary.promise : newSummary.promise;
    });
    const hook = mount();
    const filtered = { ...DEFAULT_BATCH_INDEX_FILTERS, search: "new" };
    hook.rerender({ locationId: 12, filters: filtered, active: true });
    expect(hook.result.current.items).toEqual([]);
    expect(hook.result.current.summary).toBeNull();
    expect(hook.result.current.loading).toBe(true);
    await act(async () => {
      oldList.resolve(page(11, [41]));
      oldSummary.resolve(summary(11, 9));
    });
    expect(hook.result.current.items).toEqual([]);
    expect(hook.result.current.summary).toBeNull();
    await act(async () => {
      newList.resolve(page(12, [42]));
      newSummary.resolve(summary(12, 1));
    });
    await waitFor(() => expect(hook.result.current.items.map((item) => item.batch_id)).toEqual([42]));
    expect(hook.result.current.summary?.location_id).toBe(12);
    expect(calls("cursor").every(([url]) => String(url).includes("location_id="))).toBe(true);
  });

  it("does no hidden-tab fetch; one fresh request on reentry retains only the matching prior frame", async () => {
    const returnPage = deferred<unknown>();
    const returnSummary = deferred<unknown>();
    let listCount = 0;
    let summaryCount = 0;
    mocks.fetch.mockImplementation((url: string) => {
      if (String(url).includes("/cursor?")) return ++listCount === 1 ? page(11, [41]) : returnPage.promise;
      return ++summaryCount === 1 ? summary(11, 1) : returnSummary.promise;
    });
    const hook = mount();
    await waitFor(() => expect(hook.result.current.items).toHaveLength(1));
    hook.rerender({ ...initial, active: false });
    const count = mocks.fetch.mock.calls.length;
    await act(async () => Promise.resolve());
    expect(mocks.fetch).toHaveBeenCalledTimes(count);
    hook.rerender({ ...initial, active: true });
    await waitFor(() => expect(calls("cursor")).toHaveLength(2));
    expect(hook.result.current.items.map((item) => item.batch_id)).toEqual([41]);
    expect(hook.result.current.loading).toBe(true);
    await act(async () => {
      returnPage.resolve(page(11, [42]));
      returnSummary.resolve(summary(11, 2));
    });
    await waitFor(() => expect(hook.result.current.items.map((item) => item.batch_id)).toEqual([42]));
  });

  it("drops list and summary on failed revalidation and on 403 permission revocation", async () => {
    const rejected = deferred<unknown>();
    mocks.fetch.mockImplementation((url: string) => String(url).includes("/cursor?")
      ? (calls("cursor").length === 1 ? page(11, [41]) : rejected.promise)
      : summary(11, 1));
    const hook = mount();
    await waitFor(() => expect(hook.result.current.items).toHaveLength(1));
    act(() => { void hook.result.current.refresh(); });
    await waitFor(() => expect(hook.result.current.loading).toBe(true));
    await act(async () => rejected.reject(Object.assign(new Error("Denied"), { status: 403 })));
    await waitFor(() => expect(hook.result.current.listError).toBe(true));
    expect(hook.result.current.items).toEqual([]);

    act(() => window.dispatchEvent(new Event("inventory-permission-denied")));
    expect(hook.result.current.items).toEqual([]);
    expect(hook.result.current.summary).toBeNull();
    expect(hook.result.current.hasMore).toBe(false);
  });

  it("clears an invalid summary instead of retaining an obsolete count as verified", async () => {
    let summaryCount = 0;
    mocks.fetch.mockImplementation((url: string) => String(url).includes("/cursor?")
      ? page(11, [41])
      : ++summaryCount === 1
        ? summary(11, 1)
        : { location_id: 11, as_of_date: "2026-11-02", total_relevant_batches: -1 });
    const hook = mount();
    await waitFor(() => expect(hook.result.current.summary?.total_relevant_batches).toBe(1));
    act(() => { void hook.result.current.retrySummary(); });
    await waitFor(() => expect(hook.result.current.summaryError).toBe(true));
    expect(hook.result.current.summary).toBeNull();
  });
});
