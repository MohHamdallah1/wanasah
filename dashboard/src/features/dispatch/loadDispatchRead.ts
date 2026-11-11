import type { DispatchPrivileges } from "./dispatchAccess";
import type { TabId } from "@/types/dispatch";

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
  fetch, grants, signal, isCurrent, onData, onError, tab, onPart, onReady,
}: {
  fetch: AuthRead;
  grants: DispatchPrivileges;
  signal: AbortSignal;
  isCurrent: () => boolean;
  onData: (data: DispatchReadResult) => void;
  onError: (reason: unknown) => void;
  /** Optional progressive read for the live Dispatch board. Legacy atomic
   * callers keep their original contract and regression tests unchanged. */
  tab?: TabId;
  onPart?: (kind: keyof DispatchReadResult, value: unknown) => void;
  onReady?: () => void;
}): Promise<void> {
  const options: RequestInit = { signal, cache: "no-store" };
  if (!grants.routes && !grants.shortages) return;
  if (tab) {
    // Routes are independent of Shops. Launch needs /init; Zones need /init
    // and scoped Shops. Shortages are an independent permitted reader.
    // All reads stay under the same signed, abortable read fence.
    const wanted: Array<[keyof DispatchReadResult, string]> = [];
    if (grants.routes) {
      wanted.push(["init", "/dispatch/init"]);
      if (tab === "routes") wanted.push(["routes", "/dispatch/active_routes"]);
      if (tab === "zones") wanted.push(["shops", "/dispatch/shops"]);
    }
    if (grants.shortages) wanted.push(["shortages", "/dispatch/shortages"]);
    const primary: (keyof DispatchReadResult)[] = !grants.routes
      ? ["shortages"] : tab === "routes" ? ["routes"]
        : tab === "launch" ? ["init"] : ["init", "shops"];
    let failed = false;
    const requests = new Map(wanted.map(([kind, url]) =>
      [kind, fetch(url, options).then(value => {
        if (!failed && isCurrent()) onPart?.(kind, value);
      }).catch(reason => {
        if (!failed && isCurrent()) {
          failed = true;
          onError(reason); // late 401/403 revokes even after primary paint
        }
        throw reason;
      })] as const));
    // Do not await unrelated Shops to paint active Routes, and do not block
    // Launch on Shops or Routes. Remaining requests still enforce errors.
    void Promise.all(primary.map(kind => requests.get(kind) ?? Promise.resolve()))
      .then(() => { if (!failed && isCurrent()) onReady?.(); })
      .catch(() => undefined);
    await Promise.allSettled([...requests.values()]);
    return;
  }

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
