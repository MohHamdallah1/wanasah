import { useCallback, useEffect, useMemo, useState } from "react";

type AuditStatusResponse = {
  status: "ACTIVE" | "AUDIT_LOCK";
  stocktake_session_id: number | null;
  stocktake_reference: string | null;
  stocktake_status: string | null;
};

export type SourceWarehouseAuditState =
  | { kind: "idle" }
  | { kind: "checking" }
  | { kind: "unverified" }
  | { kind: "active" }
  | { kind: "locked"; sessionId: number; reference: string; stocktakeStatus: string };

type FetchStatus = (path: string, options?: RequestInit) => Promise<unknown>;

export function parseSourceWarehouseAuditStatus(input: unknown): SourceWarehouseAuditState {
  if (!input || typeof input !== "object") throw new Error("WAREHOUSE_STATUS_INVALID");
  const record = input as Partial<AuditStatusResponse>;
  if (record.status === "ACTIVE") {
    // Only the authoritative /warehouse/status endpoint can grant this result.
    if (record.stocktake_session_id !== null || record.stocktake_reference !== null ||
        record.stocktake_status !== null) {
      throw new Error("WAREHOUSE_STATUS_INVALID");
    }
    return { kind: "active" };
  }
  if (record.status === "AUDIT_LOCK" &&
      Number.isSafeInteger(record.stocktake_session_id) &&
      Number(record.stocktake_session_id) > 0 &&
      typeof record.stocktake_reference === "string" &&
      record.stocktake_reference.trim() &&
      typeof record.stocktake_status === "string" &&
      record.stocktake_status.trim()) {
    return {
      kind: "locked",
      sessionId: Number(record.stocktake_session_id),
      reference: record.stocktake_reference,
      stocktakeStatus: record.stocktake_status,
    };
  }
  throw new Error("WAREHOUSE_STATUS_INVALID");
}

export function useSourceWarehouseAuditStatus({
  warehouseId,
  actorKey,
  enabled,
  fetchStatus,
}: {
  warehouseId: string;
  actorKey: string | null;
  enabled: boolean;
  fetchStatus: FetchStatus;
}): { state: SourceWarehouseAuditState; retry: () => void } {
  const [current, setCurrent] = useState<{ key: string; state: SourceWarehouseAuditState } | null>(null);
  const [retryRevision, setRetryRevision] = useState(0);
  const key = useMemo(() =>
    enabled && actorKey && warehouseId ? JSON.stringify([actorKey, warehouseId]) : null,
  [enabled, actorKey, warehouseId]);

  useEffect(() => {
    if (!key) {
      setCurrent(null);
      return;
    }
    const controller = new AbortController();
    setCurrent({ key, state: { kind: "checking" } });
    void fetchStatus(`/warehouse/status?location_id=${encodeURIComponent(warehouseId)}`, {
      signal: controller.signal,
    }).then((value) => {
      if (!controller.signal.aborted) {
        setCurrent({ key, state: parseSourceWarehouseAuditStatus(value) });
      }
    }).catch(() => {
      // Missing/denied/failed status is NOT a proven stocktake lock and is
      // NEVER permission to launch a route. Keep both statements truthful.
      if (!controller.signal.aborted) setCurrent({ key, state: { kind: "unverified" } });
    });
    return () => controller.abort();
  }, [key, warehouseId, fetchStatus, retryRevision]);

  const retry = useCallback(() => setRetryRevision((revision) => revision + 1), []);
  return {
    state: !key ? { kind: "idle" } : current?.key === key ? current.state : { kind: "checking" },
    retry,
  };
}
