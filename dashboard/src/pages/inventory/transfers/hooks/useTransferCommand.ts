import { useCallback, useEffect, useRef, useState } from "react";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { apiErrorStatus, isAmbiguousRequestError } from "@/lib/apiErrors";
import { completeDurableOperation, durableScope, getOrCreateDurableCommand, readDurableCommand, type DurableCommand } from "@/lib/durableOperations";

export type TransferWireCommand = { path: string; method: "POST" | "PUT"; body: Record<string, unknown> };
export function transferCommandScope(operation: string, target: string | number) {
  const company = Number(localStorage.getItem("company_id"));
  const principal = Number(localStorage.getItem("principal_id"));
  if (!Number.isSafeInteger(company) || company <= 0 || !Number.isSafeInteger(principal) || principal <= 0) {
    throw Object.assign(new Error(), { code: "INVENTORY_ACCESS_SCOPE_MISMATCH" });
  }
  // Storage partitions drafts only; backend authorization remains mandatory.
  return durableScope(company, principal, operation, target);
}
export function useTransferCommand(operation: string, target: string | number) {
  const authFetch = useAuthFetch();
  const [pending, setPending] = useState<DurableCommand<TransferWireCommand> | null>(null);
  const [busy, setBusy] = useState(false);
  const [recoveryError, setRecoveryError] = useState<unknown>(null);
  const scope = (() => { try { return transferCommandScope(operation, target); } catch { return null; } })();
  const scopeRef = useRef(scope);
  scopeRef.current = scope;
  const active = useRef(new Set<string>());
  useEffect(() => {
    let current = true;
    setPending(null);
    setBusy(false);
    setRecoveryError(null);
    if (scope) void readDurableCommand<TransferWireCommand>(scope).then(
      command => { if (current) setPending(command); },
      error => { if (current) setRecoveryError(error); },
    );
    return () => { current = false; };
  }, [scope]);

  const execute = useCallback(async (wire?: TransferWireCommand, validate?: (raw: unknown) => unknown) => {
    if (scope && active.current.has(scope)) return undefined;
    if (!scope || recoveryError) throw recoveryError ?? Object.assign(new Error(), { code: "INVENTORY_ACCESS_SCOPE_MISMATCH" });
    active.current.add(scope);
    setBusy(true);
    let command: DurableCommand<TransferWireCommand> | null = null;
    try {
      command = wire ? await getOrCreateDurableCommand(scope, wire) : await readDurableCommand<TransferWireCommand>(scope);
      if (!command) return undefined;
      if (scopeRef.current === scope) setPending(command);
      const raw = await authFetch(command.payload.path, {
        method: command.payload.method,
        body: JSON.stringify({ ...command.payload.body, request_id: command.requestId }),
      });
      validate?.(raw);
      completeDurableOperation(scope, command.requestId);
      if (scopeRef.current === scope) setPending(null);
      return raw;
    } catch (error) {
      const status = apiErrorStatus(error);
      // A deterministic rejection confirms rollback. Transport/5xx/invalid
      // responses stay pending until explicit replay; there is no auto-send.
      if (command && status && status >= 400 && status < 500 && !isAmbiguousRequestError(error)) {
        completeDurableOperation(scope, command.requestId);
        if (scopeRef.current === scope) setPending(null);
      }
      throw error;
    } finally {
      active.current.delete(scope);
      if (scopeRef.current === scope) setBusy(false);
    }
  }, [authFetch, scope, recoveryError]);
  return { pending, busy, recoveryError, execute };
}
