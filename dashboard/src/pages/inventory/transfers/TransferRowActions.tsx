import { Ban, CheckCircle2, Eye, XCircle } from "lucide-react";
import { useTransferTranslation } from "./i18n";
import type { TransferAction, WarehouseTransferListItem } from "./types";

export function TransferRowActions({ transfer, locationId, can, onOpenDetail, onOpenAction }: {
  transfer: WarehouseTransferListItem; locationId: number; can: (code: string) => boolean;
  onOpenDetail: (transfer: WarehouseTransferListItem) => void | Promise<void>;
  onOpenAction: (transfer: WarehouseTransferListItem, action: TransferAction) => void;
}) {
  const { t } = useTransferTranslation();
  const actions = [
    { action: "receive" as const, side: transfer.destination_location_id, code: "transfer.receive", Icon: CheckCircle2 },
    { action: "reject" as const, side: transfer.destination_location_id, code: "transfer.reject", Icon: XCircle },
    { action: "cancel" as const, side: transfer.source_location_id, code: "transfer.cancel", Icon: Ban },
  ];
  return <div className="flex justify-center gap-2">
    <button type="button" aria-label={t("inventoryTransfers.details")} title={t("inventoryTransfers.details")}
      onClick={() => void onOpenDetail(transfer)} className="rounded-lg border p-2"><Eye className="h-4 w-4" /></button>
    {transfer.status === "IN_TRANSIT" && actions.filter(item => item.side === locationId).map(({ action, code, Icon }) =>
      <button key={action} type="button" disabled={!can(code)} aria-label={t(`inventoryTransfers.${action}`)}
        title={t(can(code) ? `inventoryTransfers.${action}` : "inventoryTransfers.permissions")}
        onClick={() => onOpenAction(transfer, action)} className="rounded-lg border p-2 disabled:opacity-40"><Icon className="h-4 w-4" /></button>)}
  </div>;
}
