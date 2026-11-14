import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import {
  parseSourceWarehouseAuditStatus,
  useSourceWarehouseAuditStatus,
} from "@/features/dispatch/useSourceWarehouseAuditStatus";

const clear = {
  status: "ACTIVE", stocktake_session_id: null,
  stocktake_reference: null, stocktake_status: null,
} as const;
const hasLock = {
  status: "AUDIT_LOCK", stocktake_session_id: 10,
  stocktake_reference: "STK-8FCE5D62A105", stocktake_status: "COUNTING",
} as const;

describe("Source warehouse's signed audit lock authority", () => {
  it("distinguishes a real location-specific stocktake from an unlocked warehouse", () => {
    expect(parseSourceWarehouseAuditStatus(clear)).toEqual({ kind: "active" });
    expect(parseSourceWarehouseAuditStatus(hasLock)).toEqual({
      kind: "locked", sessionId: 10, reference: hasLock.stocktake_reference,
      stocktakeStatus: "COUNTING",
    });
    expect(() => parseSourceWarehouseAuditStatus({ is_locked: false })).toThrow();
    expect(() => parseSourceWarehouseAuditStatus({ status: "AUDIT_LOCK" })).toThrow();
    expect(() => parseSourceWarehouseAuditStatus({ status: "DENIED" })).toThrow();
    expect(() => parseSourceWarehouseAuditStatus({ status: "ACTIVE" })).toThrow();
    expect(() => parseSourceWarehouseAuditStatus({ ...clear, stocktake_status: "COUNTING" })).toThrow();
  });

  it("reports failed or unauthorized reads as unverified rather than an active stocktake", async () => {
    const fetchStatus = vi.fn().mockRejectedValueOnce(new Error("403")).mockResolvedValue(clear);
    const { result } = renderHook(() => useSourceWarehouseAuditStatus({
      warehouseId: "3", actorKey: "company:1:owner:7", enabled: true, fetchStatus,
    }));
    await waitFor(() => expect(result.current.state.kind).toBe("unverified"));
    expect(fetchStatus).toHaveBeenCalledTimes(1);
    act(() => result.current.retry());
    await waitFor(() => expect(result.current.state.kind).toBe("active"));
    expect(fetchStatus).toHaveBeenCalledTimes(2);
  });

  it("refreshes after leaving and returning from Warehouse's official cancellation", async () => {
    const fetchStatus = vi.fn().mockResolvedValueOnce(hasLock).mockResolvedValueOnce(clear);
    const props = { warehouseId: "3", actorKey: "company:1:owner:7", enabled: true, fetchStatus };
    const { result, rerender } = renderHook((p) => useSourceWarehouseAuditStatus(p), {
      initialProps: props,
    });
    await waitFor(() => expect(result.current.state.kind).toBe("locked"));
    rerender({ ...props, enabled: false });
    expect(result.current.state.kind).toBe("idle");
    rerender(props);
    await waitFor(() => expect(result.current.state.kind).toBe("active"));
    expect(fetchStatus).toHaveBeenCalledTimes(2);
  });

  it("never admits a different warehouse or company's stale response", async () => {
    let resolveOld: ((data: unknown) => void) | null = null;
    const old = new Promise<unknown>((resolve) => { resolveOld = resolve; });
    const fetchStatus = vi.fn().mockReturnValueOnce(old).mockResolvedValueOnce(clear);
    const args = { warehouseId: "3", actorKey: "company:1:owner:7", enabled: true, fetchStatus };
    const { result, rerender } = renderHook((p) => useSourceWarehouseAuditStatus(p), {
      initialProps: args,
    });
    rerender({ ...args, warehouseId: "1", actorKey: "company:2:owner:8" });
    await waitFor(() => expect(result.current.state.kind).toBe("active"));
    await act(async () => { resolveOld?.(hasLock); });
    expect(result.current.state.kind).toBe("active");
    expect(fetchStatus).toHaveBeenCalledTimes(2);
    expect(fetchStatus.mock.calls[1][0]).toContain("location_id=1");
    expect(fetchStatus.mock.calls[0][1].signal.aborted).toBe(true);
  });

  it("rejects malformed ACTIVE responses instead of silently opening a route", async () => {
    const fetchStatus = vi.fn().mockResolvedValue({ status: "ACTIVE", stocktake_session_id: 10 });
    const { result } = renderHook(() => useSourceWarehouseAuditStatus({
      warehouseId: "3", actorKey: "company:1:owner:7", enabled: true, fetchStatus,
    }));
    await waitFor(() => expect(result.current.state.kind).toBe("unverified"));
  });
});
