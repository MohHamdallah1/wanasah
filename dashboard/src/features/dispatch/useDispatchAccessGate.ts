import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
  // Like Inventory: first admit this mounted principal on a completed signed
  // read, then retain that exact actor's admitted view through ordinary
  // background refetch. A denied event/error or new mount still fails closed.
  const admittedActorRef = useRef<string | null>(null);
  const mustFreshlyRecoverRef = useRef(false);
  if (access.isError || revoked) mustFreshlyRecoverRef.current = true;
  const actor = access.data
    ? `${access.data.company_id}:${access.data.principal_id}:${access.data.backoffice_user_id}`
    : null;
  // A preexisting shared Query cache is not first-entry admission: require
  // one completed capability read observed by this mounted workspace.
  const fresh = Boolean(actor && access.data && access.isFetchedAfterMount !== false &&
    !access.isFetching && !access.isError && !revoked);
  if (fresh) {
    admittedActorRef.current = actor;
    mustFreshlyRecoverRef.current = false;
  }
  const trusted = Boolean(actor && access.data && !access.isError && !revoked &&
    !mustFreshlyRecoverRef.current &&
    (fresh || admittedActorRef.current === actor));
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
