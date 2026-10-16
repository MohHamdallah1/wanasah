import { useTransferTranslation as useTranslation } from "../i18n";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { useTransferCommand } from "./useTransferCommand";
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
  const { t } = useTranslation();
  const command = useTransferCommand("TRANSFER_DECISION", locationId);
  const currentLocation = useRef(locationId);
  currentLocation.current = locationId;

  const [action, setAction] = useState<TransferAction | null>(null);
  const [actionTransfer, setActionTransfer] =
    useState<WarehouseTransferListItem | null>(null);
  const [decisionReason, setDecisionReason] = useState("");
  const [actionSubmitting, setActionSubmitting] = useState(false);
  useEffect(() => { setAction(null); setActionTransfer(null); setDecisionReason(""); setActionSubmitting(false); }, [locationId]);

  const openAction = useCallback(
    (
      transfer: WarehouseTransferListItem,
      nextAction: TransferAction
    ) => {
      if (transfer.status !== "IN_TRANSIT") {
        toast.error(t("inventoryTransfers.onlyTransit"));
        return;
      }

      const isSource = transfer.source_location_id === locationId;
      const isDestination =
        transfer.destination_location_id === locationId;

      if (nextAction === "cancel" && !isSource) {
        toast.error(t("inventoryTransfers.sourceOnly"));
        return;
      }
      if (
        (nextAction === "receive" || nextAction === "reject") &&
        !isDestination
      ) {
        toast.error(t("inventoryTransfers.destinationOnly"));
        return;
      }

      setActionTransfer(transfer);
      setAction(nextAction);
      setDecisionReason("");
    },
    [locationId, t]
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
        path: "/warehouse/unified/transfer/receive", method: "POST",
        body: { transfer_header_id: actionTransfer.id, destination_location_id: actionTransfer.destination_location_id },
      } : {
        path: `/warehouse/unified/transfer/${actionTransfer.id}/${action}`, method: "POST",
        body: { decision_reason: reason },
      }, getMutationMessage);
      if (raw === undefined || currentLocation.current !== locationId) return;

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
      if (currentLocation.current === locationId) setActionSubmitting(false);
    }
  }, [
    action,
    actionTransfer,
    locationId,
    command,
    decisionReason,
    t,
    onCompleted,
    onInventoryChanged,
  ]);

  const retryPendingAction = async () => {
    try {
      const raw = await command.execute(undefined, getMutationMessage);
      if (raw === undefined || currentLocation.current !== locationId) return;
      toast.success(getMutationMessage(raw));
      setAction(null);
      setActionTransfer(null);
      setDecisionReason("");
      onCompleted();
      await onInventoryChanged();
    } catch (error) { toast.error(getErrorMessage(error)); }
  };
  return {
    command, retryPendingAction,
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
