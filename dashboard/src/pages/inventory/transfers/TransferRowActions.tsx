import { Ban, CheckCircle2, Eye, XCircle } from "lucide-react";
import { useTransferTranslation } from "./i18n";
import type { TransferAction, WarehouseTransferListItem } from "./types";

export function TransferRowActions({ transfer, locationId, can, onOpenDetail, onOpenAction }: {
  transfer: WarehouseTransferListItem;
  locationId: number;
  can: (code: string) => boolean;
  onOpenDetail: (transfer: WarehouseTransferListItem) => void | Promise<void>;
  onOpenAction: (transfer: WarehouseTransferListItem, action: TransferAction) => void;
}) {
  const { t } = useTransferTranslation();
  const actions = [
    {
      action: "receive" as const,
      side: transfer.destination_location_id,
      code: "transfer.receive",
      Icon: CheckCircle2,
      className: "border-emerald-600 bg-emerald-600 text-white hover:bg-emerald-700 focus-visible:ring-emerald-300",
      priority: "primary",
    },
    {
      action: "reject" as const,
      side: transfer.destination_location_id,
      code: "transfer.reject",
      Icon: XCircle,
      className: "border-red-200 bg-white text-red-700 hover:bg-red-50 focus-visible:ring-red-300",
      priority: "secondary",
    },
    {
      action: "cancel" as const,
      side: transfer.source_location_id,
      code: "transfer.cancel",
      Icon: Ban,
      className: "border-amber-200 bg-white text-amber-800 hover:bg-amber-50 focus-visible:ring-amber-300",
      priority: "secondary",
    },
  ] as const;

  return (
    <div className="flex flex-wrap items-center justify-center gap-1.5" data-cp13-action-group="transfer-row">
      <button
        type="button"
        aria-label={t("inventoryTransfers.details")}
        title={t("inventoryTransfers.details")}
        onClick={() => void onOpenDetail(transfer)}
        className="inline-flex h-8 items-center gap-1 rounded-lg border border-slate-200 bg-white px-2 text-[10px] font-black text-slate-600 outline-none hover:bg-slate-50 focus-visible:ring-2 focus-visible:ring-blue-300"
        data-cp13-action-priority="secondary"
      >
        <Eye className="h-3.5 w-3.5" aria-hidden="true" />
        <span>{t("inventoryTransfers.details")}</span>
      </button>

      {transfer.status === "IN_TRANSIT"
        ? actions
            .filter((item) => item.side === locationId)
            .map(({ action, code, Icon, className, priority }) => {
              const allowed = can(code);
              return (
                <button
                  key={action}
                  type="button"
                  disabled={!allowed}
                  aria-label={t(`inventoryTransfers.${action}`)}
                  title={t(allowed ? `inventoryTransfers.${action}` : "inventoryTransfers.permissions")}
                  onClick={() => onOpenAction(transfer, action)}
                  className={`inline-flex h-8 items-center gap-1 rounded-lg border px-2 text-[10px] font-black outline-none disabled:cursor-not-allowed disabled:opacity-40 focus-visible:ring-2 ${className}`}
                  data-cp13-action-priority={priority}
                  data-cp13-transfer-decision={action}
                >
                  <Icon className="h-3.5 w-3.5" aria-hidden="true" />
                  <span>{t(`inventoryTransfers.${action}`)}</span>
                </button>
              );
            })
        : null}
    </div>
  );
}
