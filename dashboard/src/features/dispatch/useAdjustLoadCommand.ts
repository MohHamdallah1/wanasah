import { useEffect, useRef, useState } from "react";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { useNetworkStatus } from "@/hooks/useNetworkStatus";
import { apiErrorStatus, isAmbiguousRequestError } from "@/lib/apiErrors";
import { completeDurableOperation, durableScope, getOrCreateDurableCommand, readDurableCommand, type DurableCommand } from "@/lib/durableOperations";
import type { AdjustLoadPayload } from "./adjustLoad";

export function useAdjustLoadCommand(routeId: string | undefined, companyId?: number, principalId?: number) {
  const authFetch = useAuthFetch();
  const online = useNetworkStatus();
  const scope = routeId && Number.isSafeInteger(companyId) && companyId > 0 &&
    Number.isSafeInteger(principalId) && principalId > 0
    ? durableScope(companyId, principalId, "dispatch-adjust-base", routeId) : null;
  const [pending, setPending] = useState<DurableCommand<AdjustLoadPayload> | null>(null);
  const [recoveryError, setRecoveryError] = useState<unknown>(null);
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [recoveryRequired, setRecoveryRequired] = useState(false);
  const active = useRef(new Set<string>());
  const scopeRef = useRef(scope);
  scopeRef.current = scope;
  useEffect(() => {
    let live = true;
    setReady(false); setPending(null); setRecoveryError(null); setBusy(false); setRecoveryRequired(false);
    if (!scope) return;
    void readDurableCommand<AdjustLoadPayload>(scope).then((command) => {
      if (live) { setPending(command); setRecoveryRequired(!!command); setReady(true); }
    }).catch((error) => { if (live) setRecoveryError(error); });
    return () => { live = false; };
  }, [scope]);

  const execute = async (payload?: AdjustLoadPayload) => {
    if (!scope || !ready || recoveryError || !online) throw Object.assign(new Error(), { code: "NETWORK_UNAVAILABLE" });
    if (active.current.has(scope)) return null;
    active.current.add(scope); setBusy(true);
    let command: DurableCommand<AdjustLoadPayload> | null = null;
    try {
      command = payload ? await getOrCreateDurableCommand(scope, payload) : await readDurableCommand<AdjustLoadPayload>(scope);
      if (!command) return null;
      if (scopeRef.current === scope) setPending(command);
      const result = await authFetch(`/dispatch/route/${routeId}/adjust_inventory`, {
        method: "PUT", body: JSON.stringify({ request_id: command.requestId, ...command.payload }),
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
      if (command && status >= 400 && status < 500 && !isAmbiguousRequestError(error)) {
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
  return { scope, pending, ready, busy, recoveryRequired, recoveryError, online, execute };
}
