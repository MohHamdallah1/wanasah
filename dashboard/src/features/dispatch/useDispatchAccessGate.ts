import { useCallback, useEffect, useMemo, useState } from "react";
import type { useInventoryAccess } from "@/hooks/useInventoryAccess";
import { dispatchPrivileges } from "./dispatchAccess";

type AccessQuery = ReturnType<typeof useInventoryAccess>;
export type DispatchGateStatus = "loading" | "ready" | "denied" | "error";

const deniedHttp = (error: unknown) => {
  const status = (error as { status?: unknown } | null)?.status;
  return status === 401 || status === 403;
};

/** An HTTP 403 fences previously displayed rows immediately, before refetch resolves. */
export function useDispatchAccessGate(access: AccessQuery) {
  const [deniedAtVersion, setDeniedAtVersion] = useState<number | null>(null);
  const { dataUpdatedAt } = access;

  useEffect(() => {
    const onDenied = () => setDeniedAtVersion(dataUpdatedAt);
    window.addEventListener("inventory-permission-denied", onDenied);
    return () => window.removeEventListener("inventory-permission-denied", onDenied);
  }, [dataUpdatedAt]);

  const revoked = deniedAtVersion !== null && deniedAtVersion === dataUpdatedAt;
  // A permission refetch in flight is NOT an authorization grant.
  const trusted = Boolean(access.data && !access.isError && !access.isFetching && !revoked);
  const grants = useMemo(() => dispatchPrivileges(trusted ? access.data : undefined), [trusted, access.data]);
  const allowed = grants.routes || grants.shortages;

  let state: DispatchGateStatus = "ready";
  if (revoked || (trusted && !allowed) || (access.isError && deniedHttp(access.error))) {
    state = "denied";
  } else if (access.isError) {
    state = "error";
  } else if (!trusted) {
    state = "loading";
  }
  const retry = useCallback(() => { void access.refetch(); }, [access.refetch]);
  return { state, grants, retry };
}
