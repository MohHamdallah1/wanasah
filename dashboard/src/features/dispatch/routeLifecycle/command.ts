import { apiErrorStatus } from "@/lib/apiErrors";
import {
  completeDurableOperation, durableScope, getOrCreateDurableCommand,
  readDurableCommand,
} from "@/lib/durableOperations";
import {
  parseLifecycleReceipt, type RouteLifecycleIntent, type RouteLifecycleReceipt,
} from "./contract";

type AuthorizedFetch = (path: string, init?: RequestInit) => Promise<unknown>;

export type RouteLifecycleOutcome =
  | { kind: "committed"; receipt: RouteLifecycleReceipt }
  | { kind: "unknown" | "denied" | "conflict" | "busy"; requestId?: string };

const actorIdentity = (actorScope: string): { companyId: number; principalId: number } => {
  const pieces = actorScope.split(":");
  if (pieces.length !== 3 || pieces.some(p => !/^[1-9]\d*$/.test(p) ||
      !Number.isSafeInteger(Number(p)))) throw new Error("M05_ACTOR_SCOPE_INVALID");
  return { companyId: Number(pieces[0]), principalId: Number(pieces[1]) };
};

const scopeFor = (actorScope: string, routeId: number) => {
  if (!Number.isSafeInteger(routeId) || routeId <= 0) throw new Error("M05_ROUTE_INVALID");
  const actor = actorIdentity(actorScope);
  return durableScope(actor.companyId, actor.principalId,
    "dispatch-route-lifecycle-m05", routeId);
};

/** All retries keep the original UUID and immutable route+epoch intent.
 * The Backend owns both success authority and execution uniqueness. A 409 is
 * NEVER converted to success by observing a changed route list.
 */
export async function dispatchRouteLifecycle({
  actorScope, routeId, intent, fetch, authorized,
}: {
  actorScope: string;
  routeId: number;
  intent?: RouteLifecycleIntent;
  fetch: AuthorizedFetch;
  authorized: () => boolean;
}): Promise<RouteLifecycleOutcome> {
  if (!authorized()) return { kind: "denied" };
  const scope = scopeFor(actorScope, routeId);
  const key = "wanasah:dispatch:lifecycle:lock:" + actorScope + ":" + routeId;
  if (typeof navigator === "undefined" || !navigator.locks?.request) {
    return { kind: "busy" }; // no unsafe cross-tab fallback
  }
  return navigator.locks.request(key, { mode: "exclusive", ifAvailable: true }, async lock => {
    if (!lock) return { kind: "busy" } as RouteLifecycleOutcome;
    if (!authorized()) return { kind: "denied" };
    // Retry after a lost response invokes this function with NO new intent.
    const previous = await readDurableCommand<RouteLifecycleIntent>(scope);
    if (!previous && !intent) return { kind: "conflict" };
    const original = intent
      ? await getOrCreateDurableCommand(scope, intent)
      : previous!;
    if (!authorized()) return { kind: "denied", requestId: original.requestId };
    try {
      const raw = await fetch(`/dispatch/route/${routeId}/lifecycle`, {
        method: "PUT",
        cache: "no-store",
        body: JSON.stringify({ ...original.payload, request_id: original.requestId }),
      });
      if (!authorized()) return { kind: "denied", requestId: original.requestId };
      const receipt = parseLifecycleReceipt(raw, routeId, original.payload.action, original.requestId);
      completeDurableOperation(scope, original.requestId);
      return { kind: "committed", receipt };
    } catch (error) {
      const status = apiErrorStatus(error);
      if (status === 401 || status === 403 || !authorized()) {
        return { kind: "denied", requestId: original.requestId };
      }
      if (status === 409 || status === 422) {
        return { kind: "conflict", requestId: original.requestId };
      }
      // Unknown outcome intentionally remains durable. Explicit Retry posts
      // exactly the original command, even after logout, navigation, refresh.
      return { kind: "unknown", requestId: original.requestId };
    }
  });
}

export const hasPendingRouteLifecycle = async (actorScope: string, routeId: number) =>
  (await readDurableCommand<RouteLifecycleIntent>(scopeFor(actorScope, routeId))) !== null;
