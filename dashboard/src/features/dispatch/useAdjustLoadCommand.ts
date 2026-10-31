import { useEffect, useRef, useState } from "react";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { useNetworkStatus } from "@/hooks/useNetworkStatus";
import { apiErrorCode, apiErrorStatus, isAmbiguousRequestError } from "@/lib/apiErrors";
import { completeDurableOperation, durableScope, getOrCreateDurableCommand, readDurableCommand, type DurableCommand } from "@/lib/durableOperations";
import type { AdjustLoadCommandContext, AdjustLoadPayload } from "./adjustLoad";

type LegacyOutcome = "COMMITTED" | "NOT_CONFIRMED" | "INDETERMINATE" | "CANCELLED";

const contextError = () => Object.assign(new Error(), { code: "DISPATCH_ROUTE_CONTEXT_CHANGED" });
const positiveId = (value: unknown): number | null => {
  if (typeof value !== "string" || !/^[1-9][0-9]*$/.test(value)) return null;
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) ? parsed : null;
};
const parsePhysicalContext = (raw: string | undefined, routeId: string | undefined): AdjustLoadCommandContext | null => {
  if (!raw) return null;
  let value: unknown;
  try { value = JSON.parse(raw); } catch { throw contextError(); }
  if (!Array.isArray(value) || value.length !== 5 || value[0] !== routeId) throw contextError();
  const vehicleId = positiveId(value[1]);
  const warehouseId = positiveId(value[2]);
  const sessionId = value[3] === null ? null : positiveId(value[3]);
  const revision = value[4];
  if (vehicleId === null || warehouseId === null ||
      (value[3] !== null && sessionId === null) ||
      !Number.isSafeInteger(revision) || Number(revision) <= 0) throw contextError();
  return {
    version: "ADJUST_LOAD_CONTEXT_V2",
    vehicle_id: vehicleId,
    source_warehouse_id: warehouseId,
    work_session_id: sessionId,
    route_context_revision: Number(revision),
  };
};
const contextsEqual = (a: AdjustLoadCommandContext | undefined, b: AdjustLoadCommandContext | null) =>
  !!a && !!b && a.version === b.version && a.vehicle_id === b.vehicle_id &&
  a.source_warehouse_id === b.source_warehouse_id && a.work_session_id === b.work_session_id &&
  a.route_context_revision === b.route_context_revision;

export function useAdjustLoadCommand(routeId: string | undefined, companyId?: number, principalId?: number, physicalContext?: string) {
  const authFetch = useAuthFetch();
  const online = useNetworkStatus();
  const legacyScope = routeId && Number.isSafeInteger(companyId) && companyId > 0 &&
    Number.isSafeInteger(principalId) && principalId > 0
    ? durableScope(companyId, principalId, "dispatch-adjust-base", routeId) : null;
  const scope = legacyScope && physicalContext
    ? durableScope(companyId!, principalId!, "dispatch-adjust-base", `${routeId}:${physicalContext}`)
    : legacyScope;
  const [pending, setPending] = useState<DurableCommand<AdjustLoadPayload> | null>(null);
  const [legacyPending, setLegacyPending] = useState<DurableCommand<AdjustLoadPayload> | null>(null);
  const [legacyOutcome, setLegacyOutcome] = useState<LegacyOutcome | null>(null);
  const [checkingLegacy, setCheckingLegacy] = useState(false);
  const [cancellingLegacy, setCancellingLegacy] = useState(false);
  const [recoveryError, setRecoveryError] = useState<unknown>(null);
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [recoveryRequired, setRecoveryRequired] = useState(false);
  const active = useRef(new Set<string>());
  const scopeRef = useRef(scope);
  scopeRef.current = scope;

  useEffect(() => {
    let live = true;
    setReady(false); setPending(null); setLegacyPending(null); setLegacyOutcome(null);
    setRecoveryError(null); setBusy(false); setCheckingLegacy(false); setCancellingLegacy(false); setRecoveryRequired(false);
    if (!scope) return;
    void Promise.all([
      readDurableCommand<AdjustLoadPayload>(scope),
      legacyScope && legacyScope !== scope
        ? readDurableCommand<AdjustLoadPayload>(legacyScope)
        : Promise.resolve(null),
    ]).then(([command, legacyCommand]) => {
      if (!live) return;
      if (legacyCommand) {
        setLegacyPending(legacyCommand);
        setPending(command);
        setRecoveryError(Object.assign(new Error(), { code: "DISPATCH_LEGACY_RECOVERY_REQUIRED" }));
        setRecoveryRequired(true);
        setReady(false);
        return;
      }
      setPending(command); setRecoveryRequired(!!command); setReady(true);
    }).catch((error) => { if (live) setRecoveryError(error); });
    return () => { live = false; };
  }, [scope, legacyScope]);

  const execute = async (payload?: AdjustLoadPayload) => {
    if (!scope || !ready || recoveryError || !online) throw Object.assign(new Error(), { code: "NETWORK_UNAVAILABLE" });
    if (active.current.has(scope)) return null;
    active.current.add(scope); setBusy(true);
    let command: DurableCommand<AdjustLoadPayload> | null = null;
    try {
      const expectedContext = parsePhysicalContext(physicalContext, routeId);
      const durablePayload = payload && expectedContext ? { ...payload, context: expectedContext } : payload;
      command = durablePayload
        ? await getOrCreateDurableCommand(scope, durablePayload)
        : await readDurableCommand<AdjustLoadPayload>(scope);
      if (!command) return null;
      if (expectedContext && !contextsEqual(command.payload.context, expectedContext)) throw contextError();
      if (scopeRef.current === scope) setPending(command);
      const headers: Record<string, string> = {};
      if (command.payload.context) {
        headers["X-Dispatch-Expected-Vehicle-Id"] = String(command.payload.context.vehicle_id);
        headers["X-Dispatch-Expected-Source-Warehouse-Id"] = String(command.payload.context.source_warehouse_id);
      }
      const result = await authFetch(`/dispatch/route/${routeId}/adjust_inventory`, {
        method: "PUT", headers, body: JSON.stringify({ request_id: command.requestId, ...command.payload }),
      }) as { mode?: string };
      if (!result || !["DIRECT", "HANDSHAKE", "NO_CHANGE"].includes(result.mode ?? "")) {
        throw Object.assign(new Error(), { code: "DISPATCH_ADJUSTMENT_RESPONSE_INVALID" });
      }
      completeDurableOperation(scope, command.requestId);
      if (scopeRef.current !== scope) return null;
      setPending(null);
      setRecoveryRequired(false);
      return result.mode;
    } catch (error) {
      const status = apiErrorStatus(error);
      const preserveForensicIdentity = apiErrorCode(error) === "DISPATCH_ADJUSTMENT_INDETERMINATE";
      if (command && status >= 400 && status < 500 &&
          !isAmbiguousRequestError(error) && !preserveForensicIdentity) {
        completeDurableOperation(scope, command.requestId);
        if (scopeRef.current === scope) { setPending(null); setRecoveryRequired(false); }
      } else if (command && scopeRef.current === scope) {
        setPending(command); setRecoveryRequired(true);
      }
      throw error;
    } finally {
      active.current.delete(scope);
      if (scopeRef.current === scope) setBusy(false);
    }
  };

  const inspectLegacy = async () => {
    if (!routeId || !legacyPending || !legacyScope || !scope || checkingLegacy || cancellingLegacy || !online) return;
    const inspectingScope = scope;
    setCheckingLegacy(true);
    try {
      const result = await authFetch(`/dispatch/route/${routeId}/adjust_inventory/recovery`, {
        method: "POST",
        body: JSON.stringify({ request_id: legacyPending.requestId, ...legacyPending.payload }),
      }) as { state?: string; request_id?: string; response?: { mode?: string } };
      if (scopeRef.current !== inspectingScope) return;
      if (result.request_id !== legacyPending.requestId ||
          !["COMMITTED", "NOT_CONFIRMED", "INDETERMINATE", "CANCELLED"].includes(result.state ?? "") ||
          (result.state === "COMMITTED" && !["DIRECT", "HANDSHAKE", "NO_CHANGE"].includes(result.response?.mode ?? ""))) {
        throw Object.assign(new Error(), { code: "DISPATCH_RECOVERY_RESPONSE_INVALID" });
      }
      setLegacyOutcome(result.state as LegacyOutcome);
    } catch (error) {
      if (scopeRef.current === inspectingScope) {
        setLegacyOutcome(null);
        throw error;
      }
    } finally {
      if (scopeRef.current === inspectingScope) setCheckingLegacy(false);
    }
  };

  const cancelLegacy = async () => {
    if (!routeId || !legacyPending || !legacyScope || !scope || legacyOutcome !== "NOT_CONFIRMED" ||
        checkingLegacy || cancellingLegacy || !online) return;
    const cancellingScope = scope;
    setCancellingLegacy(true);
    try {
      const result = await authFetch(`/dispatch/route/${routeId}/adjust_inventory/recovery/cancel`, {
        method: "POST",
        body: JSON.stringify({ request_id: legacyPending.requestId, ...legacyPending.payload }),
      }) as { state?: string; request_id?: string; response?: { mode?: string } };
      if (scopeRef.current !== cancellingScope) return;
      if (result.request_id !== legacyPending.requestId ||
          !["COMMITTED", "CANCELLED"].includes(result.state ?? "") ||
          (result.state === "COMMITTED" && !["DIRECT", "HANDSHAKE", "NO_CHANGE"].includes(result.response?.mode ?? ""))) {
        throw Object.assign(new Error(), { code: "DISPATCH_RECOVERY_RESPONSE_INVALID" });
      }
      if (result.state === "COMMITTED") {
        setLegacyOutcome("COMMITTED");
        return "COMMITTED" as const;
      }
      // The explicit cancellation response is authoritative and persisted.
      completeDurableOperation(legacyScope, legacyPending.requestId);
      setLegacyPending(null);
      setLegacyOutcome(null);
      setRecoveryError(null);
      setRecoveryRequired(!!pending);
      setReady(true);
      return "CANCELLED" as const;
    } finally {
      if (scopeRef.current === cancellingScope) setCancellingLegacy(false);
    }
  };

  const acknowledgeCommittedLegacy = () => {
    if (legacyOutcome !== "COMMITTED" || !legacyPending || !legacyScope || !scope ||
        checkingLegacy || cancellingLegacy) return;
    completeDurableOperation(legacyScope, legacyPending.requestId);
    setLegacyPending(null);
    setLegacyOutcome(null);
    setRecoveryError(null);
    setRecoveryRequired(!!pending);
    setReady(true);
  };
  const acknowledgeCancelledLegacy = () => {
    if (legacyOutcome !== "CANCELLED" || !legacyPending || !legacyScope || !scope ||
        checkingLegacy || cancellingLegacy) return;
    completeDurableOperation(legacyScope, legacyPending.requestId);
    setLegacyPending(null);
    setLegacyOutcome(null);
    setRecoveryError(null);
    setRecoveryRequired(!!pending);
    setReady(true);
  };

  return {
    scope, pending, legacyPending, legacyOutcome, checkingLegacy, cancellingLegacy,
    inspectLegacy, cancelLegacy, acknowledgeCommittedLegacy, acknowledgeCancelledLegacy,
    ready, busy, recoveryRequired, recoveryError, online, execute,
  };
}
