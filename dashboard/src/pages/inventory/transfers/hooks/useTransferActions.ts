import { useTransferTranslation as useTranslation } from "../i18n";
import { useCallback, useState } from "react";
import { toast } from "sonner";
import { useTransferCommand } from "./useTransferCommand";
import type { TransferAction, WarehouseTransferListItem } from "../types";
import { getErrorMessage, getMutationMessage } from "../utils";

interface UseTransferActionsArgs {
  onInventoryChanged: () => void | Promise<void>;
  onCompleted: () => void;
}

export function useTransferActions({
  onInventoryChanged,
  onCompleted,
}: UseTransferActionsArgs) {
  const { t } = useTranslation();
  const command = useTransferCommand("TRANSFER_DECISION", "workspace");
  const [action, setAction] = useState<TransferAction | null>(null);
  const [actionTransfer, setActionTransfer] =
    useState<WarehouseTransferListItem | null>(null);
  const [decisionReason, setDecisionReason] = useState("");
  const [actionSubmitting, setActionSubmitting] = useState(false);

  const openAction = useCallback(
    (transfer: WarehouseTransferListItem, nextAction: TransferAction) => {
      if (transfer.status !== "IN_TRANSIT") {
        toast.error(t("inventoryTransfers.onlyTransit"));
        return;
      }
      setActionTransfer(transfer);
      setAction(nextAction);
      setDecisionReason("");
    },
    [t],
  );

  const closeAction = useCallback(() => {
    if (actionSubmitting) return;
    setAction(null);
    setActionTransfer(null);
    setDecisionReason("");
  }, [actionSubmitting]);

  const updateDecisionReason = useCallback((value: string) => {
    setDecisionReason(value);
  }, []);

  const finish = useCallback(async (raw: unknown) => {
    toast.success(getMutationMessage(raw));
    setAction(null);
    setActionTransfer(null);
    setDecisionReason("");
    onCompleted();
    await onInventoryChanged();
  }, [onCompleted, onInventoryChanged]);

  const handleAction = useCallback(async () => {
    if (!action || !actionTransfer) return;
    const reason = decisionReason.trim();
    if ((action === "reject" || action === "cancel") && !reason) {
      toast.error(t("inventoryTransfers.reasonRequired"));
      return;
    }
    if (reason.length > 2000) {
      toast.error(t("inventoryTransfers.reasonLength"));
      return;
    }

    setActionSubmitting(true);
    try {
      const raw = await command.execute(action === "receive" ? {
        path: "/warehouse/unified/transfer/receive",
        method: "POST",
        body: {
          transfer_header_id: actionTransfer.id,
          destination_location_id: actionTransfer.destination_location_id,
        },
      } : {
        path: `/warehouse/unified/transfer/${actionTransfer.id}/${action}`,
        method: "POST",
        body: { decision_reason: reason },
      }, getMutationMessage);
      if (raw !== undefined) await finish(raw);
    } catch (error: unknown) {
      toast.error(getErrorMessage(error));
    } finally {
      setActionSubmitting(false);
    }
  }, [action, actionTransfer, command, decisionReason, finish, t]);

  const retryPendingAction = async () => {
    try {
      const raw = await command.execute(undefined, getMutationMessage);
      if (raw !== undefined) await finish(raw);
    } catch (error) {
      toast.error(getErrorMessage(error));
    }
  };

  return {
    command,
    retryPendingAction,
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
