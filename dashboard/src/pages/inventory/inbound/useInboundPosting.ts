import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNetworkStatus } from "@/hooks/useNetworkStatus";
import { apiErrorCode, isAmbiguousRequestError } from "@/lib/apiErrors";
import { abandonDurableOperation, completeDurableOperation, durableScope,
  getOrCreateDurableCommand, readDurableCommand, type DurableCommand } from "@/lib/durableOperations";
import { parseInboundResponse } from "./contracts";
import { isConfirmedSupplierRejection } from "@/features/suppliers/contracts";

const isConfirmedInboundRejection = (code: string | undefined) =>
  code === "INBOUND_WAREHOUSE_AUDIT_LOCKED" ||
  isConfirmedSupplierRejection(code);

export function useInboundPosting({ companyId, actorId, locationId, authenticatedFetch, legacyRequestKey, legacyPayloadKey }: {
  companyId: number; actorId: number; locationId: number;
  authenticatedFetch: (url: string, opts?: RequestInit) => Promise<unknown>;
  legacyRequestKey?: string; legacyPayloadKey?: string;
}) {
  const { t } = useTranslation();
  const online = useNetworkStatus();
  const scope = durableScope(companyId, actorId, "supplier-inbound-v1", locationId);
  const [pending, setPending] = useState<DurableCommand<Record<string, unknown>> | null>(null);
  const [recoveryRequired, setRecoveryRequired] = useState(false);
  const [recoveryError, setRecoveryError] = useState<string | null>(null);
  const running = useRef(false);
  const readLegacy = useCallback(() => {
    const requestId = legacyRequestKey ? localStorage.getItem(legacyRequestKey) : null;
    if (!requestId) return null;
    const raw = legacyPayloadKey ? localStorage.getItem(legacyPayloadKey) : null;
    let payload: unknown;
    try { payload = raw ? JSON.parse(raw) : null; }
    catch { throw Object.assign(new Error(), { code: "DURABLE_OPERATION_CORRUPT" }); }
    if (!/^[0-9a-f-]{36}$/i.test(requestId) || !payload || typeof payload !== "object"
      || Array.isArray(payload) || (payload as Record<string, unknown>).location_id !== locationId) {
      throw Object.assign(new Error(), { code: "DURABLE_OPERATION_CORRUPT" });
    }
    return { requestId, payload: payload as Record<string, unknown>, createdAt: 0 };
  }, [legacyRequestKey, legacyPayloadKey, locationId]);
  useEffect(() => {
    let live = true;
    setPending(null); setRecoveryRequired(false); setRecoveryError(null);
    void readDurableCommand<Record<string, unknown>>(scope).then(command => {
      if (!live) return;
      const recovered = command ?? readLegacy();
      setPending(recovered);
      setRecoveryRequired(recovered !== null);
    }).catch(() => {
      if (!live) return;
      setRecoveryRequired(true);
      setRecoveryError(t("suppliers.pending"));
    });
    return () => { live = false; };
  }, [scope, readLegacy, t]);
  const post = async (payload?: Record<string, unknown>) => {
    if (!online || running.current) throw Object.assign(new Error("NETWORK_UNAVAILABLE"), { code: "NETWORK_UNAVAILABLE" });
    running.current = true;
    let recovering = false;
    try {
      const previous = await readDurableCommand<Record<string, unknown>>(scope);
      const legacy = readLegacy();
      recovering = previous !== null || legacy !== null;
      if (payload && legacy) throw Object.assign(new Error(), { code: "DURABLE_OPERATION_PENDING" });
      const command = payload ? await getOrCreateDurableCommand(scope, payload) : previous ?? legacy;
      if (!command) return false;
      setPending(command);
      setRecoveryRequired(false);
      parseInboundResponse(await authenticatedFetch("/warehouse/inbound", {
        method: "POST", body: JSON.stringify({ request_id: command.requestId, ...command.payload }),
      }));
      completeDurableOperation(scope, command.requestId);
      setPending(null);
      setRecoveryRequired(false);
      if (legacyRequestKey && legacy?.requestId === command.requestId) {
        localStorage.removeItem(legacyRequestKey);
        if (legacyPayloadKey) localStorage.removeItem(legacyPayloadKey);
      }
      return true;
    } catch (error) {
      const abandon =
        (isConfirmedInboundRejection(apiErrorCode(error)) && !isAmbiguousRequestError(error)) ||
        (!recovering &&
          !isAmbiguousRequestError(error) &&
          !["DURABLE_OPERATION_PENDING", "DURABLE_OPERATION_CORRUPT", "INBOUND_RESPONSE_INVALID"].includes(apiErrorCode(error) ?? ""));
      if (abandon) {
        abandonDurableOperation(scope);
        setPending(null);
        setRecoveryRequired(false);
        if (legacyRequestKey) localStorage.removeItem(legacyRequestKey);
        if (legacyPayloadKey) localStorage.removeItem(legacyPayloadKey);
      } else {
        setRecoveryRequired(true);
      }
      throw error;
    } finally { running.current = false; }
  };
  return { post, pending, recoveryRequired, recoveryError, online };
}
