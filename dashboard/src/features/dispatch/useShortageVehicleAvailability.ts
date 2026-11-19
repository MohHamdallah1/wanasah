import { useEffect, useMemo, useRef, useState } from "react";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { useDashboardSession } from "@/hooks/useDashboardSession";
import { isDashboardSessionCurrent } from "@/lib/authStorage";

export type VehicleAvailabilityLine = {
  product_id: string;
  available_base: string;
  base_uom: string;
};
export type VehicleAvailabilityQuote =
  | { status: "UNKNOWN"; reason: string; items: [] }
  | {
    status: "VERIFIED";
    source: "CANONICAL_VEHICLE_CUSTODY";
    vehicle_id: number;
    vehicle_location_id: number;
    custody_epoch_id: number;
    stock_snapshot: string;
    items: VehicleAvailabilityLine[];
  };
type QuoteState = {
  key: string;
  quote: VehicleAvailabilityQuote | null;
  loading: boolean;
};

/** Read-only and actor-bound. An unknown or revoked read never becomes zero. */
export function useShortageVehicleAvailability({
  driverId, productIds, scope,
}: {
  driverId: string;
  productIds: readonly string[];
  scope: string | null;
}) {
  const authFetch = useAuthFetch();
  const authFetchRef = useRef(authFetch);
  authFetchRef.current = authFetch;
  const session = useDashboardSession();
  const sessionKey = session ? JSON.stringify(session) : "";
  const idsKey = [...new Set(productIds.filter(id => /^[1-9]\d*$/.test(id)))].sort(
    (a,b) => Number(a)-Number(b),
  ).slice(0,240).join(",");
  const key = `${sessionKey}:${scope ?? ""}:${driverId}:${idsKey}`;
  const [state, setState] = useState<QuoteState>({
    key: "", quote: null, loading: false,
  });
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    if (!scope || !session || !/^[1-9]\d*$/.test(driverId) || !idsKey) return;
    const controller = new AbortController();
    setState({ key, quote: null, loading: true });
    const params = new URLSearchParams({ driver_id: driverId });
    for (const id of idsKey.split(",")) params.append("product_ids", id);
    void authFetchRef.current(
      `/dispatch/shortages/vehicle-availability?${params}`,
      { signal: controller.signal },
    ).then((result: VehicleAvailabilityQuote) => {
      if (!controller.signal.aborted && isDashboardSessionCurrent(session)) {
        if (result && (result.status === "UNKNOWN" ||
            (result.status === "VERIFIED" && Array.isArray(result.items)))) {
          setState({ key, quote: result, loading: false });
        } else {
          setState({ key, quote: {status:"UNKNOWN",reason:"READ_INVALID",items:[]}, loading:false });
        }
      }
    }).catch(() => {
      // 401/403, timeout or missing custody must not expose another actor's cache.
      if (!controller.signal.aborted && isDashboardSessionCurrent(session)) {
        setState({key, quote:{status:"UNKNOWN",reason:"READ_FAILED",items:[]},loading:false});
      }
    });
    return () => controller.abort();
  }, [key, scope, session, sessionKey, driverId, idsKey, revision]);

  const current = state.key === key && session && isDashboardSessionCurrent(session)
    ? state.quote : null;
  const verified = current?.status === "VERIFIED";
  const byProduct = useMemo<Map<string,VehicleAvailabilityLine>>(() =>
    new Map<string,VehicleAvailabilityLine>(verified ? current.items.map(
      line => [line.product_id, line],
    ) : []), [current, verified]);
  return {
    status: verified ? "VERIFIED" as const : "UNKNOWN" as const,
    reason: current?.status === "UNKNOWN" ? current.reason : "NOT_VERIFIED",
    byProduct,
    loading: !!scope && !!session && !!driverId && !!idsKey &&
      (state.key !== key || state.loading),
    refresh: () => setRevision(n => n+1),
  };
}
