import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { LedgerEntry } from "@/pages/inventory/ledger/contracts";
import { useLedgerReference } from "@/pages/inventory/ledger/useLedgerReference";

const mocks = vi.hoisted(() => ({
  fetch: vi.fn(),
  identity: "company-A:principal-A",
  generation: "A",
  subscribers: new Set<() => void>(),
}));
vi.mock("@/hooks/useAuthFetch", () => ({ useAuthFetch: () => mocks.fetch }));
vi.mock("@/lib/authStorage", () => ({
  captureDashboardSession: () => ({ generation: mocks.generation, identity: mocks.identity }),
  isDashboardSessionCurrent: (scope: { generation: string; identity: string }) =>
    scope.generation === mocks.generation && scope.identity === mocks.identity,
  subscribeDashboardSession: (listener: () => void) => {
    mocks.subscribers.add(listener);
    return () => { mocks.subscribers.delete(listener); };
  },
}));

const entry = { id: 101, product_name: "Sensitive A product", reference_type: "TRANSFER", reference: "REF-A" } as LedgerEntry;
const row = (id: number) => ({
  id, product_variant_id: 7, product_name: "Sensitive A product",
  base_uom_id: 1, base_uom_code: "EACH", quantity_scale: 0, quantity_step: "1",
  type: "TRANSFER", reference_type: "TRANSFER", movement_kind: "PHYSICAL",
  quantity: "-3", balance_before: "10", balance_after: "7", balance_scope: "PRODUCT_LOCATION",
  batch_id: null, batch_number: null, source_location_id: 11, source_location_name: "Warehouse A",
  destination_location_id: 12, destination_location_name: "Warehouse B",
  source_stock_status: "AVAILABLE", destination_stock_status: "AVAILABLE",
  display_uom_id: 1, display_uom_code: "EACH", display_uom_name: "Each", display_factor_to_base: "1",
  currency_code: "JOD", cost_method: null, input_quantity: null, input_uom_code: null,
  input_uom_name: null, input_unit_cost: null, total_cost: null, average_cost_after: null,
  average_cost_uom_code: null, average_cost_uom_name: null,
  admin_name: "Sensitive actor", reference: "REF-A", notes: "Sensitive note",
  supplier_name: null, supplier_code: null, supplier_id: null, date: "2026-11-02T09:00:00+00:00",
});
const page = (ids: number[], cursor: string | null = null) => ({
  items: ids.map(row), has_more: cursor !== null, next_cursor: cursor,
  total: null, available_types: [],
});
const forbidden = (status: number) => Object.assign(new Error("Denied"), { status });
const deferred = <T,>() => {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((a, b) => { resolve = a; reject = b; });
  return { promise, resolve, reject };
};

beforeEach(() => {
  mocks.fetch.mockReset();
  mocks.identity = "company-A:principal-A";
  mocks.generation = "A";
  mocks.subscribers.clear();
});

describe("CP10 reference fail-closed authority", () => {
  for (const status of [401, 403]) {
    it(`purges partial reference evidence after a later-page ${status}`, async () => {
      const next = deferred<unknown>();
      mocks.fetch.mockImplementation((path: string) =>
        path.includes("cursor=") ? next.promise : Promise.resolve(page([101], "signed-cursor")));
      const { result } = renderHook(() => useLedgerReference(11));
      act(() => result.current.open(entry));
      await waitFor(() => expect(result.current.items).toHaveLength(1));
      await act(async () => { next.reject(forbidden(status)); });
      expect(result.current.denied).toBe(true);
      expect(result.current.entry).toBeNull();
      expect(result.current.items).toEqual([]);
      expect(result.current.error).toBe(false); // revoked, not a stale/empty success
    });
  }

  it("preserves same-scope authorized partial evidence on 503, then retries successfully", async () => {
    let failed = false;
    mocks.fetch.mockImplementation((path: string) => {
      if (!path.includes("cursor=")) return Promise.resolve(page([101], "signed-cursor"));
      if (!failed) { failed = true; return Promise.reject(forbidden(503)); }
      return Promise.resolve(page([102]));
    });
    const { result } = renderHook(() => useLedgerReference(11));
    act(() => result.current.open(entry));
    await waitFor(() => expect(result.current.error).toBe(true));
    expect(result.current.denied).toBe(false);
    expect(result.current.items).toHaveLength(1);
    act(() => result.current.retry());
    await waitFor(() => expect(result.current.items).toHaveLength(2));
    expect(result.current.error).toBe(false);
  });

  it("fences delayed A response after company/principal switch even if transport ignores abort", async () => {
    const stale = deferred<unknown>();
    mocks.fetch.mockImplementation(() => stale.promise);
    const { result } = renderHook(() => useLedgerReference(11));
    act(() => result.current.open(entry));
    act(() => {
      mocks.identity = "company-B:principal-B";
      mocks.generation = "B";
      for (const listener of mocks.subscribers) listener();
    });
    expect(result.current.entry).toBeNull();
    expect(result.current.denied).toBe(true);
    await act(async () => { stale.resolve(page([101])); });
    expect(result.current.items).toEqual([]);
  });

  it("drops an open reference on location change and tab deactivation", async () => {
    mocks.fetch.mockResolvedValue(page([101]));
    const { result, rerender } = renderHook(({ location, active }) =>
      useLedgerReference(location, active), { initialProps: { location: 11, active: true } });
    act(() => result.current.open(entry));
    await waitFor(() => expect(result.current.items).toHaveLength(1));
    rerender({ location: 12, active: true });
    await waitFor(() => expect(result.current.entry).toBeNull());
    expect(result.current.items).toEqual([]);
    act(() => result.current.open(entry));
    await waitFor(() => expect(result.current.items).toHaveLength(1));
    rerender({ location: 12, active: false });
    await waitFor(() => expect(result.current.items).toEqual([]));
    expect(result.current.entry).toBeNull();
  });
});
