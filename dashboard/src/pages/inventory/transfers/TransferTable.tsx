import { useTransferTranslation as useTranslation, formatTransferNumber } from "./i18n";
import { useInventoryAccess } from "@/hooks/useInventoryAccess";
import {
  ArrowDownToLine,
  ArrowUpFromLine,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";
import { TransferRowActions } from "./TransferRowActions";
import { STATUS_META } from "./constants";
import type {
  TransferAction,
  WarehouseTransferListItem,
} from "./types";
import { formatDate } from "./utils";

interface TransferTableProps {
  items: WarehouseTransferListItem[];
  locationId: number;
  loading: boolean;
  cursorHistoryLength: number;
  nextCursor: string | null;
  onOpenDetail: (transfer: WarehouseTransferListItem) => void | Promise<void>;
  onOpenAction: (
    transfer: WarehouseTransferListItem,
    action: TransferAction
  ) => void;
  onPrevious: () => void;
  onNext: () => void;
}

export function TransferTable({
  items,
  locationId,
  loading,
  cursorHistoryLength,
  nextCursor,
  onOpenDetail,
  onOpenAction,
  onPrevious,
  onNext,
}: TransferTableProps) {
  const { t } = useTranslation();
  const access = useInventoryAccess(locationId);
  return (
    <>
      <div className="glass-card inventory-data-panel rounded-2xl overflow-hidden min-h-0 flex-1">
        <div className="overflow-auto h-full">
          <table className="hidden md:table w-full text-sm text-start">
            <thead className="bg-slate-50 sticky top-0 z-10">
              <tr>
                <th className="p-3">{t("inventoryTransfers.transfer")}</th>
                <th className="p-3">{t("inventoryTransfers.source")}</th>
                <th className="p-3">{t("inventoryTransfers.destination")}</th>
                <th className="p-3">{t("inventoryTransfers.status")}</th>
                <th className="p-3">{t("inventoryTransfers.products")}</th>
                <th className="p-3">{t("inventoryTransfers.totalQuantity")}</th>
                <th className="p-3">{t("inventoryTransfers.createdBy")}</th>
                <th className="p-3">{t("inventoryTransfers.date")}</th>
                <th className="p-3 text-center">{t("inventoryTransfers.actions")}</th>
              </tr>
            </thead>

            <tbody className="divide-y divide-slate-100">
              {items.map((transfer) => {
                const isSource =
                  transfer.source_location_id === locationId;
                const isDestination =
                  transfer.destination_location_id === locationId;

                return (
                  <tr key={transfer.id} className="hover:bg-slate-50/70">
                    <td className="p-3">
                      <div className="font-bold text-slate-800">
                        {transfer.reference_number}
                      </div>
                      <div className="text-xs">{t(`inventoryTransfers.${transfer.transfer_purpose}`, { defaultValue: transfer.transfer_purpose })}</div>
                      <div className="text-[10px] text-slate-400">
                        #{formatTransferNumber(transfer.id)}
                      </div>
                    </td>
                    <td className="p-3">
                      <div className="flex items-center gap-1.5">
                        <ArrowUpFromLine className="w-3.5 h-3.5 text-slate-400" />
                        <span
                          className={
                            isSource
                              ? "font-bold text-blue-700"
                              : "text-slate-600"
                          }
                        >
                          {transfer.source_location_name}
                        </span>
                      </div>
                    </td>
                    <td className="p-3">
                      <div className="flex items-center gap-1.5">
                        <ArrowDownToLine className="w-3.5 h-3.5 text-slate-400" />
                        <span
                          className={
                            isDestination
                              ? "font-bold text-emerald-700"
                              : "text-slate-600"
                          }
                        >
                          {transfer.destination_location_name}
                        </span>
                      </div>
                    </td>
                    <td className="p-3">
                      <span
                        className={`px-2 py-1 rounded-lg text-xs font-bold ${STATUS_META[transfer.status].className}`}
                      >
                        {t(STATUS_META[transfer.status].label)}
                      </span>
                    </td>
                    <td className="p-3 text-slate-600">
                      {formatTransferNumber(transfer.line_count)}
                    </td>
                    <td className="p-3 font-bold text-slate-700">
                      {formatTransferNumber(transfer.total_quantity)}
                    </td>
                    <td className="p-3 text-slate-600">
                      {transfer.dispatched_by_name}
                    </td>
                    <td className="p-3 text-xs text-slate-500">
                      {formatDate(transfer.created_at)}
                    </td>
                    <td className="p-3">
                      <TransferRowActions transfer={transfer} locationId={locationId} can={access.can} onOpenDetail={onOpenDetail} onOpenAction={onOpenAction} />
                    </td>
                  </tr>
                );
              })}

              {!loading && items.length === 0 && (
                <tr>
                  <td
                    colSpan={9}
                    className="p-12 text-center text-slate-400"
                  >{t("inventoryTransfers.empty")}</td>
                </tr>
              )}
            </tbody>
          </table>
          <div className="md:hidden divide-y">
            {items.map(transfer => <article key={transfer.id} className="p-3 space-y-2">
              <div className="flex justify-between gap-2"><strong className="break-all">{transfer.reference_number}</strong><span>{t(STATUS_META[transfer.status].label)}</span></div>
              <dl className="grid grid-cols-2 gap-2 text-xs">
                <div><dt>{t("inventoryTransfers.source")}</dt><dd>{transfer.source_location_name}</dd></div>
                <div><dt>{t("inventoryTransfers.destination")}</dt><dd>{transfer.destination_location_name}</dd></div>
                <div><dt>{t("inventoryTransfers.purpose")}</dt><dd>{t(`inventoryTransfers.${transfer.transfer_purpose}`, { defaultValue: transfer.transfer_purpose })}</dd></div>
                <div><dt>{t("inventoryTransfers.totalQuantity")}</dt><dd>{formatTransferNumber(transfer.total_quantity)}</dd></div>
              </dl>
              <TransferRowActions transfer={transfer} locationId={locationId} can={access.can} onOpenDetail={onOpenDetail} onOpenAction={onOpenAction} />
            </article>)}
            {!loading && items.length === 0 && <p className="p-4">{t("inventoryTransfers.empty")}</p>}
          </div>

        </div>
      </div>

      <div className="flex items-center justify-between">
        <span className="text-xs text-slate-500">
          {t("inventoryTransfers.page", { page: formatTransferNumber(cursorHistoryLength + 1) })}
        </span>

        <div className="flex gap-2">
          <button
            aria-label={t("inventoryTransfers.previous")}
            onClick={onPrevious}
            disabled={cursorHistoryLength === 0 || loading}
            className="px-3 py-2 rounded-xl border border-slate-200 bg-white disabled:opacity-40"
          >
            <ChevronRight className="w-4 h-4" />
          </button>
          <button
            aria-label={t("inventoryTransfers.next")}
            onClick={onNext}
            disabled={!nextCursor || loading}
            className="px-3 py-2 rounded-xl border border-slate-200 bg-white disabled:opacity-40"
          >
            <ChevronLeft className="w-4 h-4" />
          </button>
        </div>
      </div>
    </>
  );
}
