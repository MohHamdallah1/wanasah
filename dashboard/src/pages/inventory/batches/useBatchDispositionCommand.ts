import { useEffect, useState } from "react";
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
  parseBatchDispositionMutation,
  type BatchActionSnapshot,
  type BatchDisposition,
} from "./contracts";

type BatchDispositionCommand = {
  batch_id: number;
  expected_revision: number;
  disposition: BatchDisposition;
  reason: string;
};

type Params = {
  batch: BatchActionSnapshot | null;
  canChange: boolean;
  onSucceeded: () => void | Promise<void>;
  onRevisionConflict: () => void | Promise<void>;
};

const isCommand = (
  value: unknown,
): value is BatchDispositionCommand => {
  if (
    value === null ||
    typeof value !== "object" ||
    Array.isArray(value)
  ) {
    return false;
  }
  const row = value as Record<string, unknown>;
  return (
    typeof row.batch_id === "number" &&
    Number.isSafeInteger(row.batch_id) &&
    row.batch_id > 0 &&
    typeof row.expected_revision === "number" &&
    Number.isSafeInteger(row.expected_revision) &&
    row.expected_revision > 0 &&
    (row.disposition === "RELEASED" ||
      row.disposition === "QUARANTINED" ||
      row.disposition === "BLOCKED" ||
      row.disposition === "RECALLED") &&
    typeof row.reason === "string" &&
    row.reason.trim().length > 0 &&
    row.reason.length <= 2000
  );
};

export function useBatchDispositionCommand({
  batch,
  canChange,
  onSucceeded,
  onRevisionConflict,
}: Params) {
  const { t } = useTranslation();
  const authFetch = useAuthFetch();
  const access = useInventoryAccess();
  const isOnline = useNetworkStatus();
  const [target, setTargetState] = useState<BatchDisposition | null>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [pendingBlocked, setPendingBlocked] = useState(false);
  const [revisionConflict, setRevisionConflict] = useState(false);
  const [pending, setPending] = useState<
    DurableCommand<BatchDispositionCommand> | null
  >(null);

  const companyId = access.data?.company_id ?? null;
  const backofficeUserId = access.data?.backoffice_user_id ?? null;
  const scope =
    batch && companyId !== null && backofficeUserId !== null
      ? durableScope(
          companyId,
          backofficeUserId,
          "batch-disposition-v1",
          batch.batch_id,
        )
      : null;

  useEffect(() => {
    setTargetState(null);
    setReason("");
    setPending(null);
    setPendingBlocked(false);
    setRevisionConflict(false);

    if (!scope || !batch) return;
    let cancelled = false;
    void (async () => {
      try {
        const stored = await readDurableCommand<unknown>(scope);
        if (cancelled || !stored) return;
        if (
          !isCommand(stored.payload) ||
          stored.payload.batch_id !== batch.batch_id
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
        setTargetState(restored.payload.disposition);
        setReason(restored.payload.reason);
      } catch {
        if (!cancelled) setPendingBlocked(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [batch?.batch_id, scope]);

  const setTarget = (value: BatchDisposition) => {
    setRevisionConflict(false);
    setTargetState(value);
  };

  const submit = async () => {
    if (
      !batch ||
      busy ||
      !scope ||
      !isOnline ||
      !canChange ||
      pendingBlocked
    ) {
      return;
    }

    const clean = reason.trim();
    if (!pending && (!target || !clean)) {
      toast.error(
        t("inventoryBatches.disposition.errors.required"),
      );
      return;
    }

    setBusy(true);
    try {
      const payload =
        pending?.payload ?? {
          batch_id: batch.batch_id,
          expected_revision: batch.disposition_revision,
          disposition: target as BatchDisposition,
          reason: clean,
        };
      const durable =
        pending ??
        (await getOrCreateDurableCommand(
          scope,
          payload,
        ));
      if (!isCommand(durable.payload)) {
        throw Object.assign(new Error(), {
          code: "DURABLE_OPERATION_CORRUPT",
        });
      }

      setPending(durable);
      const result = parseBatchDispositionMutation(
        await authFetch(
          `/warehouse/batches/${batch.batch_id}/disposition`,
          {
            method: "POST",
            body: JSON.stringify({
              request_id: durable.requestId,
              expected_revision:
                durable.payload.expected_revision,
              disposition:
                durable.payload.disposition,
              reason: durable.payload.reason,
            }),
          },
        ),
      );
      if (result.batch_id !== batch.batch_id) {
        throw Object.assign(new Error(), {
          code: "BATCH_DISPOSITION_RESPONSE_INVALID",
        });
      }

      completeDurableOperation(
        scope,
        durable.requestId,
      );
      setPending(null);
      setTargetState(null);
      setReason("");
      setRevisionConflict(false);
      toast.success(
        t("inventoryBatches.disposition.success"),
      );
      await onSucceeded();
    } catch (error) {
      const code = apiErrorCode(error);
      const conflict = code === "BATCH_DISPOSITION_REVISION_CONFLICT";
      const localBlocked = code === "DURABLE_OPERATION_CORRUPT";
      if (localBlocked) {
        setPendingBlocked(true);
      }
      if (conflict) {
        abandonDurableOperation(scope);
        setPending(null);
        setTargetState(null);
        setRevisionConflict(true);
        await onRevisionConflict();
      } else if (
        !localBlocked &&
        code !== "DURABLE_OPERATION_PENDING" &&
        code !== "BATCH_DISPOSITION_RESPONSE_INVALID" &&
        !isAmbiguousRequestError(error)
      ) {
        abandonDurableOperation(scope);
        setPending(null);
      }
      toast.error(
        apiErrorMessage(
          error,
          t("inventoryBatches.disposition.errors.save"),
        ),
      );
    } finally {
      setBusy(false);
    }
  };

  return {
    target,
    setTarget,
    reason,
    setReason,
    busy,
    pending,
    pendingBlocked,
    revisionConflict,
    isOnline,
    submit,
  };
}
