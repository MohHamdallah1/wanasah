import { useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { useAuthFetch } from "@/hooks/useAuthFetch";
import { useInventoryAccess } from "@/hooks/useInventoryAccess";
import { useNetworkStatus } from "@/hooks/useNetworkStatus";
import { apiErrorCode, apiErrorMessage, isAmbiguousRequestError } from "@/lib/apiErrors";
import {
  abandonDurableOperation,
  completeDurableOperation,
  durableScope,
  getOrCreateDurableCommand,
} from "@/lib/durableOperations";

export type WholeProductQualityAction = "DISPOSE" | "RETURN_TO_VENDOR";

const resultRecord = (raw: unknown): Record<string, unknown> => {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    throw new Error("PRODUCT_QUALITY_COMMAND_RESPONSE_INVALID");
  }
  return raw as Record<string, unknown>;
};

export function useProductQualityCommands({
  productVariantId,
  onSucceeded,
}: {
  productVariantId: number;
  onSucceeded: () => void | Promise<void>;
}) {
  const { t } = useTranslation();
  const authFetch = useAuthFetch();
  const access = useInventoryAccess();
  const isOnline = useNetworkStatus();
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const companyId = access.data?.company_id ?? null;
  const driverId = access.data?.driver_id ?? null;

  const resolveAll = async ({
    action,
    reason,
    disposalMethod,
    evidenceReference,
    recipientName,
    handoverReference,
  }: {
    action: WholeProductQualityAction;
    reason: string;
    disposalMethod?: string;
    evidenceReference?: string;
    recipientName?: string;
    handoverReference?: string;
  }) => {
    if (!isOnline || companyId === null || driverId === null || busyKey !== null) return false;
    const key = `${productVariantId}:${action}`;
    const payload = {
      action,
      reason: reason.trim(),
      disposal_method: disposalMethod?.trim() || null,
      evidence_reference: evidenceReference?.trim() || null,
      recipient_name: recipientName?.trim() || null,
      handover_reference: handoverReference?.trim() || null,
    };
    const scope = durableScope(companyId, driverId, "whole-product-quality-resolve-v1", key);
    setBusyKey(key);
    try {
      const durable = await getOrCreateDurableCommand(scope, payload);
      const raw = resultRecord(await authFetch(
        `/warehouse/quality/products/${productVariantId}/resolve-all`,
        {
          method: "POST",
          body: JSON.stringify({ request_id: durable.requestId, ...durable.payload }),
        },
      ));
      if (
        raw.action !== action
        || typeof raw.total_quantity !== "string"
        || !Array.isArray(raw.locations)
      ) {
        throw new Error("PRODUCT_QUALITY_COMMAND_RESPONSE_INVALID");
      }
      completeDurableOperation(scope, durable.requestId);
      toast.success(t(`productQualityInline.success.${action}`));
      await onSucceeded();
      return true;
    } catch (error) {
      const code = apiErrorCode(error);
      const ambiguous = isAmbiguousRequestError(error)
        || code === "DURABLE_OPERATION_PENDING"
        || code === "PRODUCT_QUALITY_COMMAND_RESPONSE_INVALID";
      if (!ambiguous) abandonDurableOperation(scope);
      toast.error(apiErrorMessage(
        error,
        ambiguous
          ? t("productQualityInline.pending")
          : t("productQualityInline.errors.resolve"),
      ));
      return false;
    } finally {
      setBusyKey(null);
    }
  };

  return { resolveAll, busyKey, isOnline };
}
