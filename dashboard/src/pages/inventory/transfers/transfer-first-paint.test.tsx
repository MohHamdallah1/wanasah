import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ fetch: vi.fn() }));
vi.mock("@/hooks/useAuthFetch", () => ({ useAuthFetch: () => mocks.fetch }));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn(), info: vi.fn() } }));

import { useTransferList } from "./hooks/useTransferList";

const transfer = (id = 1) => ({
  id, reference_number: `TRN-${id}`, source_location_id: 11, source_location_name: "A1",
  destination_location_id: 12, destination_location_name: "A2",
  transfer_purpose: "WAREHOUSE_BALANCING" as const, status: "IN_TRANSIT" as const,
  dispatched_by: 81, dispatched_by_name: "Sender", received_by: null, received_by_name: null,
  cancelled_by: null, cancelled_by_name: null, line_count: 1, total_quantity: "4", notes: null,
  decision_reason: null, created_at: "2026-10-16T10:00:00Z", updated_at: "2026-10-16T10:00:00Z",
  accepted_at: null, rejected_at: null, cancelled_at: null, posted_at: null,
});
const page = (items = [transfer()]) => ({ items, total: items.length, has_more: false, next_cursor: null });

type Frame = { loading: boolean; rows: number; failed: boolean };

/** Records every committed render, not just the settled one. */
function renderRecorded() {
  const frames: Frame[] = [];
  const view = renderHook(() => {
    const list = useTransferList();
    frames.push({ loading: list.loading, rows: list.items.length, failed: list.failure !== null });
    return list;
  });
  return { frames, ...view };
}

/**
 * The table paints "no transfers" for a frame whenever the committed state is
 * { loading: false, rows: 0, failed: false } while a request is still owed.
 */
const paintsEmptyState = (frame: Frame) => !frame.loading && frame.rows === 0 && !frame.failed;

beforeEach(() => {
  localStorage.clear();
  mocks.fetch.mockReset();
});
afterEach(cleanup);

describe("transfer list first paint", () => {
  it("is already loading on the very first frame, never 'empty' before the first page", async () => {
    let resolve!: (value: unknown) => void;
    mocks.fetch.mockReturnValueOnce(new Promise((r) => { resolve = r; }));
    const { frames, result } = renderRecorded();

    expect(frames.length).toBeGreaterThan(0);
    expect(frames.some(paintsEmptyState)).toBe(false);
    expect(result.current.loading).toBe(true);

    await act(async () => { resolve(page([transfer(1), transfer(2)])); });
    await waitFor(() => expect(result.current.items).toHaveLength(2));
    expect(result.current.loading).toBe(false);
  });

  it("still reports a genuinely empty result once the first page has arrived", async () => {
    mocks.fetch.mockResolvedValueOnce(page([]));
    const { frames, result } = renderRecorded();

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.items).toHaveLength(0);
    expect(result.current.failure).toBeNull();
    // The empty state appears exactly once: as the settled last frame.
    expect(frames.filter(paintsEmptyState)).toHaveLength(1);
    expect(paintsEmptyState(frames[frames.length - 1])).toBe(true);
  });

  it("does not flash 'empty' when the status filter changes the scope", async () => {
    mocks.fetch.mockResolvedValueOnce(page([transfer(1)]));
    const { frames, result } = renderRecorded();
    await waitFor(() => expect(result.current.items).toHaveLength(1));

    let resolveFiltered!: (value: unknown) => void;
    mocks.fetch.mockReturnValueOnce(new Promise((r) => { resolveFiltered = r; }));
    const before = frames.length;
    act(() => result.current.setStatus("IN_TRANSIT"));

    await waitFor(() => expect(mocks.fetch).toHaveBeenCalledTimes(2));
    const sinceChange = frames.slice(before);
    expect(sinceChange.length).toBeGreaterThan(0);
    expect(sinceChange.some(paintsEmptyState)).toBe(false);
    expect(result.current.loading).toBe(true);

    await act(async () => { resolveFiltered(page([transfer(3)])); });
    await waitFor(() => expect(result.current.items.map((row) => row.id)).toEqual([3]));
    expect(result.current.loading).toBe(false);
  });

  it("stops reporting loading and surfaces the failure when the first page fails", async () => {
    mocks.fetch.mockRejectedValueOnce(Object.assign(new Error("down"), { status: 503 }));
    const { result } = renderRecorded();

    await waitFor(() => expect(result.current.failure?.phase).toBe("first"));
    expect(result.current.loading).toBe(false);
    expect(result.current.items).toHaveLength(0);
  });
});
