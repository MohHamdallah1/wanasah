import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  DEFAULT_BATCH_INDEX_FILTERS,
  type BatchIndexFilters,
} from "@/pages/inventory/batches/batchIndexContracts";

const mocks = vi.hoisted(() => ({ fetch: vi.fn() }));
vi.mock("@/hooks/useAuthFetch", () => ({ useAuthFetch: () => mocks.fetch }));

import { useBatchIndex } from "@/pages/inventory/batches/useBatchIndex";

const rawItem = (id: number, productName = `Product ${id}`) => ({
  batch_id: id,
  batch_number: `LOT-${id}`,
  production_date: "2026-01-01",
  expiry_date: "2026-12-31",
  disposition: "RELEASED",
  disposition_reason: null,
  disposition_revision: 1,
  allowed_disposition_targets: ["QUARANTINED", "BLOCKED", "RECALLED"],
  days_to_expiry: 60,
  product_id: 10,
  product_variant_id: 100 + id,
  product_name: productName,
  sku: `SKU-${id}`,
  family_name: "Family A",
  lot_control_mode: "REQUIRED",
  expiry_control_mode: "REQUIRED",
  minimum_remaining_shelf_life_days: 14,
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
  on_hand_quantity: "10",
  reserved_quantity: "1",
  available_for_sale_quantity: "9",
  unavailable_quantity: "0",
  available_status_quantity: "10",
  quarantined_quantity: "0",
  blocked_quantity: "0",
  recalled_quantity: "0",
  damaged_quantity: "0",
  disposal_pending_quantity: "0",
});

const page = (locationId: number, id: number, name?: string) => ({
  location_id: locationId,
  as_of_date: "2026-11-02",
  items: [rawItem(id, name)],
  next_cursor: null,
  has_more: false,
});

const summary = (locationId: number, total = 1) => ({
  location_id: locationId,
  as_of_date: "2026-11-02",
  total_relevant_batches: total,
  expired_count: 0,
  expiring_soon_count: 0,
  non_sellable_count: 0,
  quarantined_count: 0,
  blocked_count: 0,
  recalled_count: 0,
  damaged_or_disposal_attention_count: 0,
});

type Props = {
  locationId: number;
  filters: BatchIndexFilters;
  active: boolean;
  refreshKey: number;
};

const initialProps: Props = {
  locationId: 11,
  filters: DEFAULT_BATCH_INDEX_FILTERS,
  active: true,
  refreshKey: 0,
};

const deferred = <T,>() => {
  let resolvePromise!: (value: T) => void;
  let rejectPromise!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolveValue, rejectValue) => {
    resolvePromise = resolveValue;
    rejectPromise = rejectValue;
  });
  return { promise, resolve: resolvePromise, reject: rejectPromise };
};

const renderBatchIndex = (props: Props = initialProps) =>
  renderHook(
    (current: Props) => useBatchIndex({
      locationId: current.locationId,
      filters: current.filters,
      active: current.active,
      refreshKey: current.refreshKey,
      expiryWarningDays: 30,
    }),
    { initialProps: props },
  );

beforeEach(() => {
  mocks.fetch.mockReset();
});

afterEach(() => {
  cleanup();
});

describe("IT-03 / IT-04 batch reentry and refresh authority", () => {
  it("does not repeat batch HTTP reads on ordinary same-scope hide and reentry", async () => {
    mocks.fetch.mockImplementation(async (path: string) =>
      path.includes("/summary?")
        ? summary(11)
        : page(11, 1),
    );

    const view = renderBatchIndex();
    await waitFor(() => expect(view.result.current.items[0]?.batch_id).toBe(1));
    await waitFor(() => expect(view.result.current.summary?.total_relevant_batches).toBe(1));
    expect(mocks.fetch).toHaveBeenCalledTimes(2);

    view.rerender({ ...initialProps, active: false });
    await act(async () => undefined);
    expect(mocks.fetch).toHaveBeenCalledTimes(2);

    view.rerender({ ...initialProps, active: true });
    await act(async () => undefined);
    expect(view.result.current.items[0]?.batch_id).toBe(1);
    expect(view.result.current.summary?.total_relevant_batches).toBe(1);
    expect(mocks.fetch).toHaveBeenCalledTimes(2);
  });

  it("keeps same-scope rows and summary visible while refresh is in flight, then replaces them atomically per response", async () => {
    let cycle: "initial" | "refresh" = "initial";
    const nextList = deferred<unknown>();
    const nextSummary = deferred<unknown>();
    mocks.fetch.mockImplementation((path: string) => {
      if (cycle === "initial") {
        return Promise.resolve(path.includes("/summary?") ? summary(11, 1) : page(11, 1, "Before"));
      }
      return path.includes("/summary?") ? nextSummary.promise : nextList.promise;
    });

    const view = renderBatchIndex();
    await waitFor(() => expect(view.result.current.items[0]?.product_name).toBe("Before"));
    await waitFor(() => expect(view.result.current.summary?.total_relevant_batches).toBe(1));

    cycle = "refresh";
    act(() => { void view.result.current.refresh(); });
    await waitFor(() => expect(view.result.current.loading).toBe(true));
    expect(view.result.current.items[0]?.product_name).toBe("Before");
    expect(view.result.current.summary?.total_relevant_batches).toBe(1);

    await act(async () => {
      nextList.resolve(page(11, 2, "After"));
      nextSummary.resolve(summary(11, 2));
    });
    await waitFor(() => expect(view.result.current.items[0]?.product_name).toBe("After"));
    expect(view.result.current.summary?.total_relevant_batches).toBe(2);
  });

  it("retains same-scope evidence on a transient refresh failure but drops it immediately on 403", async () => {
    let mode: "ok" | "offline" | "denied" = "ok";
    mocks.fetch.mockImplementation((path: string) => {
      if (mode === "offline") {
        return Promise.reject(Object.assign(new Error("offline"), { status: 0, code: "NETWORK_UNAVAILABLE" }));
      }
      if (mode === "denied") {
        return Promise.reject(Object.assign(new Error("denied"), { status: 403, code: "PERMISSION_DENIED" }));
      }
      return Promise.resolve(path.includes("/summary?") ? summary(11, 4) : page(11, 4));
    });

    const view = renderBatchIndex();
    await waitFor(() => expect(view.result.current.items[0]?.batch_id).toBe(4));
    await waitFor(() => expect(view.result.current.summary?.total_relevant_batches).toBe(4));

    mode = "offline";
    await act(async () => { await view.result.current.refresh(); });
    expect(view.result.current.items[0]?.batch_id).toBe(4);
    expect(view.result.current.summary?.total_relevant_batches).toBe(4);
    expect(view.result.current.listError).toBe(true);
    expect(view.result.current.summaryError).toBe(true);

    mode = "denied";
    await act(async () => { await view.result.current.refresh(); });
    expect(view.result.current.items).toEqual([]);
    expect(view.result.current.summary).toBeNull();
    expect(view.result.current.listError).toBe(true);
    expect(view.result.current.summaryError).toBe(true);
  });

  it("never exposes previous-filter rows while a changed filter scope is unresolved", async () => {
    let holdChangedScope = false;
    const changedList = deferred<unknown>();
    const changedSummary = deferred<unknown>();
    mocks.fetch.mockImplementation((path: string) => {
      if (holdChangedScope && path.includes("search=needle")) {
        return path.includes("/summary?") ? changedSummary.promise : changedList.promise;
      }
      return Promise.resolve(path.includes("/summary?") ? summary(11) : page(11, 1, "Old filter"));
    });

    const view = renderBatchIndex();
    await waitFor(() => expect(view.result.current.items[0]?.product_name).toBe("Old filter"));

    holdChangedScope = true;
    view.rerender({
      ...initialProps,
      filters: { ...DEFAULT_BATCH_INDEX_FILTERS, search: "needle" },
    });
    expect(view.result.current.items).toEqual([]);
    expect(view.result.current.summary).toBeNull();
    expect(view.result.current.loading).toBe(true);
    expect(view.result.current.summaryLoading).toBe(true);

    await act(async () => {
      changedList.resolve(page(11, 9, "Needle result"));
      changedSummary.resolve(summary(11, 9));
    });
    await waitFor(() => expect(view.result.current.items[0]?.product_name).toBe("Needle result"));
    expect(view.result.current.summary?.total_relevant_batches).toBe(9);
  });

  it("rejects delayed warehouse A responses after switching to warehouse B", async () => {
    const listA = deferred<unknown>();
    const summaryA = deferred<unknown>();
    mocks.fetch.mockImplementation((path: string) => {
      const params = new URLSearchParams(path.split("?")[1]);
      const location = Number(params.get("location_id"));
      if (location === 11) return path.includes("/summary?") ? summaryA.promise : listA.promise;
      if (location === 12) {
        return Promise.resolve(path.includes("/summary?") ? summary(12, 12) : page(12, 12, "Warehouse B"));
      }
      throw new Error(`Unexpected location: ${location}`);
    });

    const view = renderBatchIndex();
    view.rerender({ ...initialProps, locationId: 12 });

    await waitFor(() => expect(view.result.current.items[0]?.product_name).toBe("Warehouse B"));
    expect(view.result.current.summary?.location_id).toBe(12);

    await act(async () => {
      listA.resolve(page(11, 11, "Late warehouse A"));
      summaryA.resolve(summary(11, 11));
    });
    await act(async () => undefined);

    expect(view.result.current.items[0]?.product_name).toBe("Warehouse B");
    expect(view.result.current.summary?.location_id).toBe(12);
  });

  it("defers invalidation while hidden and refreshes exactly once when the tab returns", async () => {
    let listVersion = 1;
    mocks.fetch.mockImplementation(async (path: string) =>
      path.includes("/summary?")
        ? summary(11, listVersion)
        : page(11, listVersion),
    );

    const view = renderBatchIndex();
    await waitFor(() => expect(view.result.current.items[0]?.batch_id).toBe(1));
    expect(mocks.fetch).toHaveBeenCalledTimes(2);

    listVersion = 2;
    view.rerender({ ...initialProps, active: false, refreshKey: 1 });
    await act(async () => undefined);
    expect(mocks.fetch).toHaveBeenCalledTimes(2);

    view.rerender({ ...initialProps, active: true, refreshKey: 1 });
    await waitFor(() => expect(view.result.current.items[0]?.batch_id).toBe(2));
    expect(mocks.fetch).toHaveBeenCalledTimes(4);
  });

  it("keeps the shell cache bounded to Batches and partitions remounts by principal scope plus warehouse", () => {
    const shell = readFileSync(
      resolve(process.cwd(), "src/pages/inventory/MainInventory.tsx"),
      "utf8",
    );
    expect(shell).toContain('data-inventory-tab-cache="batches"');
    expect(shell).toContain('key={`${warmScopeKey ?? "invalid"}:${selectedLocationId}`}');
    expect(shell).toContain('active={activeTab === "batches"}');
    expect(shell).toContain("const targetLocationId = selectedLocationId");
    expect(shell).toContain("const admission = await locationAccess.refetch()");
    expect(shell).toContain("selectedLocationIdRef.current !== targetLocationId");
    expect(shell).toContain("admission.data.location_id !== targetLocationId");
    expect(shell).toContain('hasInventoryPermission(admission.data, "inventory.read")');
    expect(shell).toContain("admissionSeq !== batchTabAdmissionSeq.current");
    expect(shell).toContain("setBatchRefreshKey((value) => value + 1)");
    expect(shell).not.toContain('data-inventory-tab-cache="inbound"');
    expect(shell).not.toContain('data-inventory-tab-cache="transfers"');
    expect(shell).not.toContain('data-inventory-tab-cache="ledger"');
  });
});
