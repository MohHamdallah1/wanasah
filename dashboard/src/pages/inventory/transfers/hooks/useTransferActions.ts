import { useCallback, useState } from "react";
import { toast } from "sonner";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import type {
  TransferAction,
  WarehouseTransferListItem,
} from "../types";
import { getErrorMessage, getMutationMessage } from "../utils";

interface UseTransferActionsArgs {
  locationId: number;
  onInventoryChanged: () => void | Promise<void>;
  onCompleted: () => void;
}

export function useTransferActions({
  locationId,
  onInventoryChanged,
  onCompleted,
}: UseTransferActionsArgs) {
  const authenticatedFetch = useAuthFetch();

  const [action, setAction] = useState<TransferAction | null>(null);
  const [actionTransfer, setActionTransfer] =
    useState<WarehouseTransferListItem | null>(null);
  const [decisionReason, setDecisionReason] = useState("");
  const [actionRequestId, setActionRequestId] = useState(() =>
    crypto.randomUUID()
  );
  const [actionSubmitting, setActionSubmitting] = useState(false);

  const openAction = useCallback(
    (
      transfer: WarehouseTransferListItem,
      nextAction: TransferAction
    ) => {
      if (transfer.status !== "IN_TRANSIT") {
        toast.error("هذه العملية متاحة فقط للحوالات الموجودة في الطريق.");
        return;
      }

      const isSource = transfer.source_location_id === locationId;
      const isDestination =
        transfer.destination_location_id === locationId;

      if (nextAction === "cancel" && !isSource) {
        toast.error("الإلغاء متاح من جهة مصدر الحوالة فقط.");
        return;
      }
      if (
        (nextAction === "receive" || nextAction === "reject") &&
        !isDestination
      ) {
        toast.error("الاستلام/الرفض متاحان من جهة وجهة الحوالة فقط.");
        return;
      }

      setActionTransfer(transfer);
      setAction(nextAction);
      setDecisionReason("");
      setActionRequestId(crypto.randomUUID());
    },
    [locationId]
  );

  const closeAction = useCallback(() => {
    if (actionSubmitting) return;
    setAction(null);
    setActionTransfer(null);
    setDecisionReason("");
  }, [actionSubmitting]);

  const updateDecisionReason = useCallback((value: string) => {
    setDecisionReason(value);
    setActionRequestId(crypto.randomUUID());
  }, []);

  const handleAction = useCallback(async () => {
    if (!action || !actionTransfer) return;

    const reason = decisionReason.trim();
    if ((action === "reject" || action === "cancel") && !reason) {
      toast.error("سبب القرار مطلوب.");
      return;
    }
    if (reason.length > 2000) {
      toast.error("سبب القرار لا يجوز أن يتجاوز 2000 حرف.");
      return;
    }

    setActionSubmitting(true);

    try {
      let raw: unknown;

      if (action === "receive") {
        raw = await authenticatedFetch(
          "/warehouse/unified/transfer/receive",
          {
            method: "POST",
            body: JSON.stringify({
              request_id: actionRequestId,
              transfer_header_id: actionTransfer.id,
              destination_location_id:
                actionTransfer.destination_location_id,
            }),
          }
        );
      } else {
        raw = await authenticatedFetch(
          `/warehouse/unified/transfer/${actionTransfer.id}/${action}`,
          {
            method: "POST",
            body: JSON.stringify({
              request_id: actionRequestId,
              decision_reason: reason,
            }),
          }
        );
      }

      toast.success(getMutationMessage(raw));
      setAction(null);
      setActionTransfer(null);
      setDecisionReason("");
      onCompleted();
      await onInventoryChanged();
    } catch (error: unknown) {
      // Keep the same request_id for an unchanged safe retry.
      toast.error(getErrorMessage(error));
    } finally {
      setActionSubmitting(false);
    }
  }, [
    action,
    actionRequestId,
    actionTransfer,
    authenticatedFetch,
    decisionReason,
    onCompleted,
    onInventoryChanged,
  ]);

  return {
    action,
    actionTransfer,
    decisionReason,
    actionSubmitting,
    openAction,
    closeAction,
    updateDecisionReason,
    handleAction,
  };
}
