import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { apiErrorStatus } from "@/lib/apiErrors";
import { isDashboardSessionCurrent, type DashboardSession } from "@/lib/authStorage";
import {
  completeDurableOperation, getOrCreateDurableCommand, hashPayload,
  readDurableCommand, type DurableCommand,
} from "@/lib/durableOperations";
import {
  isOriginalRouteUuid, isRouteLaunchIntent, originalRouteReceipt,
  routeLaunchActorMatchesSession,
  routeLaunchIntent, routeLaunchReadback, routeLaunchScopeKey, routeLaunchText,
  type RouteLaunchActor, type RouteLaunchIntent, type RouteLaunchOutcome,
} from "./contract";

type AuthFetch = (path: string, opts?: RequestInit) => Promise<unknown>;
type Stored = DurableCommand<RouteLaunchIntent>;
type Inputs = {
  actor: RouteLaunchActor;
  authorized: () => boolean;
  current: () => boolean;
  fetch: AuthFetch;
};
const unknown = (requestId?: string): RouteLaunchOutcome => ({ kind: "unknown", requestId });
const denied = (error: unknown): boolean => [401, 403].includes(apiErrorStatus(error) ?? 0);
const sameId = (a: RouteLaunchIntent, b: RouteLaunchIntent) =>
  hashPayload(a).then(first => hashPayload(b).then(second => first === second));

/** One independently testable D07 command boundary; React is merely its adapter.
 * A persisted UUID + business payload survives lost 201, navigation, reload and
 * same-actor login. Authorization is ALWAYS rechecked by genuine Backend GET.
 */
export function createRouteLaunchRecovery({ actor, authorized, current, fetch }: Inputs) {
  const scope = routeLaunchScopeKey(actor);
  let disposed = false;
  let writing = false;
  let revoked = false;
  let verifiedId: string | null = null;
  let epoch = 0;
  const controllers = new Set<AbortController>();
  const live = (captured: number): boolean => !disposed && epoch === captured && current();
  const isAllowed = (token: number) => live(token) && !revoked && authorized();
  const cancelled = (token: number): RouteLaunchOutcome =>
    live(token) ? { kind: "blocked" } : { kind: "stale" };
  const checkAccess = (token: number): RouteLaunchOutcome | null =>
    !live(token) ? { kind: "stale" } : !isAllowed(token) ? { kind: "blocked" } : null;

  const call = async (path: string, opts: RequestInit, token: number): Promise<unknown> => {
    if (!isAllowed(token)) throw Object.assign(new Error("D07_ACCESS_NOT_CURRENT"), { status: 403 });
    const controller = new AbortController();
    controllers.add(controller);
    try {
      const response = await fetch(path, { ...opts, signal: controller.signal });
      if (!isAllowed(token)) throw Object.assign(new Error("D07_ACCESS_NOT_CURRENT"), { status: 403 });
      return response;
    } finally {
      controllers.delete(controller);
    }
  };

  const requireOriginal = async (): Promise<Stored | null> => {
    const command = await readDurableCommand<RouteLaunchIntent>(scope);
    if (command && (!isOriginalRouteUuid(command.requestId) ||
      !isRouteLaunchIntent(command.payload, actor))) throw new Error("D07_CORRUPT_OR_FOREIGN_COMMAND");
    return command;
  };

  const readback = async (command: Stored, token: number): Promise<RouteLaunchOutcome> => {
    try {
      const raw = await call(
        `/dispatch/route/create-operations/${command.requestId}`,
        { method: "GET", cache: "no-store" }, token,
      );
      if (!live(token)) return { kind: "stale" };
      const receipt = routeLaunchReadback(raw, command.requestId);
      if (receipt) {
        verifiedId = command.requestId;
        return { kind: "committed", requestId: command.requestId, receipt };
      }
      return unknown(command.requestId); // UNKNOWN, invalid JSON or wrong operation are NOT success.
    } catch (error) {
      if (!live(token)) return { kind: "stale" };
      if (denied(error)) { revoked = true; return { kind: "blocked" }; }
      return unknown(command.requestId);
    }
  };

  const postOriginal = async (command: Stored, token: number): Promise<RouteLaunchOutcome> => {
    try {
      const body = JSON.stringify({ ...command.payload, request_id: command.requestId });
      const raw = await call("/dispatch/route", { method: "POST", body }, token);
      if (!live(token)) return { kind: "stale" };
      const receipt = originalRouteReceipt(raw, command.requestId);
      if (receipt) {
        verifiedId = command.requestId;
        return { kind: "committed", requestId: command.requestId, receipt };
      }
      return unknown(command.requestId);
    } catch (error) {
      if (!live(token)) return { kind: "stale" };
      if (denied(error)) { revoked = true; return { kind: "blocked" }; }
      if (apiErrorStatus(error) === 409) return { kind: "conflict", requestId: command.requestId };
      // This POST may already have COMMITTED. GET the ORIGINAL UUID only;
      // never fetch active_routes as counterfeit proof or create a new UUID.
      return readback(command, token);
    }
  };

  const perform = async (
    kind: "launch" | "recover" | "retry", supplied?: RouteLaunchIntent,
  ): Promise<RouteLaunchOutcome> => {
    const token = epoch;
    const failed = checkAccess(token);
    if (failed) return failed;
    // Cross-tab lock is mandatory: refusing an operation is safer than two
    // tabs inventing different UUIDs for the same route intent.
    if (writing || typeof navigator === "undefined" || !navigator.locks?.request) {
      return { kind: "busy" };
    }
    writing = true;
    try {
      return await navigator.locks.request(
        `${scope}:exclusive-d07-launch`,
        { mode: "exclusive", ifAvailable: true },
        async (lock): Promise<RouteLaunchOutcome> => {
          if (!lock) return { kind: "busy" } satisfies RouteLaunchOutcome;
          if (checkAccess(token)) return cancelled(token);
          let existing: Stored | null;
          try {
            existing = await requireOriginal();
          } catch {
            return { kind: "blocked" }; // corrupted records never get overwritten
          }
          if (checkAccess(token)) return cancelled(token);
          if (kind === "launch") {
            if (!supplied) return { kind: "blocked" };
            let normalized: RouteLaunchIntent;
            try {
              normalized = routeLaunchIntent(supplied);
              if (normalized.source_location_id !== actor.warehouseId ||
                  normalized.vehicle_id !== actor.vehicleId) return { kind: "blocked" };
            } catch {
              return { kind: "blocked" };
            }
            if (existing) {
              if (!(await sameId(existing.payload, normalized))) {
                return { kind: "conflict", requestId: existing.requestId };
              }
              if (checkAccess(token)) return cancelled(token);
              // A second click / refresh NEVER posts while prior outcome is uncertain.
              return readback(existing, token);
            }
            try {
              existing = await getOrCreateDurableCommand(scope, normalized);
              if (!isOriginalRouteUuid(existing.requestId) ||
                  !isRouteLaunchIntent(existing.payload, actor)) {
                return { kind: "blocked" };
              }
            } catch {
              return { kind: "blocked" }; // no POST without safe durable persistence
            }
            if (checkAccess(token)) return cancelled(token);
            return postOriginal(existing, token);
          }
          if (!existing) return { kind: "idle" };
          const result = await readback(existing, token);
          if (result.kind !== "unknown" || kind === "recover") return result;
          if (checkAccess(token)) return cancelled(token);
          // Explicit user Retry, only after GET UNKNOWN. Exact original UUID
          // and immutable persisted payload are sent; server remains authority.
          return postOriginal(existing, token);
        },
      );
    } catch {
      return live(token) ? { kind: "blocked" } : { kind: "stale" };
    } finally {
      writing = false;
    }
  };

  return {
    launch: (intent: RouteLaunchIntent) => perform("launch", intent),
    recover: () => perform("recover"),
    retryOriginal: () => perform("retry"),
    readPending: () => isAllowed(epoch) ? requireOriginal() : Promise.resolve(null),
    acknowledge: (requestId: string): boolean => {
      if (!current() || disposed || revoked || !authorized() ||
          verifiedId !== requestId || !isOriginalRouteUuid(requestId)) return false;
      try {
        completeDurableOperation(scope, requestId);
        verifiedId = null;
        return true;
      } catch { return false; }
    },
    dispose: () => {
      disposed = true;
      epoch++;
      for (const controller of controllers) controller.abort();
      controllers.clear();
    },
  };
}

export type UseRouteLaunchRecoveryOptions = {
  actor: RouteLaunchActor | null;
  session: DashboardSession;
  authorized: boolean;
  language: string;
  fetch: AuthFetch;
  onCommitted?: (receipt: Extract<RouteLaunchOutcome, { kind: "committed" }>["receipt"]) => void;
};

/** Mountable by DispatchBoard AFTER D10 merge. No Board or D10 module imports.
 * Same actor may restore the durable UUID on a fresh login, but stale
 * responses from old principals/permissions are never admitted.
 */
export function useRouteLaunchRecovery({
  actor, session, authorized, language, fetch, onCommitted,
}: UseRouteLaunchRecoveryOptions) {
  const [result, setResult] = useState<RouteLaunchOutcome>({ kind: "idle" });
  const [busy, setBusy] = useState(false);
  const latest = useRef({ authorized, onCommitted, fetch });
  latest.current = { authorized, onCommitted, fetch };
  const key = actor && routeLaunchActorMatchesSession(actor, session.identity)
    ? (() => { try { return routeLaunchScopeKey(actor); } catch { return null; } })() : null;
  const controller = useMemo(() => {
    if (!actor || !key) return null;
    return createRouteLaunchRecovery({
      actor,
      current: () => isDashboardSessionCurrent(session),
      authorized: () => latest.current.authorized,
      fetch: (path, options) => latest.current.fetch(path, options),
    });
    // Deliberately reset only on verified actor/scope/login generation.
  }, [key, session.generation, session.identity, authorized]);
  useEffect(() => {
    setResult({ kind: authorized && key ? "idle" : "blocked" });
    setBusy(false);
    if (!controller || !authorized || !key) return () => { controller?.dispose(); };
    let active = true;
    void controller.recover().then(answer => {
      if (!active || !isDashboardSessionCurrent(session) || !latest.current.authorized) return;
      setResult(answer);
      if (answer.kind === "committed") latest.current.onCommitted?.(answer.receipt);
    });
    return () => { active = false; controller.dispose(); };
  }, [controller, authorized, session, key]);

  const run = useCallback(async (operation: "launch" | "recover" | "retry", intent?: RouteLaunchIntent) => {
    if (!controller || !latest.current.authorized || busy) return { kind: "blocked" } as RouteLaunchOutcome;
    setBusy(true);
    try {
      const answer = operation === "launch" && intent ? await controller.launch(intent)
        : operation === "retry" ? await controller.retryOriginal() : await controller.recover();
      if (answer.kind !== "stale" && isDashboardSessionCurrent(session) && latest.current.authorized) {
        setResult(answer);
        if (answer.kind === "committed") latest.current.onCommitted?.(answer.receipt);
      }
      return answer;
    } finally {
      if (isDashboardSessionCurrent(session)) setBusy(false);
    }
  }, [controller, busy, session]);

  return {
    launch: (intent: RouteLaunchIntent) => run("launch", intent),
    recover: () => run("recover"),
    retryOriginal: () => run("retry"),
    acknowledge: (id: string) => {
      if (result.kind !== "committed" || result.requestId !== id) return false;
      const done = controller?.acknowledge(id) ?? false;
      if (done) setResult({ kind: "idle" });
      return done;
    },
    result: authorized && key ? result : ({ kind: "blocked" } as RouteLaunchOutcome),
    message: routeLaunchText(language, authorized && key ? result.kind : "blocked"),
    busy,
    hasUnresolved: result.kind === "unknown" || result.kind === "conflict" || result.kind === "committed",
  };
}
