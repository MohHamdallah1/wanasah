import {
  Boxes,
  Car,
  ClipboardCheck,
  RefreshCcw,
} from "lucide-react";
import type {
  StocktakeSessionSummary,
  StocktakeStatus,
  StocktakeType,
} from "./types";

interface StocktakeSessionCenterProps {
  sessions: StocktakeSessionSummary[];
  total: number | null;
  loading: boolean;
  loadingMore: boolean;
  nextCursor: string | null;
  currentSessionId: number | null;
  onRefresh: () => void;
  onStartCycle: () => void;
  cycleStartDisabled: boolean;
  vehicleStartDisabled: boolean;
  onStartVehicleRecon: () => void;
  onLoadMore: () => void;
  onOpenSession: (
    session: StocktakeSessionSummary
  ) => void | Promise<void>;
}

const TYPE_LABELS: Record<StocktakeType, string> = {
  FULL_COUNT: "جرد شامل",
  CYCLE_COUNT: "جرد دوري",
  VEHICLE_RECON: "تسوية سيارة",
};

const STATUS_LABELS: Record<StocktakeStatus, string> = {
  DRAFT: "مسودة",
  COUNTING: "قيد العد",
  PENDING_REVIEW: "بانتظار المراجعة",
  RECOUNT_REQUIRED: "إعادة عد مطلوبة",
  APPROVED: "معتمد",
  POSTED: "مرحّل",
  CANCELLED: "ملغى",
};

const STATUS_CLASS: Record<StocktakeStatus, string> = {
  DRAFT: "bg-slate-100 text-slate-600",
  COUNTING: "bg-amber-50 text-amber-700",
  PENDING_REVIEW: "bg-blue-50 text-blue-700",
  RECOUNT_REQUIRED: "bg-red-50 text-red-700",
  APPROVED: "bg-emerald-50 text-emerald-700",
  POSTED: "bg-emerald-50 text-emerald-700",
  CANCELLED: "bg-slate-100 text-slate-500",
};

const canOpenSession = (
  status: StocktakeStatus
): boolean =>
  status === "COUNTING" ||
  status === "PENDING_REVIEW" ||
  status === "RECOUNT_REQUIRED";

const sessionScope = (
  session: StocktakeSessionSummary
): string => {
  if (session.stocktake_type === "FULL_COUNT") {
    return "الموقع كاملاً";
  }

  if (session.stocktake_type === "VEHICLE_RECON") {
    return session.related_work_session_id
      ? `جلسة عمل #${session.related_work_session_id}`
      : "جلسة عمل غير محددة";
  }

  const product =
    session.scope_product_name ||
    `الصنف #${session.scope_product_variant_id ?? "—"}`;

  return session.scope_batch_number
    ? `${product} · دفعة ${session.scope_batch_number}`
    : product;
};

export function StocktakeSessionCenter({
  sessions,
  total,
  loading,
  loadingMore,
  nextCursor,
  currentSessionId,
  onRefresh,
  onStartCycle,
  cycleStartDisabled,
  vehicleStartDisabled,
  onStartVehicleRecon,
  onLoadMore,
  onOpenSession,
}: StocktakeSessionCenterProps) {
  return (
    <section className="glass-card inventory-data-panel rounded-2xl border border-slate-200 overflow-hidden shrink-0">
      <div className="inventory-panel-toolbar px-4 py-3 flex items-center justify-between gap-3 bg-white/70">
        <div className="flex items-center gap-2">
          <ClipboardCheck className="w-4 h-4 text-[#1e87bb]" />
          <div>
            <h3 className="text-sm font-black text-slate-800">
              جلسات الجرد النشطة
            </h3>
            <p className="text-[10px] text-slate-500 mt-0.5">
              {total !== null
                ? `${total} جلسة نشطة في الموقع`
                : "المصدر: السيرفر"}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            disabled={vehicleStartDisabled}
            onClick={onStartVehicleRecon}
            className="px-3 py-2 rounded-lg bg-violet-600 text-white text-xs font-black"
            title="تسوية عهدة سيارة مرتبطة بجلسة عمل منتهية"
          >
            + تسوية سيارة
          </button>

          <button
            type="button"
            onClick={onStartCycle}
            disabled={cycleStartDisabled}
            className="px-3 py-2 rounded-lg bg-blue-600 text-white text-xs font-black disabled:opacity-40 disabled:cursor-not-allowed"
            title={cycleStartDisabled ? "الجرد الدوري غير متاح أثناء القفل الشامل" : "بدء جرد دوري لصنف أو دفعة"}
          >
            + جرد دوري
          </button>

        <button
          type="button"
          onClick={onRefresh}
          disabled={loading}
          className="p-2 rounded-lg border border-slate-200 bg-white text-slate-500 hover:text-[#1e87bb] disabled:opacity-50"
          title="تحديث الجلسات"
        >
          <RefreshCcw
            className={`w-4 h-4 ${
              loading ? "animate-spin" : ""
            }`}
          />
        </button>
        </div>
      </div>

      {loading && sessions.length === 0 ? (
        <div className="px-4 py-5 text-xs text-slate-400 text-center">
          جاري جلب الجلسات النشطة...
        </div>
      ) : sessions.length === 0 ? (
        <div className="px-4 py-4 text-xs text-slate-400 text-center border-t border-slate-100">
          لا توجد جلسات جرد نشطة لهذا الموقع.
        </div>
      ) : (
        <div className="border-t border-slate-100">
          <div className="max-h-48 overflow-auto divide-y divide-slate-100">
            {sessions.map((session) => {
              const selected =
                currentSessionId === session.id;
              const TypeIcon =
                session.stocktake_type === "VEHICLE_RECON"
                  ? Car
                  : Boxes;

              return (
                <div
                  key={session.id}
                  className={`px-4 py-3 flex items-center justify-between gap-4 ${
                    selected
                      ? "bg-blue-50/60"
                      : "bg-white hover:bg-slate-50/70"
                  }`}
                >
                  <div className="flex items-center gap-3 min-w-0">
                    <div className="w-9 h-9 rounded-xl bg-slate-100 flex items-center justify-center shrink-0">
                      <TypeIcon className="w-4 h-4 text-slate-600" />
                    </div>

                    <div className="min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-xs font-black text-slate-800">
                          {TYPE_LABELS[session.stocktake_type]}
                        </span>
                        <span
                          className={`text-[10px] font-bold px-2 py-0.5 rounded-md ${
                            STATUS_CLASS[session.status]
                          }`}
                        >
                          {STATUS_LABELS[session.status]}
                        </span>
                        {session.pending_independent_recount_required && (
                          <span className="text-[10px] font-bold px-2 py-0.5 rounded-md bg-red-100 text-red-700">
                            عد مستقل مطلوب
                          </span>
                        )}
                      </div>

                      <div className="text-[11px] text-slate-500 mt-1 truncate">
                        {session.reference_number} ·{" "}
                        {sessionScope(session)} · بدأها{" "}
                        {session.started_by_name}
                      </div>
                    </div>
                  </div>

                  <button
                    type="button"
                    disabled={
                      !canOpenSession(session.status) ||
                      selected
                    }
                    onClick={() =>
                      void onOpenSession(session)
                    }
                    className="px-3 py-1.5 rounded-lg text-xs font-black border border-slate-200 bg-white text-slate-700 hover:border-blue-300 hover:text-blue-700 disabled:opacity-40 disabled:cursor-not-allowed shrink-0"
                  >
                    {selected ? "مفتوحة" : "فتح"}
                  </button>
                </div>
              );
            })}
          </div>

          {nextCursor && (
            <div className="p-2 border-t border-slate-100">
              <button
                type="button"
                onClick={onLoadMore}
                disabled={loadingMore}
                className="w-full py-2 rounded-lg text-xs font-bold text-blue-700 bg-blue-50 hover:bg-blue-100 disabled:opacity-50"
              >
                {loadingMore
                  ? "جاري تحميل المزيد..."
                  : "تحميل المزيد"}
              </button>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
