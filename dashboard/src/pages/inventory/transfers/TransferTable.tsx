import {
  ArrowDownToLine,
  ArrowUpFromLine,
  Ban,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Eye,
  XCircle,
} from "lucide-react";
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
  return (
    <>
      <div className="glass-card rounded-2xl overflow-hidden min-h-0 flex-1">
        <div className="overflow-auto h-full">
          <table className="w-full text-sm text-right">
            <thead className="bg-slate-50 sticky top-0 z-10">
              <tr>
                <th className="p-3">الحوالة</th>
                <th className="p-3">المصدر</th>
                <th className="p-3">الوجهة</th>
                <th className="p-3">الحالة</th>
                <th className="p-3">الأصناف</th>
                <th className="p-3">إجمالي العبوات</th>
                <th className="p-3">أنشأها</th>
                <th className="p-3">التاريخ</th>
                <th className="p-3 text-center">إجراءات</th>
              </tr>
            </thead>

            <tbody className="divide-y divide-slate-100">
              {items.map((transfer) => {
                const isSource =
                  transfer.source_location_id === locationId;
                const isDestination =
                  transfer.destination_location_id === locationId;
                const inTransit = transfer.status === "IN_TRANSIT";

                return (
                  <tr key={transfer.id} className="hover:bg-slate-50/70">
                    <td className="p-3">
                      <div className="font-bold text-slate-800">
                        {transfer.reference_number}
                      </div>
                      <div className="text-[10px] text-slate-400">
                        ID: {transfer.id}
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
                        {STATUS_META[transfer.status].label}
                      </span>
                    </td>
                    <td className="p-3 text-slate-600">
                      {transfer.line_count}
                    </td>
                    <td className="p-3 font-bold text-slate-700">
                      {transfer.total_quantity}
                    </td>
                    <td className="p-3 text-slate-600">
                      {transfer.dispatched_by_name}
                    </td>
                    <td className="p-3 text-xs text-slate-500">
                      {formatDate(transfer.created_at)}
                    </td>
                    <td className="p-3">
                      <div className="flex justify-center gap-1.5">
                        <button
                          onClick={() => void onOpenDetail(transfer)}
                          className="p-2 rounded-lg border border-slate-200 text-slate-600 hover:text-blue-600"
                          title="التفاصيل"
                        >
                          <Eye className="w-4 h-4" />
                        </button>

                        {inTransit && isDestination && (
                          <>
                            <button
                              onClick={() =>
                                onOpenAction(transfer, "receive")
                              }
                              className="p-2 rounded-lg border border-emerald-200 text-emerald-600 hover:bg-emerald-50"
                              title="استلام"
                            >
                              <CheckCircle2 className="w-4 h-4" />
                            </button>
                            <button
                              onClick={() =>
                                onOpenAction(transfer, "reject")
                              }
                              className="p-2 rounded-lg border border-red-200 text-red-600 hover:bg-red-50"
                              title="رفض"
                            >
                              <XCircle className="w-4 h-4" />
                            </button>
                          </>
                        )}

                        {inTransit && isSource && (
                          <button
                            onClick={() =>
                              onOpenAction(transfer, "cancel")
                            }
                            className="p-2 rounded-lg border border-amber-200 text-amber-600 hover:bg-amber-50"
                            title="إلغاء"
                          >
                            <Ban className="w-4 h-4" />
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}

              {!loading && items.length === 0 && (
                <tr>
                  <td
                    colSpan={9}
                    className="p-12 text-center text-slate-400"
                  >
                    لا توجد حوالات ضمن النطاق المحدد.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div className="flex items-center justify-between">
        <span className="text-xs text-slate-500">
          الصفحة {cursorHistoryLength + 1}
        </span>

        <div className="flex gap-2">
          <button
            onClick={onPrevious}
            disabled={cursorHistoryLength === 0 || loading}
            className="px-3 py-2 rounded-xl border border-slate-200 bg-white disabled:opacity-40"
          >
            <ChevronRight className="w-4 h-4" />
          </button>
          <button
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
