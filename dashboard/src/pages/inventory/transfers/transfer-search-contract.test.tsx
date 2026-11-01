import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "@/i18n";

const mocks = vi.hoisted(() => ({ fetch: vi.fn() }));
vi.mock("@/hooks/useAuthFetch", () => ({ useAuthFetch: () => mocks.fetch }));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn(), info: vi.fn() } }));

import { useTransferList } from "./hooks/useTransferList";

const transfer = (id: number) => ({
  id, reference_number: `TRN-${id}`, source_location_id: 11, source_location_name: "A1",
  destination_location_id: 12, destination_location_name: "A2",
  transfer_purpose: "WAREHOUSE_BALANCING" as const, status: "IN_TRANSIT" as const,
  dispatched_by: 81, dispatched_by_name: "Sender", received_by: null, received_by_name: null,
  cancelled_by: null, cancelled_by_name: null, line_count: 1, total_quantity: "4",
  notes: null, decision_reason: null, created_at: "2026-10-16T10:00:00Z",
  updated_at: "2026-10-16T10:00:00Z", accepted_at: null, rejected_at: null,
  cancelled_at: null, posted_at: null,
});
const page = (ids: number[], next: string | null = null) => ({
  items: ids.map(transfer), total: ids.length, has_more: next !== null, next_cursor: next,
});
const urls = () => mocks.fetch.mock.calls.map(([path]: [string]) => new URL(path, "http://local.test"));

beforeEach(async () => {
  localStorage.clear();
  mocks.fetch.mockReset();
  await i18n.changeLanguage("en");
});
afterEach(cleanup);

describe("IT-02 transfer API search contract", () => {
  it.each([
    ["ar", "ع", "عم"],
    ["en", "a", "ab"],
  ])("never queries or displays unrelated rows for a one-character %s search", async (locale, one, two) => {
    await i18n.changeLanguage(locale);
    mocks.fetch.mockResolvedValue(page([1]));
    const { result } = renderHook(() => useTransferList());
    await waitFor(() => expect(result.current.items.map((row) => row.id)).toEqual([1]));

    act(() => result.current.setSearchInput(one));
    expect(result.current.searchTooShort).toBe(true);
    expect(result.current.items).toEqual([]);
    expect(result.current.loading).toBe(false);
    act(() => { result.current.refreshTransfers(); result.current.retry(); result.current.loadMore(); result.current.setStatus("IN_TRANSIT"); });
    await waitFor(() => expect(result.current.searchPending).toBe(false));
    expect(mocks.fetch).toHaveBeenCalledTimes(1);
    expect(urls().every((url) => !url.searchParams.has("search"))).toBe(true);

    act(() => result.current.setSearchInput(two));
    expect(result.current.items).toEqual([]);
    expect(result.current.loading).toBe(true);
    await waitFor(() => expect(urls().some((url) => url.searchParams.get("search") === two)).toBe(true));
    await waitFor(() => expect(result.current.searchPending).toBe(false));
    expect(result.current.searchTooShort).toBe(false);
    expect(urls().some((url) => url.searchParams.get("search")?.length === 1)).toBe(false);

    act(() => result.current.setSearchInput(""));
    expect(result.current.items).toEqual([]);
    await waitFor(() => expect(result.current.searchPending).toBe(false));
    await waitFor(() => expect(urls().at(-1)?.searchParams.has("search")).toBe(false));
  });

  it("rejects late prior-search results and keeps pagination bound to the new search", async () => {
    let resolveOld!: (value: unknown) => void;
    mocks.fetch
      .mockResolvedValueOnce(page([1]))
      .mockReturnValueOnce(new Promise((resolve) => { resolveOld = resolve; }))
      .mockResolvedValueOnce(page([3], "NEXT"))
      .mockResolvedValueOnce(page([4]));

    const { result } = renderHook(() => useTransferList());
    await waitFor(() => expect(result.current.items.map((row) => row.id)).toEqual([1]));
    act(() => result.current.setSearchInput("ab"));
    await waitFor(() => expect(urls().some((url) => url.searchParams.get("search") === "ab")).toBe(true));
    act(() => result.current.setSearchInput("abc"));
    expect(result.current.items).toEqual([]);
    await waitFor(() => expect(result.current.items.map((row) => row.id)).toEqual([3]));
    await act(async () => { resolveOld(page([2])); });
    expect(result.current.items.map((row) => row.id)).toEqual([3]);
    act(() => result.current.loadMore());
    await waitFor(() => expect(result.current.items.map((row) => row.id)).toEqual([3, 4]));
    expect(urls().at(-1)?.searchParams.get("search")).toBe("abc");
    expect(urls().at(-1)?.searchParams.get("cursor")).toBe("NEXT");
  });

  it("keeps the matching scope after an API failure for explicit retry", async () => {
    mocks.fetch
      .mockResolvedValueOnce(page([]))
      .mockRejectedValueOnce(Object.assign(new Error("down"), { status: 503 }))
      .mockResolvedValueOnce(page([5]));

    const { result } = renderHook(() => useTransferList());
    await waitFor(() => expect(result.current.loading).toBe(false));
    act(() => result.current.setSearchInput("سند"));
    await waitFor(() => expect(result.current.failure?.phase).toBe("first"));
    expect(result.current.items).toEqual([]);
    act(() => result.current.retry());
    await waitFor(() => expect(result.current.items.map((row) => row.id)).toEqual([5]));
    expect(urls().slice(1).every((url) => url.searchParams.get("search") === "سند")).toBe(true);
  });
});
