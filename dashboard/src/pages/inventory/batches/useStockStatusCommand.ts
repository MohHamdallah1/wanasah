import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { useAuthFetch } from "@/hooks/useAuthFetch";
import { useInventoryAccess } from "@/hooks/useInventoryAccess";
import { useNetworkStatus } from "@/hooks/useNetworkStatus";
import {
  apiErrorCode,
  apiErrorMessage,
  isAmbiguousRequestError,
} from "@/lib/apiErrors";
import {
  abandonDurableOperation,
  completeDurableOperation,
  durableScope,
  getOrCreateDurableCommand,
  readDurableCommand,
  type DurableCommand,
} from "@/lib/durableOperations";
import {
  compareQuantity,
  validateVariantQuantity,
  type Quantity,
} from "@/lib/quantity";

import {
  parseInventoryStatusChangeResponse,
  type StatusChangeDestination,
} from "./batchActionContracts";
import { batchActionText } from "./batchActionsI18n";
import type { BatchStockStatus } from "./batchStockSourcesContract";

type StockStatusCommand = {
  location_id: number;
  product_variant_id: number;
  batch_id: number;
  uom_id: number;
  source_status: BatchStockStatus;
  destination_status: StatusChangeDestination;
  quantity: Quantity;
  reason: string;
};

type Params = {
  locationId: number;
  productVariantId: number;
  batchId: number;
  baseUomId: number;
  sourceStatus: BatchStockStatus;
  destinationStatus: StatusChangeDestination;
  eligibleQuantity: Quantity;
  quantityScale: number;
  quantityStep: Quantity;
  canChange: boolean;
  onSucceeded: () => void | Promise<void>;
};

const isCommand = (value: unknown): value is StockStatusCommand => {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const row = value as Record<string, unknown>;
  const positive = (item: unknown) =>
    typeof item === "number" && Number.isSafeInteger(item) && item > 0;
  return (
    positive(row.location_id) &&
    positive(row.product_variant_id) &&
    positive(row.batch_id) &&
    positive(row.uom_id) &&
    typeof row.source_status === "string" &&
    typeof row.destination_status === "string" &&
    typeof row.quantity === "string" &&
    typeof row.reason === "string" &&
    row.reason.trim().length > 0 &&
    row.reason.length <= 2000
  );
};

export function useStockStatusCommand({
  locationId,
  productVariantId,
  batchId,
  baseUomId,
  sourceStatus,
  destinationStatus,
  eligibleQuantity,
  quantityScale,
  quantityStep,
  canChange,
  onSucceeded,
}: Params) {
  const { t, i18n } = useTranslation();
  const language = i18n.resolvedLanguage || i18n.language || "en";
  const authFetch = useAuthFetch();
  const access = useInventoryAccess(locationId);
  const isOnline = useNetworkStatus();
  const [quantity, setQuantity] = useState(eligibleQuantity);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [pendingBlocked, setPendingBlocked] = useState(false);
  const [pending, setPending] = useState<DurableCommand<StockStatusCommand> | null>(null);

  const scope = useMemo(() => {
    const companyId = access.data?.company_id;
    const actorId = access.data?.backoffice_user_id;
    if (!companyId || !actorId) return null;
    return durableScope(
      companyId,
      actorId,
      "inventory-status-change-v1",
      `${batchId}:${locationId}:${productVariantId}:${sourceStatus}`,
    );
  }, [access.data?.backoffice_user_id, access.data?.company_id, batchId, locationId, productVariantId, sourceStatus]);

  useEffect(() => {
    setQuantity(eligibleQuantity);
    setReason("");
    setPending(null);
    setPendingBlocked(false);
    if (!scope) return;
    let cancelled = false;
    void (async () => {
      try {
        const stored = await readDurableCommand<unknown>(scope);
        if (cancelled || !stored) return;
        if (
          !isCommand(stored.payload) ||
          stored.payload.location_id !== locationId ||
          stored.payload.product_variant_id !== productVariantId ||
          stored.payload.batch_id !== batchId ||
          stored.payload.uom_id !== baseUomId ||
          stored.payload.source_status !== sourceStatus
        ) {
          setPendingBlocked(true);
          return;
        }
        const restored = {
          requestId: stored.requestId,
          payload: stored.payload,
          createdAt: stored.createdAt,
        };
        setPending(restored);
        setQuantity(restored.payload.quantity);
        setReason(restored.payload.reason);
      } catch {
        if (!cancelled) setPendingBlocked(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [baseUomId, batchId, eligibleQuantity, locationId, productVariantId, scope, sourceStatus]);

  const validationError = useMemo(() => {
    if (pending) return null;
    try {
      const parsed = validateVariantQuantity(
        quantity,
        quantityScale,
        quantityStep,
        "quantity",
      );
      if (compareQuantity(parsed, eligibleQuantity) > 0) {
        return batchActionText(t, language, "quantityTooLarge");
      }
      if (!reason.trim()) return batchActionText(t, language, "reason");
      return null;
    } catch {
      return batchActionText(t, language, "quantityRequired");
    }
  }, [eligibleQuantity, language, pending, quantity, quantityScale, quantityStep, reason, t]);

  const submit = async () => {
    if (!scope || busy || !isOnline || !canChange || pendingBlocked) return;
    let normalized: Quantity;
    try {
      normalized = pending?.payload.quantity ?? validateVariantQuantity(
        quantity,
        quantityScale,
        quantityStep,
        "quantity",
      );
      if (compareQuantity(normalized, eligibleQuantity) > 0) {
        toast.error(batchActionText(t, language, "quantityTooLarge"));
        return;
      }
    } catch {
      toast.error(batchActionText(t, language, "quantityRequired"));
      return;
    }
    const cleanReason = pending?.payload.reason ?? reason.trim();
    if (!cleanReason) {
      toast.error(batchActionText(t, language, "reason"));
      return;
    }

    setBusy(true);
    try {
      const payload: StockStatusCommand = pending?.payload ?? {
        location_id: locationId,
        product_variant_id: productVariantId,
        batch_id: batchId,
        uom_id: baseUomId,
        source_status: sourceStatus,
        destination_status: destinationStatus,
        quantity: normalized,
        reason: cleanReason,
      };
      const durable = pending ?? await getOrCreateDurableCommand(scope, payload);
      if (!isCommand(durable.payload)) {
        throw Object.assign(new Error(), { code: "DURABLE_OPERATION_CORRUPT" });
      }
      setPending(durable);
      parseInventoryStatusChangeResponse(
        await authFetch("/warehouse/inventory/status-change", {
          method: "POST",
          body: JSON.stringify({
            request_id: durable.requestId,
            location_id: durable.payload.location_id,
            product_variant_id: durable.payload.product_variant_id,
            batch_id: durable.payload.batch_id,
            uom_id: durable.payload.uom_id,
            source_status: durable.payload.source_status,
            destination_status: durable.payload.destination_status,
            quantity: durable.payload.quantity,
            reason: durable.payload.reason,
          }),
        }),
        {
          source: durable.payload.source_status,
          destination: durable.payload.destination_status,
        },
      );
      completeDurableOperation(scope, durable.requestId);
      setPending(null);
      toast.success(batchActionText(t, language, "success"));
      await onSucceeded();
    } catch (error: unknown) {
      const code = apiErrorCode(error);
      const localBlocked = code === "DURABLE_OPERATION_CORRUPT";
      if (localBlocked) setPendingBlocked(true);
      if (
        !localBlocked &&
        code !== "DURABLE_OPERATION_PENDING" &&
        code !== "BATCH_ACTION_SOURCE_RESPONSE_INVALID" &&
        !isAmbiguousRequestError(error)
      ) {
        abandonDurableOperation(scope);
        setPending(null);
      }
      toast.error(apiErrorMessage(error, batchActionText(t, language, "saveError")));
    } finally {
      setBusy(false);
    }
  };

  return {
    quantity,
    setQuantity,
    reason,
    setReason,
    busy,
    pending,
    pendingBlocked,
    isOnline,
    validationError,
    submit,
  };
}
