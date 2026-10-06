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
import type { Quantity } from "@/lib/quantity";
import { allocateRequestedQuantity, type QualityActionLine } from "./productQualityLocationModel";
import type { QualityDispatchPurpose, QualityTerminalAction } from "./wholeProductQualityContract";

const resultRecord = (raw: unknown): Record<string, unknown> => {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    throw new Error("PRODUCT_QUALITY_COMMAND_RESPONSE_INVALID");
  }
  return raw as Record<string, unknown>;
};

export function useProductQualityCommands({
  productVariantId,
  baseUomId,
  onSucceeded,
}: {
  productVariantId: number;
  baseUomId: number;
  onSucceeded: () => void | Promise<void>;
}) {
  const { t } = useTranslation();
  const authFetch = useAuthFetch();
  const access = useInventoryAccess();
  const isOnline = useNetworkStatus();
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const companyId = access.data?.company_id ?? null;
  const driverId = access.data?.driver_id ?? null;

  const stage = async ({
    purpose,
    locationId,
    quantity,
    lines,
    reason,
  }: {
    purpose: QualityDispatchPurpose;
    locationId: number;
    quantity: Quantity;
    lines: QualityActionLine[];
    reason: string;
  }) => {
    if (!isOnline || companyId === null || driverId === null || busyKey !== null) return false;
    const key = `${productVariantId}:${locationId}:${purpose}`;
    let allocations;
    try {
      allocations = allocateRequestedQuantity(lines, quantity);
    } catch {
      toast.error(t("products.qualityInline.errors.quantity"));
      return false;
    }
    const payload = {
      source_location_id: locationId,
      transfer_purpose: purpose,
      items: allocations.map((line) => ({
        product_variant_id: productVariantId,
        batch_id: line.batchId,
        source_status: line.stockStatus,
        quantity: line.quantity,
        uom_id: baseUomId,
      })),
      notes: reason.trim(),
    };
    const scope = durableScope(companyId, driverId, "product-quality-location-stage-v1", key);
    setBusyKey(key);
    try {
      const durable = await getOrCreateDurableCommand(scope, payload);
      const raw = resultRecord(await authFetch("/warehouse/quality/stage", {
        method: "POST",
        body: JSON.stringify({ request_id: durable.requestId, ...durable.payload }),
      }));
      if (typeof raw.transfer_reference !== "string" || !raw.transfer_reference.trim()) {
        throw new Error("PRODUCT_QUALITY_COMMAND_RESPONSE_INVALID");
      }
      completeDurableOperation(scope, durable.requestId);
      toast.success(t("products.qualityInline.stageSuccess", { reference: raw.transfer_reference }));
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
          ? t("products.qualityInline.pending")
          : t("products.qualityInline.errors.stage"),
      ));
      return false;
    } finally {
      setBusyKey(null);
    }
  };

  const confirmTerminal = async ({
    action,
    locationId,
    quantity,
    lines,
    reason,
    method,
    evidenceReference,
    vendorName,
    vendorReference,
    handoverReference,
  }: {
    action: QualityTerminalAction;
    locationId: number;
    quantity: Quantity;
    lines: QualityActionLine[];
    reason?: string;
    method?: string;
    evidenceReference?: string;
    vendorName?: string;
    vendorReference?: string;
    handoverReference?: string;
  }) => {
    if (!isOnline || companyId === null || driverId === null || busyKey !== null) return false;
    const groupKey = `${productVariantId}:${locationId}:${action}`;
    let allocations;
    try {
      allocations = allocateRequestedQuantity(lines, quantity);
    } catch {
      toast.error(t("products.qualityInline.errors.quantity"));
      return false;
    }
    setBusyKey(groupKey);
    let changed = false;
    try {
      for (const allocation of allocations) {
        const common = {
          source_location_id: locationId,
          product_variant_id: productVariantId,
          batch_id: allocation.batchId,
          quantity: allocation.quantity,
        };
        const payload = action === "CONFIRM_DISPOSAL"
          ? {
              ...common,
              reason: reason?.trim(),
              method: method?.trim() || null,
              evidence_reference: evidenceReference?.trim() || null,
            }
          : {
              ...common,
              source_status: allocation.stockStatus,
              vendor_name: vendorName?.trim(),
              vendor_reference: vendorReference?.trim(),
              handover_reference: handoverReference?.trim(),
            };
        const key = `${groupKey}:${allocation.batchId}:${allocation.stockStatus}`;
        const scope = durableScope(
          companyId,
          driverId,
          "product-quality-location-terminal-v1",
          key,
        );
        try {
          const durable = await getOrCreateDurableCommand(scope, payload);
          const endpoint = action === "CONFIRM_DISPOSAL"
            ? "/warehouse/quality/disposal/confirm"
            : "/warehouse/quality/vendor-return/confirm";
          const raw = resultRecord(await authFetch(endpoint, {
            method: "POST",
            body: JSON.stringify({ request_id: durable.requestId, ...durable.payload }),
          }));
          const expected = action === "CONFIRM_DISPOSAL"
            ? "INVENTORY_FINAL_DISPOSAL_CONFIRMED"
            : "INVENTORY_VENDOR_HANDOVER_CONFIRMED";
          if (raw.event_type !== expected) {
            throw new Error("PRODUCT_QUALITY_COMMAND_RESPONSE_INVALID");
          }
          completeDurableOperation(scope, durable.requestId);
          changed = true;
        } catch (error) {
          const code = apiErrorCode(error);
          const ambiguous = isAmbiguousRequestError(error)
            || code === "DURABLE_OPERATION_PENDING"
            || code === "PRODUCT_QUALITY_COMMAND_RESPONSE_INVALID";
          if (!ambiguous) abandonDurableOperation(scope);
          if (changed) await onSucceeded();
          toast.error(apiErrorMessage(
            error,
            ambiguous
              ? t("products.qualityInline.pending")
              : t("products.qualityInline.errors.confirm"),
          ));
          return false;
        }
      }
      await onSucceeded();
      toast.success(t(`products.qualityInline.confirmSuccess.${action}`));
      return true;
    } finally {
      setBusyKey(null);
    }
  };

  return { stage, confirmTerminal, busyKey, isOnline };
}
