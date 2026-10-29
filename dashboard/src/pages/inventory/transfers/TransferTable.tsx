import { useEffect, useMemo, useRef } from "react";
import { ArrowDownToLine, ArrowUpFromLine } from "lucide-react";
import { useLocationCapabilities } from "@/hooks/useInventoryAccess";
import { useTransferTranslation as useTranslation, formatTransferNumber } from "./i18n";
import { TransferRowActions } from "./TransferRowActions";
import { STATUS_META } from "./constants";
import type { TransferAction, WarehouseTransferListItem } from "./types";
import { formatDate } from "./utils";

interface TransferTableProps {
  items: WarehouseTransferListItem[];
  loading: boolean;
  loadingMore: boolean;
  hasMore: boolean;
  onLoadMore: () => void;
  onOpenDetail: (transfer: WarehouseTransferListItem) => void | Promise<void>;
  onOpenAction: (transfer: WarehouseTransferListItem, action: TransferAction) => void;
}

export function TransferTable({
  items,
  loading,
  loadingMore,
  hasMore,
  onLoadMore,
  onOpenDetail,
  onOpenAction,
}: TransferTableProps) {
  const { t } = useTranslation();
  const locationIds = useMemo(() => [...new Set(items.flatMap((transfer) => [transfer.source_location_id, transfer.destination_location_id]))], [items]);
  const canAt = useLocationCapabilities(locationIds);
  const scrollRef = useRef<HTMLDivElement>(null);
  const sentinelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const root = scrollRef.current;
    const sentinel = sentinelRef.current;
    if (!root || !sentinel || !hasMore || loading || loadingMore || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) onLoadMore();
    }, { root, rootMargin: "500px 0px", threshold: 0 });
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [hasMore, loading, loadingMore, onLoadMore]);

  return (
    <div className="flex min-h-0 flex-1 flex-col" data-cp13-transfer-list="true">
      <div ref={scrollRef} className="min-h-0 flex-1 overflow-auto">
        <table className="hidden min-w-[1120px] w-full text-sm md:table" aria-busy={loading || loadingMore}>
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
            {items.map((transfer) => (
              <tr key={transfer.id} className="align-middle hover:bg-slate-50/70" data-cp13-transfer-row="compact">
                <td className="px-3 py-2">
                  <div className="font-black text-slate-900">{transfer.reference_number}</div>
                  <div className="mt-0.5 text-[10px] font-semibold tabular-nums text-slate-400">#{formatTransferNumber(transfer.id)}</div>
                </td>
                <td className="px-3 py-2">
                  <div className="flex items-center gap-1.5">
                    <ArrowUpFromLine className="h-3.5 w-3.5 shrink-0 text-slate-400" aria-hidden="true" />
                    <span className="font-semibold text-slate-700">{transfer.source_location_name}</span>
                  </div>
                </td>
                <td className="px-3 py-2">
                  <div className="flex items-center gap-1.5">
                    <ArrowDownToLine className="h-3.5 w-3.5 shrink-0 text-slate-400" aria-hidden="true" />
                    <span className="font-semibold text-slate-700">{transfer.destination_location_name}</span>
                  </div>
                </td>
                <td className="px-3 py-2 text-xs font-bold text-slate-700" data-cp13-transfer-purpose={transfer.transfer_purpose}>
                  {t(`inventoryTransfers.${transfer.transfer_purpose}`, { defaultValue: transfer.transfer_purpose })}
                </td>
                <td className="px-3 py-2">
                  <span className={`inline-flex items-center gap-1 rounded-md border px-2 py-1 text-[10px] font-black ${STATUS_META[transfer.status].className}`} data-cp13-transfer-status={transfer.status}>
                    <span className="h-1.5 w-1.5 rounded-full bg-current" aria-hidden="true" />
                    {t(STATUS_META[transfer.status].label)}
                  </span>
                </td>
                <td className="px-3 py-2 text-xs text-slate-600">
                  <div className="font-black text-slate-800">{formatTransferNumber(transfer.line_count)} {t("inventoryTransfers.products")}</div>
                  <div className="mt-0.5 text-[10px] font-semibold tabular-nums text-slate-500" dir="ltr">
                    {formatTransferNumber(transfer.total_quantity)} · {t("inventoryTransfers.totalQuantity")}
                  </div>
                </td>
                <td className="px-3 py-2 text-xs font-semibold text-slate-600">{transfer.dispatched_by_name}</td>
                <td className="whitespace-nowrap px-3 py-2 text-[10px] font-semibold text-slate-500" dir="ltr">{formatDate(transfer.created_at)}</td>
                <td className="px-3 py-2">
                  <TransferRowActions transfer={transfer} canAt={canAt} onOpenDetail={onOpenDetail} onOpenAction={onOpenAction} />
                </td>
              </tr>
            ))}
            {loading && items.length === 0 ? (
              <tr><td colSpan={9} className="p-8 text-center text-sm font-bold text-slate-400" role="status" data-cp13-state="loading">{t("inventoryTransfers.loading")}</td></tr>
            ) : null}
            {!loading && items.length === 0 ? (
              <tr><td colSpan={9} className="p-8 text-center text-sm font-semibold text-slate-400" data-cp13-state="empty">{t("inventoryTransfers.empty")}</td></tr>
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
                <div className="min-w-0"><dt className="font-bold text-slate-400">{t("inventoryTransfers.source")}</dt><dd className="mt-0.5 truncate font-black text-slate-700">{transfer.source_location_name}</dd></div>
                <div className="min-w-0"><dt className="font-bold text-slate-400">{t("inventoryTransfers.destination")}</dt><dd className="mt-0.5 truncate font-black text-slate-700">{transfer.destination_location_name}</dd></div>
                <div><dt className="font-bold text-slate-400">{t("inventoryTransfers.products")}</dt><dd className="mt-0.5 font-black tabular-nums text-slate-700">{formatTransferNumber(transfer.line_count)}</dd></div>
                <div><dt className="font-bold text-slate-400">{t("inventoryTransfers.totalQuantity")}</dt><dd className="mt-0.5 font-black tabular-nums text-slate-700" dir="ltr">{formatTransferNumber(transfer.total_quantity)}</dd></div>
              </dl>
              <TransferRowActions transfer={transfer} canAt={canAt} onOpenDetail={onOpenDetail} onOpenAction={onOpenAction} />
            </article>
          ))}
          {loading && items.length === 0 ? <p role="status" className="p-6 text-center text-sm font-bold text-slate-400">{t("inventoryTransfers.loading")}</p> : null}
          {!loading && items.length === 0 ? <p className="p-6 text-center text-sm font-semibold text-slate-400">{t("inventoryTransfers.empty")}</p> : null}
        </div>

        <div ref={sentinelRef} className="flex min-h-10 items-center justify-center py-2 text-[11px] font-bold text-slate-400" data-transfer-scroll-sentinel="true">
          {loadingMore ? <span role="status">{t("inventoryTransfers.moreLoading")}</span> : hasMore ? <span>{t("inventoryTransfers.scrollMore")}</span> : items.length ? <span>{t("inventoryTransfers.end")}</span> : null}
        </div>
      </div>
    </div>
  );
}
