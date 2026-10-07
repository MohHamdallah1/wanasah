import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { useNetworkStatus } from "@/hooks/useNetworkStatus";
import { apiErrorCode, apiErrorMessage, isAmbiguousRequestError } from "@/lib/apiErrors";
import { abandonDurableOperation, completeDurableOperation, durableScope, getOrCreateDurableCommand,
  readDurableCommand, type DurableCommand } from "@/lib/durableOperations";
import { isConfirmedSupplierRejection, parseSupplier, supplierDraftKey } from "@/features/suppliers/contracts";

type Command = { endpoint: string; method: "POST" | "PUT" | "PATCH"; body: Record<string, unknown> };
export function useSupplierCommands(companyId: number | undefined, actorId: number | undefined) {
  const { t } = useTranslation();
  const authFetch = useAuthFetch();
  const online = useNetworkStatus();
  const cache = useQueryClient();
  const scope = companyId && actorId ? durableScope(companyId, actorId, "supplier-master-v1") : null;
  const [pending, setPending] = useState<DurableCommand<Command> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const running = useRef(false);
  useEffect(() => {
    let live = true;
    setPending(null);
    if (scope) void readDurableCommand<Command>(scope).then(value => { if (live) setPending(value); })
      .catch(err => { if (live) setError(apiErrorMessage(err, t("suppliers.pending"))); });
    return () => { live = false; };
  }, [scope, t]);
  const execute = async (command?: Command) => {
    if (!scope || !online || running.current) return false;
    running.current = true; setBusy(true); setError(null);
    let recovering = false;
    try {
      recovering = (await readDurableCommand(scope)) !== null;
      const durable = command ? await getOrCreateDurableCommand(scope, command) : await readDurableCommand<Command>(scope);
      if (!durable) return false;
      setPending(durable);
      parseSupplier(await authFetch(durable.payload.endpoint, {
        method: durable.payload.method, body: JSON.stringify({ ...durable.payload.body, request_id: durable.requestId }),
      }));
      completeDurableOperation(scope, durable.requestId); setPending(null);
      if (durable.payload.method !== "PATCH") {
        const target = durable.payload.method === "POST" ? "new" : durable.payload.endpoint.split("/").pop();
        localStorage.removeItem(supplierDraftKey(companyId, actorId, target));
      }
      await cache.invalidateQueries({ queryKey: ["suppliers"] });
      await cache.invalidateQueries({ queryKey: ["supplier-selection"] });
      return true;
    } catch (err) {
      const code = apiErrorCode(err);
      const ambiguous = recovering || isAmbiguousRequestError(err) || ["DURABLE_OPERATION_PENDING", "DURABLE_OPERATION_CORRUPT", "SUPPLIER_RESPONSE_INVALID"].includes(code ?? "");
      if (!ambiguous || (isConfirmedSupplierRejection(code) && !isAmbiguousRequestError(err))) { abandonDurableOperation(scope); setPending(null); }
      setError(apiErrorMessage(err, t(ambiguous ? "suppliers.pending" : "suppliers.saveFailed")));
      return false;
    } finally { running.current = false; setBusy(false); }
  };
  return { execute, pending, error, busy, online };
}
