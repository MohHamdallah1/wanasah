import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { isConfirmedSupplierRejection } from "@/features/suppliers/contracts";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { useInventoryAccess } from "@/hooks/useInventoryAccess";
import { useNetworkStatus } from "@/hooks/useNetworkStatus";
import { apiErrorCode, apiErrorMessage, isAmbiguousRequestError } from "@/lib/apiErrors";
import {
  abandonDurableOperation,
  completeDurableOperation,
  durableScope,
  getOrCreateDurableCommand,
  readDurableCommand,
  type DurableCommand,
} from "@/lib/durableOperations";
import {
  parseWholeProductQualityResult,
  type WholeProductPostResolutionHold,
  type WholeProductQualityAction,
} from "./wholeProductQualityResolveContract";

export type { WholeProductQualityAction } from "./wholeProductQualityResolveContract";

type QualityPayload = {
  action: WholeProductQualityAction;
  reason: string;
  supplier_id?: number | null;
  recipient_name?: string | null;
  post_resolution_hold?: WholeProductPostResolutionHold;
};

type QualityPending = {
  scope: string;
  command: DurableCommand<QualityPayload>;
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
  const [pending, setPending] = useState<QualityPending | null>(null);
  const [recoveryBlocked, setRecoveryBlocked] = useState(false);
  const [recoveryReady, setRecoveryReady] = useState(false);
  const [recoveryRevision, setRecoveryRevision] = useState(0);
  const running = useRef(false);

  useEffect(() => {
    let live = true;
    setRecoveryReady(false);
    setPending(null);
    setRecoveryBlocked(false);
    if (companyId === null || driverId === null) return;

    const scopes = [
      durableScope(companyId, driverId, "whole-product-quality-resolve-v3", productVariantId),
      ...(["DISPOSE", "RETURN_TO_VENDOR"] as const).map((action) =>
        durableScope(companyId, driverId, "whole-product-quality-resolve-v2", `${productVariantId}:${action}`),
      ),
    ];

    void Promise.all(
      scopes.map(async (scope) => ({
        scope,
        command: await readDurableCommand<QualityPayload>(scope),
      })),
    )
      .then((records) => {
        if (!live) return;
        const found = records.find((record) => record.command !== null);
        setPending(found?.command ? { scope: found.scope, command: found.command } : null);
        setRecoveryReady(true);
      })
      .catch(() => {
        if (live) setRecoveryBlocked(true);
      });

    return () => {
      live = false;
    };
  }, [companyId, driverId, productVariantId, recoveryRevision]);

  const resolveAll = async ({
    action,
    reason,
    supplierId,
    confirmationPassword,
    postResolutionHold,
    stored,
  }: {
    action: WholeProductQualityAction;
    reason: string;
    supplierId?: number | null;
    confirmationPassword: string;
    postResolutionHold?: WholeProductPostResolutionHold;
    stored?: QualityPending;
  }) => {
    if (
      !confirmationPassword
      || !isOnline
      || companyId === null
      || driverId === null
      || running.current
      || recoveryBlocked
      || !recoveryReady
    ) return false;
    if (pending && !stored) return false;
    if (!stored && postResolutionHold === undefined) return false;
    if (!stored && action === "RETURN_TO_VENDOR" && supplierId == null) return false;

    const key = `${productVariantId}:${action}`;
    const payload: QualityPayload = stored?.command.payload ?? {
      action,
      reason: reason.trim(),
      supplier_id: action === "RETURN_TO_VENDOR" ? supplierId ?? null : null,
      post_resolution_hold: postResolutionHold,
    };
    const expectedHold = payload.post_resolution_hold ?? "NONE";
    const scope = stored?.scope
      ?? durableScope(companyId, driverId, "whole-product-quality-resolve-v3", productVariantId);

    setBusyKey(key);
    running.current = true;
    let recovering = false;
    try {
      recovering = (await readDurableCommand(scope)) !== null;
      const durable = stored?.command ?? await getOrCreateDurableCommand(scope, payload);
      setPending({ scope, command: durable });
      const body = {
        request_id: durable.requestId,
        ...durable.payload,
        handover_reference: durable.payload.action === "RETURN_TO_VENDOR"
          ? `SYSTEM-${durable.requestId}`
          : null,
        // Re-authentication stays ephemeral and is never persisted in durable storage.
        confirmation_password: confirmationPassword,
      };

      const raw = await authFetch(
        `/warehouse/quality/products/${productVariantId}/resolve-all`,
        {
          method: "POST",
          body: JSON.stringify(body),
        },
      );
      parseWholeProductQualityResult(
        raw,
        productVariantId,
        durable.payload.action,
        durable.payload.post_resolution_hold ?? "NONE",
      );

      completeDurableOperation(scope, durable.requestId);
      setPending(null);
      setRecoveryRevision((value) => value + 1);
      toast.success(t(`productQualityInline.success.${durable.payload.action}`));
      await onSucceeded();
      return true;
    } catch (error) {
      const code = apiErrorCode(error);
      const ambiguous = isAmbiguousRequestError(error)
        || recovering
        || code === "DURABLE_OPERATION_PENDING"
        || code === "DURABLE_OPERATION_CORRUPT"
        || code === "PRODUCT_QUALITY_COMMAND_RESPONSE_INVALID";

      if (
        !ambiguous
        || (isConfirmedSupplierRejection(code) && !isAmbiguousRequestError(error))
      ) {
        abandonDurableOperation(scope);
        setPending(null);
        setRecoveryRevision((value) => value + 1);
      }

      toast.error(apiErrorMessage(
        error,
        ambiguous
          ? t("productQualityInline.pending")
          : t("productQualityInline.errors.resolve"),
      ));
      return false;
    } finally {
      setBusyKey(null);
      running.current = false;
    }
  };

  const retryPending = (confirmationPassword: string) => pending
    ? resolveAll({
        action: pending.command.payload.action,
        reason: pending.command.payload.reason,
        supplierId: pending.command.payload.supplier_id ?? null,
        confirmationPassword,
        postResolutionHold: pending.command.payload.post_resolution_hold ?? "NONE",
        stored: pending,
      })
    : Promise.resolve(false);

  return {
    resolveAll,
    retryPending,
    pending,
    recoveryBlocked,
    recoveryReady,
    busyKey,
    isOnline,
  };
}
