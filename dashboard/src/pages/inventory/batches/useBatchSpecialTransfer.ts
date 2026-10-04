import { useState } from "react";
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
} from "@/lib/durableOperations";
import type { Quantity } from "@/lib/quantity";

import {
  parseBatchSpecialTransferResult,
  type BatchSpecialTransferPurpose,
} from "./batchSpecialTransferContract";
import type { BatchActionSnapshot } from "./contracts";
import type {
  BatchStockStatus,
} from "./batchStockSourcesContract";

type Choice = {
  purpose: BatchSpecialTransferPurpose;
  sourceLocationId: number;
  sourceStatus: BatchStockStatus;
  quantity: Quantity;
  baseUomId: number;
};

type Params = {
  batch: BatchActionSnapshot | null;
  productVariantId: number | null;
  onSucceeded: () => void | Promise<void>;
};

export function useBatchSpecialTransfer({
  batch,
  productVariantId,
  onSucceeded,
}: Params) {
  const { t } = useTranslation();
  const authFetch = useAuthFetch();
  const access = useInventoryAccess();
  const isOnline = useNetworkStatus();
  const [busyKey, setBusyKey] = useState<string | null>(null);

  const companyId = access.data?.company_id ?? null;
  const driverId = access.data?.driver_id ?? null;

  const run = async (choice: Choice) => {
    if (
      !batch ||
      productVariantId === null ||
      !isOnline ||
      companyId === null ||
      driverId === null ||
      busyKey !== null
    ) {
      return;
    }

    const key = [
      batch.batch_id,
      choice.sourceLocationId,
      choice.sourceStatus,
    ].join(":");
    const scope = durableScope(
      companyId,
      driverId,
      "batch-special-transfer-v1",
      key,
    );
    const notes = t(
      `inventoryBatches.quantityActions.notes.${choice.purpose}`,
      {
        batch: batch.batch_number,
        reason:
          batch.disposition_reason ??
          t("inventoryBatches.quantityActions.defaultReason"),
      },
    );
    const payload = {
      source_location_id: choice.sourceLocationId,
      transfer_purpose: choice.purpose,
      items: [
        {
          product_variant_id: productVariantId,
          batch_id: batch.batch_id,
          source_status: choice.sourceStatus,
          quantity: choice.quantity,
          uom_id: choice.baseUomId,
        },
      ],
      notes,
    };

    setBusyKey(key);
    try {
      const durable = await getOrCreateDurableCommand(
        scope,
        payload,
      );
      const result = parseBatchSpecialTransferResult(
        await authFetch(
          "/warehouse/unified/transfer/special/dispatch",
          {
            method: "POST",
            body: JSON.stringify({
              request_id: durable.requestId,
              ...durable.payload,
            }),
          },
        ),
      );
      completeDurableOperation(scope, durable.requestId);
      toast.success(
        t("inventoryBatches.quantityActions.success", {
          reference: result.transfer_reference,
        }),
      );
      await onSucceeded();
      return true;
    } catch (error) {
      const code = apiErrorCode(error);
      const ambiguous =
        isAmbiguousRequestError(error) ||
        code === "BATCH_SPECIAL_TRANSFER_RESPONSE_INVALID" ||
        code === "DURABLE_OPERATION_PENDING";
      if (!ambiguous) {
        abandonDurableOperation(scope);
      }
      toast.error(
        apiErrorMessage(
          error,
          ambiguous
            ? t("inventoryBatches.quantityActions.pending")
            : t("inventoryBatches.quantityActions.errors.dispatch"),
        ),
      );
      return false;
    } finally {
      setBusyKey(null);
    }
  };

  return {
    run,
    busyKey,
    isOnline,
  };
}
