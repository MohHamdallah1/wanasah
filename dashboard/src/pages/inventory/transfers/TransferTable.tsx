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
    <div className="flex min-h-0 flex-1 flex-col" data-cp13-transfer-list="true">
      <div className="min-h-0 flex-1 overflow-auto">
        <table className="hidden min-w-[1120px] w-full text-sm md:table" aria-busy={loading}>
          <thead className="sticky top-0 z-10 border-b border-slate-200 bg-slate-50/95 backdrop-blur">
            <tr>
              <th className="px-3 py-2 text-start text-[11px] font-black text-slate-500">{t("inventoryTransfers.transfer")}</th>
              <th className="px-3 py-2 text-start text-[11px] font-black text-slate-500">{t("inventoryTransfers.source")}</th>
              <th className="px-3 py-2 text-start text-[11px] font-black text-slate-500">{t("inventoryTransfers.destination")}</th>
              <th className="px-3 py-2 text-start text-[11px] font-black text-slate-500">{t("inventoryTransfers.purpose")}</th>
              <th className="px-3 py-2 text-start text-[11px] font-black text-slate-500">{t("inventoryTransfers.status")}</th>
              <th className="px-3 py-2 text-start text-[11px] font-black text-slate-500">{t("inventoryTransfers.products")}</th>
              <th className="px-3 py-2 text-start text-[11px] font-black text-slate-500">{t("inventoryTransfers.createdBy")}</th>
              <th className="px-3 py-2 text-start text-[11px] font-black text-slate-500">{t("inventoryTransfers.date")}</th>
              <th className="px-3 py-2 text-center text-[11px] font-black text-slate-500">{t("inventoryTransfers.actions")}</th>
            </tr>
          </thead>

          <tbody className="divide-y divide-slate-100">
            {items.map((transfer) => {
              const isSource = transfer.source_location_id === locationId;
              const isDestination = transfer.destination_location_id === locationId;

              return (
                <tr key={transfer.id} className="align-middle hover:bg-slate-50/70" data-cp13-transfer-row="compact">
                  <td className="px-3 py-2">
                    <div className="font-black text-slate-900">{transfer.reference_number}</div>
                    <div className="mt-0.5 text-[10px] font-semibold tabular-nums text-slate-400">
                      #{formatTransferNumber(transfer.id)}
                    </div>
                  </td>
                  <td className="px-3 py-2">
                    <div className="flex items-center gap-1.5">
                      <ArrowUpFromLine className="h-3.5 w-3.5 shrink-0 text-slate-400" aria-hidden="true" />
                      <span className={isSource ? "font-black text-blue-700" : "font-semibold text-slate-600"}>
                        {transfer.source_location_name}
                      </span>
                    </div>
                  </td>
                  <td className="px-3 py-2">
                    <div className="flex items-center gap-1.5">
                      <ArrowDownToLine className="h-3.5 w-3.5 shrink-0 text-slate-400" aria-hidden="true" />
                      <span className={isDestination ? "font-black text-emerald-700" : "font-semibold text-slate-600"}>
                        {transfer.destination_location_name}
                      </span>
                    </div>
                  </td>
                  <td className="px-3 py-2 text-xs font-bold text-slate-700" data-cp13-transfer-purpose={transfer.transfer_purpose}>
                    {t(`inventoryTransfers.${transfer.transfer_purpose}`, { defaultValue: transfer.transfer_purpose })}
                  </td>
                  <td className="px-3 py-2">
                    <span
                      className={`inline-flex items-center gap-1 rounded-md border px-2 py-1 text-[10px] font-black ${STATUS_META[transfer.status].className}`}
                      data-cp13-transfer-status={transfer.status}
                    >
                      <span className="h-1.5 w-1.5 rounded-full bg-current" aria-hidden="true" />
                      {t(STATUS_META[transfer.status].label)}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-xs text-slate-600">
                    <div className="font-black text-slate-800">
                      {formatTransferNumber(transfer.line_count)} {t("inventoryTransfers.products")}
                    </div>
                    <div className="mt-0.5 text-[10px] font-semibold tabular-nums text-slate-500" dir="ltr">
                      {formatTransferNumber(transfer.total_quantity)} · {t("inventoryTransfers.totalQuantity")}
                    </div>
                  </td>
                  <td className="px-3 py-2 text-xs font-semibold text-slate-600">
                    {transfer.dispatched_by_name}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-[10px] font-semibold text-slate-500" dir="ltr">
                    {formatDate(transfer.created_at)}
                  </td>
                  <td className="px-3 py-2">
                    <TransferRowActions
                      transfer={transfer}
                      locationId={locationId}
                      can={access.can}
                      onOpenDetail={onOpenDetail}
                      onOpenAction={onOpenAction}
                    />
                  </td>
                </tr>
              );
            })}

            {loading && items.length === 0 ? (
              <tr>
                <td colSpan={9} className="p-8 text-center text-sm font-bold text-slate-400" role="status" data-cp13-state="loading">
                  {t("inventoryTransfers.loading")}
                </td>
              </tr>
            ) : null}

            {!loading && items.length === 0 ? (
              <tr>
                <td colSpan={9} className="p-8 text-center text-sm font-semibold text-slate-400" data-cp13-state="empty">
                  {t("inventoryTransfers.empty")}
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>

        <div className="divide-y divide-slate-100 md:hidden" data-cp13-phone-list="true">
          {items.map((transfer) => (
            <article key={transfer.id} className="space-y-2 p-2.5" data-cp13-transfer-card="compact">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <strong className="block truncate text-sm text-slate-900">{transfer.reference_number}</strong>
                  <span className="mt-0.5 block truncate text-[10px] font-bold text-slate-500">
                    {t(`inventoryTransfers.${transfer.transfer_purpose}`, { defaultValue: transfer.transfer_purpose })}
                  </span>
                </div>
                <span className={`inline-flex shrink-0 items-center gap-1 rounded-md border px-2 py-1 text-[10px] font-black ${STATUS_META[transfer.status].className}`}>
                  <span className="h-1.5 w-1.5 rounded-full bg-current" aria-hidden="true" />
                  {t(STATUS_META[transfer.status].label)}
                </span>
              </div>

              <dl className="grid grid-cols-2 gap-x-3 gap-y-1.5 border-y border-slate-100 py-2 text-[10px]">
                <div className="min-w-0">
                  <dt className="font-bold text-slate-400">{t("inventoryTransfers.source")}</dt>
                  <dd className="mt-0.5 truncate font-black text-slate-700">{transfer.source_location_name}</dd>
                </div>
                <div className="min-w-0">
                  <dt className="font-bold text-slate-400">{t("inventoryTransfers.destination")}</dt>
                  <dd className="mt-0.5 truncate font-black text-slate-700">{transfer.destination_location_name}</dd>
                </div>
                <div>
                  <dt className="font-bold text-slate-400">{t("inventoryTransfers.products")}</dt>
                  <dd className="mt-0.5 font-black tabular-nums text-slate-700">{formatTransferNumber(transfer.line_count)}</dd>
                </div>
                <div>
                  <dt className="font-bold text-slate-400">{t("inventoryTransfers.totalQuantity")}</dt>
                  <dd className="mt-0.5 font-black tabular-nums text-slate-700" dir="ltr">{formatTransferNumber(transfer.total_quantity)}</dd>
                </div>
              </dl>

              <TransferRowActions
                transfer={transfer}
                locationId={locationId}
                can={access.can}
                onOpenDetail={onOpenDetail}
                onOpenAction={onOpenAction}
              />
            </article>
          ))}

          {loading && items.length === 0 ? (
            <p role="status" className="p-6 text-center text-sm font-bold text-slate-400" data-cp13-state="loading">
              {t("inventoryTransfers.loading")}
            </p>
          ) : null}
          {!loading && items.length === 0 ? (
            <p className="p-6 text-center text-sm font-semibold text-slate-400" data-cp13-state="empty">
              {t("inventoryTransfers.empty")}
            </p>
          ) : null}
        </div>
      </div>

      <div className="flex items-center justify-between border-t border-slate-100 bg-slate-50/60 px-3 py-2" data-cp13-continuation="cursor">
        <span className="text-[10px] font-bold text-slate-500">
          {t("inventoryTransfers.page", { page: formatTransferNumber(cursorHistoryLength + 1) })}
        </span>

        <div className="flex gap-1.5">
          <button
            type="button"
            aria-label={t("inventoryTransfers.previous")}
            onClick={onPrevious}
            disabled={cursorHistoryLength === 0 || loading}
            className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-slate-200 bg-white outline-none disabled:opacity-40 focus-visible:ring-2 focus-visible:ring-blue-300"
          >
            <ChevronRight className="h-3.5 w-3.5" aria-hidden="true" />
          </button>
          <button
            type="button"
            aria-label={t("inventoryTransfers.next")}
            onClick={onNext}
            disabled={!nextCursor || loading}
            className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-slate-200 bg-white outline-none disabled:opacity-40 focus-visible:ring-2 focus-visible:ring-blue-300"
          >
            <ChevronLeft className="h-3.5 w-3.5" aria-hidden="true" />
          </button>
        </div>
      </div>
    </div>
  );
}
