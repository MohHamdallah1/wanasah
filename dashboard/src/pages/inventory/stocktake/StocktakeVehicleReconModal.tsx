import {
  Car,
  Search,
} from "lucide-react";
import { Modal } from "@/components/ui/modal";
import type { VehicleReconStartController } from "./hooks/useVehicleReconStart";

interface StocktakeVehicleReconModalProps {
  open: boolean;
  controller: VehicleReconStartController;
  onClose: () => void;
  onOpened: () => void;
}

const STATUS_LABEL: Record<string, string> = {
  DRAFT: "مسودة",
  COUNTING: "قيد العد",
  PENDING_REVIEW: "بانتظار المراجعة",
  RECOUNT_REQUIRED: "إعادة عد مطلوبة",
  APPROVED: "معتمد",
  POSTED: "مرحّل",
};

export function StocktakeVehicleReconModal({
  open,
  controller,
  onClose,
  onOpened,
}: StocktakeVehicleReconModalProps) {
  const {
    searchInput,
    setSearchInput,
    items,
    nextCursor,
    loading,
    loadingMore,
    busyWorkSessionId,
    notes,
    setNotes,
    loadMore,
    startOrOpen,
  } = controller;

  const handleCandidate = async (
    workSessionId: number
  ) => {
    const candidate = items.find(
      (item) =>
        item.work_session_id ===
        workSessionId
    );
    if (!candidate) return;

    if (await startOrOpen(candidate)) {
      onOpened();
    }
  };

  return (
    <Modal
      isOpen={open}
      onClose={onClose}
      title="تسوية عهدة سيارة"
      maxWidth="max-w-5xl"
    >
      <div className="space-y-4">
        <div className="rounded-xl border border-violet-100 bg-violet-50 p-4 text-sm font-bold text-violet-800">
          تظهر فقط جلسات العمل المنتهية وغير المسواة مخزنياً، والمرتبطة بسيارات خرجت من المستودع المحدد. التسوية المالية تبقى مساراً مستقلاً.
        </div>

        <div className="relative">
          <Search className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
          <input
            value={searchInput}
            onChange={(event) =>
              setSearchInput(
                event.target.value
              )
            }
            maxLength={100}
            placeholder="ابحث باسم المندوب أو اسم/كود السيارة..."
            className="w-full rounded-xl border border-slate-200 bg-white pr-10 pl-3 py-2.5 text-sm outline-none focus:ring-2 focus:ring-violet-500/20"
          />
        </div>

        <div className="max-h-[420px] overflow-auto rounded-xl border border-slate-200 divide-y divide-slate-100">
          {items.map((item) => {
            const existing =
              item
                .existing_stocktake_session_id !==
              null;
            const busy =
              busyWorkSessionId ===
              item.work_session_id;

            return (
              <div
                key={item.work_session_id}
                className="p-4 bg-white flex flex-col md:flex-row md:items-center justify-between gap-4"
              >
                <div className="flex items-start gap-3 min-w-0">
                  <div className="w-10 h-10 rounded-xl bg-violet-50 flex items-center justify-center shrink-0">
                    <Car className="w-5 h-5 text-violet-600" />
                  </div>

                  <div className="min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-black text-slate-800">
                        {item.vehicle_location_name}
                      </span>
                      <span className="text-[10px] font-bold px-2 py-0.5 rounded-md bg-slate-100 text-slate-600">
                        {item.vehicle_location_code}
                      </span>
                      {existing && (
                        <span className="text-[10px] font-bold px-2 py-0.5 rounded-md bg-amber-50 text-amber-700">
                          جرد مفتوح:{" "}
                          {STATUS_LABEL[
                            item.existing_stocktake_status ??
                              ""
                          ] ??
                            item.existing_stocktake_status}
                        </span>
                      )}
                    </div>

                    <div className="text-xs text-slate-500 mt-1">
                      المندوب:{" "}
                      <span className="font-bold text-slate-700">
                        {item.driver_name}
                      </span>
                      {" · "}
                      جلسة #{item.work_session_id}
                      {" · "}
                      {item.session_date}
                    </div>

                    <div className="text-[11px] text-slate-400 mt-1">
                      انتهت: {item.end_time}
                      {item
                        .existing_stocktake_reference
                        ? ` · ${item.existing_stocktake_reference}`
                        : ""}
                    </div>
                  </div>
                </div>

                <button
                  type="button"
                  disabled={
                    busyWorkSessionId !== null
                  }
                  onClick={() =>
                    void handleCandidate(
                      item.work_session_id
                    )
                  }
                  className="px-4 py-2 rounded-xl bg-violet-600 hover:bg-violet-700 disabled:bg-slate-300 text-white text-xs font-black shrink-0"
                >
                  {busy
                    ? "جاري الفتح..."
                    : existing
                      ? "فتح الجرد المفتوح"
                      : "بدء تسوية السيارة"}
                </button>
              </div>
            );
          })}

          {loading &&
            items.length === 0 && (
              <div className="p-8 text-center text-sm text-slate-400">
                جاري جلب جلسات السيارات...
              </div>
            )}

          {!loading &&
            items.length === 0 && (
              <div className="p-8 text-center text-sm text-slate-400">
                لا توجد جلسات عمل منتهية تحتاج تسوية مخزنية لهذا المستودع.
              </div>
            )}
        </div>

        {nextCursor && (
          <button
            type="button"
            onClick={loadMore}
            disabled={loadingMore}
            className="w-full py-2.5 rounded-xl bg-violet-50 text-violet-700 text-xs font-black disabled:opacity-50"
          >
            {loadingMore
              ? "جاري تحميل المزيد..."
              : "تحميل المزيد"}
          </button>
        )}

        <div>
          <label className="text-xs font-black text-slate-700">
            ملاحظات التسوية (اختياري)
          </label>
          <textarea
            value={notes}
            onChange={(event) =>
              setNotes(event.target.value)
            }
            maxLength={4000}
            className="mt-1 w-full min-h-20 rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm outline-none"
          />
        </div>
      </div>
    </Modal>
  );
}
