import { Truck, UserMinus, Clock, AlertTriangle, CircleStop } from "lucide-react";
import { PendingRoute } from "@/types/dispatch";

interface PendingRoutesTableProps {
  routes: PendingRoute[];
  onOpenRouteModal: (route: PendingRoute, type: "follow_up" | "transfer") => void;
  onPostponeRoute: (id: string) => void;
  onCloseZone: (route: PendingRoute) => void;
  onForceWithdraw: (route: PendingRoute) => void;
  getDriverShortages: (driverId: string) => number;
}

export function PendingRoutesTable({
  routes,
  onOpenRouteModal,
  onPostponeRoute,
  onCloseZone,
  onForceWithdraw,
  getDriverShortages,
}: PendingRoutesTableProps) {
  if (routes.length === 0) {
    return <p className="text-sm text-slate-500 p-6 text-center">لا توجد مناطق معلقة حالياً.</p>;
  }

  return (
    <div className="bg-white rounded-2xl border border-slate-200 overflow-y-auto max-h-[45vh] divide-y divide-slate-100 shadow-sm">
      {routes.map((route) => {
        const driverShortageCount = getDriverShortages(route.driverId);
        return (
          <div
            key={route.id}
            className="flex flex-row justify-between items-center p-4 hover:bg-slate-50 transition-all group"
          >
            <div className="flex items-center gap-4">
              <div className="w-10 h-10 rounded-xl bg-emerald-50 flex items-center justify-center">
                <Truck className="w-5 h-5 text-[#1e87bb]" />
              </div>
              <div className="flex items-center gap-2">
                <h3 className="font-bold text-slate-800 text-base">{route.zoneName}</h3>
                <span className="text-slate-300">|</span>
                <p className="text-sm text-slate-500 font-medium">المندوب: {route.driverName}</p>
                {driverShortageCount > 0 && (
                  <span className="text-[10px] bg-amber-500 text-white px-2 py-0.5 rounded-full font-bold animate-pulse">
                    +{driverShortageCount} طلبية خارجية
                  </span>
                )}
                <span className="text-slate-300">|</span>
                <p className="text-sm text-amber-600 font-bold">متبقي {route.shopsRemaining} محلات</p>
                {route.status === "active" && (
                  <span className="flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-emerald-100 text-[#1e87bb] text-[10px] font-bold border border-emerald-200">
                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
                    🟢 قيد العمل
                  </span>
                )}
              </div>
            </div>
            <div className="flex items-center gap-2">
              {route.shopsRemaining === 0 ? (
                <button 
                  onClick={() => onCloseZone(route)} 
                  className="w-full bg-emerald-500 text-white px-4 py-2 rounded-xl text-xs font-bold hover:bg-emerald-600 transition-colors flex items-center justify-center gap-2 shadow-lg animate-pulse"
                >
                  إغلاق وتصفير المنطقة ✅
                </button>
              ) : route.status === "waiting" ? (
                <>
                  <button
                    onClick={() => onOpenRouteModal(route, "follow_up")}
                    className="px-4 py-2 rounded-xl bg-[#1e87bb] text-white text-xs font-bold hover:bg-[#0f766e] transition-colors shadow-sm"
                  >
                    متابعة الحمولة
                  </button>
                  <button
                    onClick={() => onOpenRouteModal(route, "transfer")}
                    className="px-4 py-2 rounded-xl border border-slate-200 bg-white text-slate-600 text-xs font-bold hover:bg-slate-50 transition-colors flex items-center gap-2"
                  >
                    <UserMinus className="w-3.5 h-3.5" />
                    تحويل لمندوب آخر
                  </button>
                  <button
                    onClick={() => onPostponeRoute(route.id)}
                    className="px-4 py-2 rounded-xl border border-slate-200 bg-white text-slate-600 text-xs font-bold hover:bg-slate-50 transition-colors flex items-center gap-2"
                  >
                    <Clock className="w-3.5 h-3.5" />
                    تأجيل للغد 🕒
                  </button>
                  <button
                    onClick={() => onCloseZone(route)}
                    className="px-4 py-2 rounded-xl border border-red-200 text-red-500 text-xs font-bold hover:bg-red-50 transition-colors flex items-center gap-2"
                  >
                    <AlertTriangle className="w-3.5 h-3.5" />
                    إغلاق وتصفير
                  </button>
                </>
              ) : (
                <button
                  onClick={() => onForceWithdraw(route)}
                  className="px-6 py-2 rounded-xl border border-red-200 bg-red-50 text-red-600 text-xs font-bold hover:bg-red-600 hover:text-white transition-all flex items-center gap-2 shadow-sm"
                >
                  <CircleStop className="w-4 h-4" />
                  🛑 إيقاف وسحب المنطقة
                </button>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
