import { useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { useAuthFetch } from "@/hooks/useAuthFetch";
import { useInventoryAccess } from "@/hooks/useInventoryAccess";
import { useNetworkStatus } from "@/hooks/useNetworkStatus";
import { apiErrorCode, apiErrorMessage, isAmbiguousRequestError } from "@/lib/apiErrors";
import { abandonDurableOperation, completeDurableOperation, durableScope, getOrCreateDurableCommand } from "@/lib/durableOperations";
import type { Quantity } from "@/lib/quantity";
import { parseBatchTerminalActionResult } from "./batchTerminalActionContract";
import type { BatchActionSnapshot } from "./contracts";
import type { BatchStockStatus, BatchTerminalAction } from "./batchStockSourcesContract";

type TerminalCommand = {
  action: BatchTerminalAction;
  sourceLocationId: number;
  sourceStatus: BatchStockStatus;
  quantity: Quantity;
  reason?: string;
  method?: string;
  evidenceReference?: string;
  vendorName?: string;
  vendorReference?: string;
  handoverReference?: string;
};

export function useBatchTerminalAction({ batch, productVariantId, baseUomCode, onSucceeded }: {
  batch: BatchActionSnapshot;
  productVariantId: number;
  baseUomCode: string;
  onSucceeded: () => void | Promise<void>;
}) {
  const { t } = useTranslation();
  const authFetch = useAuthFetch();
  const access = useInventoryAccess();
  const isOnline = useNetworkStatus();
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const companyId = access.data?.company_id ?? null;
  const driverId = access.data?.driver_id ?? null;

  const run = async (command: TerminalCommand) => {
    if (!isOnline || companyId === null || driverId === null || busyKey !== null) return false;
    const key = [batch.batch_id, command.sourceLocationId, command.sourceStatus, command.action].join(":");
    const scope = durableScope(companyId, driverId, "batch-terminal-quality-v1", key);
    const common = {
      source_location_id: command.sourceLocationId,
      product_variant_id: productVariantId,
      batch_id: batch.batch_id,
      quantity: command.quantity,
    };
    const payload = command.action === "CONFIRM_DISPOSAL"
      ? { ...common, reason: command.reason?.trim(), method: command.method?.trim() || null, evidence_reference: command.evidenceReference?.trim() || null }
      : { ...common, source_status: command.sourceStatus, vendor_name: command.vendorName?.trim(), vendor_reference: command.vendorReference?.trim(), handover_reference: command.handoverReference?.trim() };
    const endpoint = command.action === "CONFIRM_DISPOSAL"
      ? "/warehouse/quality/disposal/confirm"
      : "/warehouse/quality/vendor-return/confirm";
    setBusyKey(key);
    try {
      const durable = await getOrCreateDurableCommand(scope, payload);
      const result = parseBatchTerminalActionResult(command.action, await authFetch(endpoint, {
        method: "POST",
        body: JSON.stringify({ request_id: durable.requestId, ...durable.payload }),
      }));
      completeDurableOperation(scope, durable.requestId);
      toast.success(t(`terminalQualityActions.success.${command.action}`, {
        quantity: result.completed_quantity,
        unit: baseUomCode,
      }));
      await onSucceeded();
      return result;
    } catch (error) {
      const code = apiErrorCode(error);
      const ambiguous = isAmbiguousRequestError(error) ||
        code === "BATCH_TERMINAL_ACTION_RESPONSE_INVALID" || code === "DURABLE_OPERATION_PENDING";
      if (!ambiguous) abandonDurableOperation(scope);
      toast.error(apiErrorMessage(error, ambiguous
        ? t("terminalQualityActions.pending")
        : t("terminalQualityActions.errors.submit")));
      return false;
    } finally { setBusyKey(null); }
  };

  return { run, busyKey, isOnline };
}
