import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { companyLocalDate, useInboundOptions } from "./useInboundOptions";

const payload = (asOfDate: string, cost: string, revision: number) => ({
  currency_code: "JOD",
  as_of_date: asOfDate,
  items: [{
    product_variant_id: 7, base_uom_id: 1,
    uoms: [
      { id: 1, code: "EACH", name: "Each", factor_to_base: "1" },
      { id: 2, code: "CARTON", name: "Carton", factor_to_base: "20" },
    ],
    purchase_cost_reference: {
      amount: cost, purchase_uom_id: 2, currency_code: "JOD", revision,
    },
  }],
});

beforeEach(() => vi.clearAllMocks());
afterEach(cleanup);

describe("IT-09 inbound hints are advisory and revalidated", () => {
  it("uses the company local midnight, not the browser's local midnight", () => {
    expect(companyLocalDate("Asia/Amman", new Date("2026-11-01T20:59:59Z"))).toBe("2026-11-01");
    expect(companyLocalDate("Asia/Amman", new Date("2026-11-01T21:00:01Z"))).toBe("2026-11-02");
    expect(companyLocalDate("Invalid/Unknown")).toBeNull();
  });

  it("revalidates changed UOM/reference/date values rather than returning old hints at posting", async () => {
    const fetch = vi.fn()
      .mockResolvedValueOnce(payload("2026-11-01", "8.000000", 1))
      .mockResolvedValueOnce(payload("2026-11-02", "9.500000", 2));
    const { result } = renderHook(() => useInboundOptions(fetch, "1:9"));
    await act(async () => { await result.current.ensure([7]); });
    expect(result.current.asOfDate).toBe("2026-11-01");
    expect(result.current.options.get(7)?.purchase_cost_reference?.amount).toBe("8.000000");

    let updated!: Awaited<ReturnType<typeof result.current.refresh>>;
    await act(async () => { updated = await result.current.refresh([7]); });
    expect(updated.asOfDate).toBe("2026-11-02");
    expect(updated.options.get(7)?.purchase_cost_reference?.revision).toBe(2);
    expect(result.current.options.get(7)?.purchase_cost_reference?.amount).toBe("9.500000");
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(fetch.mock.calls.map(([, opts]) => JSON.parse(opts.body).ids)).toEqual([[7], [7]]);
  });

  it("fences delayed old-day responses that arrive after new-day revalidation", async () => {
    let resolveOld!: (value: unknown) => void;
    const fetch = vi.fn()
      .mockReturnValueOnce(new Promise((resolve) => { resolveOld = resolve; }))
      .mockResolvedValueOnce(payload("2026-11-02", "9.500000", 2));
    const { result } = renderHook(() => useInboundOptions(fetch, "1:9"));
    let old!: Promise<unknown>;
    act(() => { old = result.current.ensure([7]); });
    await act(async () => { await result.current.refresh([7]); });
    await act(async () => {
      resolveOld(payload("2026-11-01", "8.000000", 1));
      await expect(old).rejects.toMatchObject({ code: "INBOUND_OPTIONS_INVALID" });
    });
    expect(result.current.asOfDate).toBe("2026-11-02");
    expect(result.current.options.get(7)?.purchase_cost_reference?.revision).toBe(2);
  });

  it("clears previously displayed hints on failed revalidation and retries explicitly", async () => {
    const fetch = vi.fn()
      .mockResolvedValueOnce(payload("2026-11-01", "8.000000", 1))
      .mockRejectedValueOnce(new Error("network"))
      .mockResolvedValueOnce(payload("2026-11-02", "9.000000", 2));
    const { result } = renderHook(() => useInboundOptions(fetch, "1:9"));
    await act(async () => { await result.current.ensure([7]); });
    await act(async () => { await expect(result.current.refresh([7])).rejects.toThrow("network"); });
    expect(result.current.options.size).toBe(0);
    expect(result.current.asOfDate).toBeNull();
    await act(async () => { await result.current.ensure([7]); });
    expect(result.current.asOfDate).toBe("2026-11-02");
  });

  it("hides the old principal's cache immediately and does not trust their in-flight response", async () => {
    let resolveOld!: (value: unknown) => void;
    const fetch = vi.fn()
      .mockReturnValueOnce(new Promise((resolve) => { resolveOld = resolve; }))
      .mockResolvedValueOnce(payload("2026-11-02", "12.000000", 5));
    const { result, rerender } = renderHook(({ scope }) => useInboundOptions(fetch, scope), {
      initialProps: { scope: "1:9" },
    });
    let old!: Promise<unknown>;
    act(() => { old = result.current.ensure([7]); });
    rerender({ scope: "2:10" });
    expect(result.current.options.size).toBe(0);
    expect(result.current.asOfDate).toBeNull();
    await act(async () => { await result.current.ensure([7]); });
    await act(async () => {
      resolveOld(payload("2026-11-01", "8.000000", 1));
      await expect(old).rejects.toMatchObject({ code: "INBOUND_OPTIONS_INVALID" });
    });
    await waitFor(() => expect(result.current.options.get(7)?.purchase_cost_reference?.revision).toBe(5));
  });
});
