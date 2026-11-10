import type { DispatchPrivileges } from "./dispatchAccess";

type AuthRead = (url: string, init: RequestInit) => Promise<unknown>;

export type DispatchReadResult = {
  init: unknown | null;
  shops: unknown | null;
  routes: unknown | null;
  shortages: unknown | null;
};

/**
 * Refresh all permitted tables as ONE admitted response. No prior rows are
 * reused when a permission is lost or when one request returns 401/403.
 * The existing backend/RLS still authorizes each Bearer HTTP request.
 */
export async function loadDispatchRead({
  fetch, grants, signal, isCurrent, onData, onError,
}: {
  fetch: AuthRead;
  grants: DispatchPrivileges;
  signal: AbortSignal;
  isCurrent: () => boolean;
  onData: (data: DispatchReadResult) => void;
  onError: (reason: unknown) => void;
}): Promise<void> {
  const options: RequestInit = { signal, cache: "no-store" };
  if (!grants.routes && !grants.shortages) return;
  try {
    const [init, shops, routes, shortages] = await Promise.all([
      grants.routes ? fetch("/dispatch/init", options) : Promise.resolve(null),
      grants.routes ? fetch("/dispatch/shops", options) : Promise.resolve(null),
      grants.routes ? fetch("/dispatch/active_routes", options) : Promise.resolve(null),
      grants.shortages ? fetch("/dispatch/shortages", options) : Promise.resolve(null),
    ]);
    if (!isCurrent()) return;
    onData({ init, shops, routes, shortages });
  } catch (reason) {
    if (isCurrent()) onError(reason);
  }
}
