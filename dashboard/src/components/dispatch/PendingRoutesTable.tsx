import { Truck, UserMinus, Clock, AlertTriangle, CircleStop, Package, Radar, Lock } from "lucide-react";
import { PendingRoute } from "@/types/dispatch";

// DASHBOARD_DISPATCH_ROUTE_CONTRACT_V3
interface PendingRoutesTableProps {
  routes: PendingRoute[];
  onOpenRouteModal: (route: PendingRoute, type: "follow_up" | "transfer") => void;
  onPostponeRoute: (id: string) => void;
  onCloseZone: (route: PendingRoute) => void;
  onForceWithdraw: (route: PendingRoute) => void;
  driverShortagesMap: Record<string, number>;
  onAdjustInventory: (route: PendingRoute) => void;
  onOpenRadar: (route: PendingRoute) => void;
}

export function PendingRoutesTable({
  routes,
  onOpenRouteModal,
  onPostponeRoute,
  onCloseZone,
  onForceWithdraw,
  driverShortagesMap,
  onAdjustInventory,
  onOpenRadar,
}: PendingRoutesTableProps) {
  if (routes.length === 0) {
    return <p className="text-sm text-slate-500 p-6 text-center">لا توجد خطوط سير تشغيلية حالياً.</p>;
  }

  const renderActionButtons = (route: PendingRoute) => {
    const radarButton = (
      <button
        key="radar-btn"
        onClick={() => onOpenRadar(route)}
        className="px-4 py-2 rounded-xl border border-blue-200 bg-blue-50 text-blue-600 text-xs font-bold hover:bg-blue-600 hover:text-white transition-all flex items-center gap-2 shadow-sm"
        title="رادار المصافحات"
      >
        <Radar className="w-4 h-4" />
      </button>
    );

    if (route.shopsRemaining === 0) {
      return (
        <>
          {radarButton}
          <button
            onClick={() => onCloseZone(route)}
            className="w-full bg-emerald-500 text-white px-4 py-2 rounded-xl text-xs font-bold hover:bg-emerald-600 transition-colors flex items-center justify-center gap-2 shadow-lg"
          >
            إغلاق خط السير ✅
          </button>
        </>
      );
    }

    if (route.sessionEnded) {
      return (
        <>
          {radarButton}
          <span
            className="px-3 py-2 rounded-xl border border-slate-200 bg-slate-50 text-slate-500 text-[10px] font-bold flex items-center gap-1.5"
            title="هوية العهدة لا تتغير بعد ربط WorkSession"
          >
            <Lock className="w-3.5 h-3.5" />
            WorkSession منتهية
          </span>
          <button
            onClick={() => onPostponeRoute(route.id)}
            className="px-4 py-2 rounded-xl border border-amber-200 text-amber-600 text-xs font-bold hover:bg-amber-50 transition-colors flex items-center gap-2 shadow-sm"
          >
            <Clock className="w-3.5 h-3.5" /> تأجيل المنطقة ⏸️
          </button>
          <button
            onClick={() => onCloseZone(route)}
            className="px-4 py-2 rounded-xl border border-red-200 text-red-500 text-xs font-bold hover:bg-red-50 transition-colors flex items-center gap-2 shadow-sm"
          >
            <AlertTriangle className="w-3.5 h-3.5" /> إغلاق خط السير
          </button>
        </>
      );
    }

    if (route.status === "waiting") {
      return (
        <>
          {radarButton}
          <button
            onClick={() => onOpenRouteModal(route, "follow_up")}
            className="px-4 py-2 rounded-xl bg-[#1e87bb] text-white text-xs font-bold hover:bg-[#0f766e] transition-colors shadow-sm"
          >
            {route.sessionBound ? "استئناف نفس الخط" : "متابعة الحمولة"}
          </button>
          {!route.sessionBound && (
            <button
              onClick={() => onOpenRouteModal(route, "transfer")}
              className="px-4 py-2 rounded-xl border border-slate-200 bg-white text-slate-600 text-xs font-bold hover:bg-slate-50 transition-colors flex items-center gap-2"
            >
              <UserMinus className="w-3.5 h-3.5" /> تحويل لمندوب آخر
            </button>
          )}
          <button
            onClick={() => onPostponeRoute(route.id)}
            className="px-4 py-2 rounded-xl border border-slate-200 bg-white text-slate-600 text-xs font-bold hover:bg-slate-50 transition-colors flex items-center gap-2"
          >
            <Clock className="w-3.5 h-3.5" /> تأجيل المنطقة ⏸️
          </button>
          <button
            onClick={() => onCloseZone(route)}
            className="px-4 py-2 rounded-xl border border-red-200 text-red-500 text-xs font-bold hover:bg-red-50 transition-colors flex items-center gap-2"
          >
            <AlertTriangle className="w-3.5 h-3.5" /> إغلاق خط السير
          </button>
        </>
      );
    }

    return (
      <>
        {radarButton}
        <button
          onClick={() => onAdjustInventory(route)}
          className="px-4 py-2 rounded-xl border border-emerald-200 bg-emerald-50 text-emerald-600 text-xs font-bold hover:bg-emerald-600 hover:text-white transition-all flex items-center gap-2 shadow-sm"
        >
          <Package className="w-4 h-4" /> تعديل الحمولة
        </button>
        <button
          onClick={() => onForceWithdraw(route)}
          className="px-6 py-2 rounded-xl border border-red-200 bg-red-50 text-red-600 text-xs font-bold hover:bg-red-600 hover:text-white transition-all flex items-center gap-2 shadow-sm"
        >
          <CircleStop className="w-4 h-4" /> إيقاف مؤقت
        </button>
      </>
    );
  };

  return (
    <div className="bg-white rounded-2xl border border-slate-200 overflow-y-auto max-h-[45vh] divide-y divide-slate-100 shadow-sm custom-scrollbar">
      {routes.map((route) => {
        const driverShortageCount = driverShortagesMap[route.driverId] || 0;

        return (
          <div
            key={route.id}
            className="flex flex-row justify-between items-center p-4 hover:bg-slate-50 transition-all group"
          >
            <div className="flex items-center gap-4">
              <div className="w-10 h-10 rounded-xl bg-emerald-50 flex items-center justify-center">
                <Truck className="w-5 h-5 text-[#1e87bb]" />
              </div>
              <div className="flex items-center gap-2 flex-wrap">
                <h3 className="font-bold text-slate-800 text-base">{route.zoneName}</h3>
                <span className="text-slate-300">|</span>
                <p className="text-sm text-slate-500 font-medium">المندوب: {route.driverName}</p>

                {driverShortageCount > 0 && (
                  <span className="text-[10px] bg-amber-500 text-white px-2 py-0.5 rounded-full font-bold animate-pulse">
                    +{driverShortageCount} طلبات عاجلة
                  </span>
                )}

                <span className="text-slate-300">|</span>
                <p className="text-sm text-amber-600 font-bold">متبقي {route.shopsRemaining} محلات</p>

                {route.status === "active" && !route.sessionEnded && (
                  <span className="flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-emerald-100 text-[#1e87bb] text-[10px] font-bold border border-emerald-200">
                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
                    🟢 قيد العمل
                  </span>
                )}
              </div>
            </div>

            <div className="flex items-center gap-2">
              {renderActionButtons(route)}
            </div>
          </div>
        );
      })}
    </div>
  );
}
