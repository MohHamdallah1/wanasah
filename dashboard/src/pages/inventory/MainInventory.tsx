import { useState, useEffect, useCallback, useRef } from "react";
import { Package, History, Lock, RefreshCcw, FilePlus, Menu } from "lucide-react";
import { toast } from "sonner";
import { Tab1LiveStock } from "./Tab1LiveStock";
import { Tab2Inbound } from "./Tab2Inbound";
import { Tab3Stocktake } from "./Tab3Stocktake";
import { Tab4Ledger } from "./Tab4Ledger";
import type { WarehouseProduct, WarehouseAlert, LedgerEntry } from "./inventoryUtils";

import { useAuthFetch } from "@/hooks/useAuthFetch"; // +++ استدعاء الدستور الموحد +++

// ─── Tab config ───────────────────────────────────────────────────────────────
const TABS = [
  { id: "live", label: "الرصيد الحي", icon: Package },
  { id: "inbound", label: "توريد بضاعة", icon: FilePlus },
  { id: "ledger", label: "سجل الحركات", icon: History },
  { id: "stocktake", label: "جرد وتسوية", icon: Lock },
] as const;

type TabId = typeof TABS[number]["id"];

// ─── Main Component ───────────────────────────────────────────────────────────
export default function MainInventory() {
  const authFetch = useAuthFetch();

  const [activeTab, setActiveTab] = useState<TabId>(() => (localStorage.getItem("inventory_active_tab") as TabId) || "live");
  useEffect(() => { localStorage.setItem("inventory_active_tab", activeTab); }, [activeTab]);
  
  // +++ حالة اختيار المستودع +++
  const [locations, setLocations] = useState<{ id: number, name: string, code: string }[]>([]);
  const [selectedLocationId, setSelectedLocationId] = useState<number | null>(null);
  const [locationError, setLocationError] = useState<boolean>(false); // +++ التفرقة بين فشل الشبكة والمستودع الفارغ +++
  
  const [products, setProducts] = useState<WarehouseProduct[]>([]);
  const [alerts, setAlerts] = useState<WarehouseAlert[]>([]);
  const [ledger, setLedger] = useState<LedgerEntry[]>([]);
  const ledgerFetchedRef = useRef(false); 
  const [isAuditLocked, setIsAuditLocked] = useState<boolean>(true);
  const [loadingStatus, setLoadingStatus] = useState(true);
  const [loadingStock, setLoadingStock] = useState(false);
  const [loadingLedger, setLoadingLedger] = useState(false);
  const [lastSync, setLastSync] = useState<Date>(new Date());

  // جلب المستودعات المتاحة للشركة عند الدخول
  useEffect(() => {
    const fetchLocations = async () => {
      try {
        setLocationError(false);
        const data = await authFetch("/warehouse/locations");
        if (Array.isArray(data) && data.length > 0) {
          setLocations(data);
          setSelectedLocationId(data[0].id); // التحديد التلقائي لأول مستودع متاح
        }
      } catch (e: any) {
        setLocationError(true);
        toast.error("فشل الاتصال بالخادم لجلب المستودعات.");
      }
    };
    fetchLocations();
  }, [authFetch]);

  // ── fetchers ────────────────────────────────────────────────────────────────
  const fetchStock = useCallback(async () => {
    if (!selectedLocationId) return;
    setLoadingStock(true);
    try {
      const data = await authFetch(`/warehouse/inventory?location_id=${selectedLocationId}`);
      if (Array.isArray(data)) {
        setProducts(data);
        setLastSync(new Date()); 
      } else {
        throw new Error("تنسيق بيانات المخزون غير صالح");
      }
    } catch (e: any) {
      toast.error(e.message || "خطأ حرج في جلب المخزون");
      setProducts([]);
    } finally {
      setLoadingStock(false);
    }
  }, [authFetch, selectedLocationId]); // +++ سحق Stale Closure (P0-2) +++

  const fetchAlerts = useCallback(async () => {
    if (!selectedLocationId) return;
    try {
      const data = await authFetch(`/warehouse/alerts?location_id=${selectedLocationId}`);
      if (Array.isArray(data)) {
        setAlerts(data);
        if (data.length > 0) {
          toast.warning(`تنبيه: يوجد ${data.length} منتجات تجاوزت الحد الأدنى للمخزون!`);
        }
      }
    } catch (e: any) {
      console.error("Alerts Fetch Error:", e);
      toast.warning("تنبيه: فشل الاتصال بخدمة التنبيهات");
    }
  }, [authFetch, selectedLocationId]); 

  // جلب حالة القفل للمستودع المحدد فقط دون التأثير على باقي المستودعات.
  const fetchStatus = useCallback(async () => {
    if (!selectedLocationId) {
      setIsAuditLocked(false);
      return;
    }

    setLoadingStatus(true);

    try {
      const data = await authFetch(
        `/warehouse/status?location_id=${selectedLocationId}`
      );

      if (data) {
        setIsAuditLocked(data.status === "AUDIT_LOCK");
      }
    } catch (e: any) {
      toast.error(
        "خطأ حرج: تعذر التأكد من حالة قفل المستودع المحدد."
      );
      setIsAuditLocked(true);
    } finally {
      setLoadingStatus(false);
    }
  }, [authFetch, selectedLocationId]);

  const fetchLedger = useCallback(async (force = false) => {
    if (!selectedLocationId) return;
    if (!force && ledgerFetchedRef.current) return;
    setLoadingLedger(true);
    try {
      const data = await authFetch(`/warehouse/ledger?location_id=${selectedLocationId}`);
      if (Array.isArray(data)) {
        setLedger(data);
        ledgerFetchedRef.current = true;
      }
    } catch (e: any) {
      toast.error(e.message || "خطأ في جلب السجل");
      setLedger([]);
    } finally {
      setLoadingLedger(false);
    }
  }, [authFetch, selectedLocationId]); // +++ سحق Stale Closure (P0-2) +++

  // ── on mount ────────────────────────────────────────────────────────────────
  useEffect(() => {
    fetchStatus();
  }, [fetchStatus]);

  // جلب المخزون فور توفر المستودع
  useEffect(() => {
    if (selectedLocationId) {
      ledgerFetchedRef.current = false; // إعادة طلب السجل للمستودع الجديد
      fetchStock();
      fetchAlerts();
      if (activeTab === "ledger") fetchLedger();
    }
  }, [selectedLocationId, fetchStock, fetchAlerts, fetchLedger, activeTab]);

  // +++ الدرع المعماري (P2 Fixed): حماية الشاشة البيضاء في حال انعدام المواقع (مع استثناء فشل الشبكة) +++
  if (!loadingStatus && locations.length === 0 && !locationError) {
    return (
      <div className="flex flex-col items-center justify-center h-full w-full bg-slate-50/50 rounded-3xl border border-slate-200 p-8 text-center animate-in fade-in duration-500">
        <div className="w-24 h-24 bg-blue-100 text-blue-600 rounded-full flex items-center justify-center mb-6 shadow-inner">
          <Package className="w-10 h-10" />
        </div>
        <h2 className="text-2xl font-black text-slate-800 mb-2">لا توجد مستودعات متاحة</h2>
        <p className="text-slate-500 font-bold max-w-md">
          لم يتم العثور على أي مستودعات فعالة لشركتك. يرجى التواصل مع الدعم الفني أو تحديث الصفحة لتوليد المستودع الرئيسي تلقائياً.
        </p>
        <button onClick={() => window.location.reload()} className="mt-8 px-6 py-3 bg-blue-600 hover:bg-blue-700 text-white font-bold rounded-xl shadow-lg transition-all active:scale-95 flex items-center gap-2">
          <RefreshCcw className="w-5 h-5" /> تحديث النظام
        </button>
      </div>
    );
  }

  // ─── UI ─────────────────────────────────────────────────────────────────────
  return (
    <div className="flex flex-col gap-4 w-full h-full flex-1 min-h-0 animate-in fade-in duration-200">

      {/* ═══ Tab Bar ═══ */}
      {/* +++ الكي الجراحي: إضافة الارتفاع h-16 md:h-20 وتدوير الزوايا rounded-2xl ليطابق البار الرئيسي +++ */}
      <nav className="glass-card h-16 md:h-20 rounded-2xl px-3 md:px-6 py-2 flex items-center justify-between gap-1">
        <div className="flex items-center gap-1">
          {TABS.map(({ id, label, icon: Icon }) => {
            const active = activeTab === id;
            return (
              <button
                key={id}
                onClick={() => setActiveTab(id)}
                className={`flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-semibold transition-all ${active
                  ? "bg-blue-500 text-white shadow-md shadow-blue-500/20"
                  : "text-slate-600 hover:text-slate-800 hover:bg-white/60"
                  }`}
              >
                <Icon className="w-4 h-4" />
                <span className="hidden sm:inline">{label}</span>
              </button>
            );
          })}
        </div>

        {/* +++ الحقن المعماري: نقل معلومات الرصيد الحي، وقت التحديث، وزر التحديث الكامل للبار العلوي +++ */}
        <div className="flex items-center gap-4 px-2">
          {/* +++ محدد المستودعات +++ */}
          {locations.length > 0 && (
            <select
              className="bg-slate-50 border border-slate-200 text-slate-700 text-xs font-bold rounded-lg px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-blue-500"
              value={selectedLocationId || ""}
              onChange={(e) => setSelectedLocationId(Number(e.target.value))}
            >
              {locations.map(loc => (
                <option key={loc.id} value={loc.id}>
                  {loc.name}
                </option>
              ))}
            </select>
          )}

          <div className="flex flex-col items-end border-l border-slate-200 pl-4 justify-center">
            <div className="flex items-center gap-2">
              <Package className="w-4 h-4 text-[#1e87bb]" />
              <span className="text-sm font-black text-slate-700">
                الرصيد الحي — <span className="text-[#1e87bb]">{products.length}</span> صنف
              </span>
              {isAuditLocked && (
                <span className="text-[10px] font-bold text-amber-600 bg-amber-50 px-2 py-0.5 rounded-md border border-amber-200">
                  مقفل 🔒
                </span>
              )}
            </div>
            <span className="text-[10px] font-bold text-slate-400 mt-0.5">
              آخر تحديث: {lastSync.toLocaleTimeString("ar-EG")}
            </span>
          </div>
          <button
            onClick={() => { fetchStock(); fetchStatus(); fetchAlerts(); }}
            disabled={loadingStock}
            className="flex items-center gap-1.5 px-3 py-2 bg-white border border-slate-200 text-xs font-bold text-slate-600 rounded-xl hover:bg-slate-50 hover:text-[#1e87bb] hover:border-[#1e87bb]/30 transition-all shadow-sm disabled:opacity-50 active:scale-95"
          >
            <RefreshCcw className={`w-3.5 h-3.5 ${loadingStock ? "animate-spin" : ""}`} />
            تحديث
          </button>
        </div>
      </nav>

      {/* ═══ Tab Content ═══ */}
      <div className="flex-1 min-h-0 flex flex-col">
        {activeTab === "live" && (
          <Tab1LiveStock
            products={products}
            alerts={alerts}
            loading={loadingStock}
            // +++ الكي الجراحي: عند ضغط زر التحديث من داخل الجدول، نحدث النواقص والمخزون معاً +++
            onRefresh={() => { fetchStock(); fetchAlerts(); }}
          />
        )}
        {activeTab === "inbound" && selectedLocationId && (
          <Tab2Inbound
            products={products}
            locationId={selectedLocationId} // +++ تمرير الموقع لعملية الإدخال +++
            authenticatedFetch={authFetch}
            onSuccess={async () => {
              await Promise.all([
                fetchStock(),
                fetchAlerts(),
                fetchLedger(true)
              ]);
            }}
          />
        )}
        {activeTab === "stocktake" && selectedLocationId && (
          <Tab3Stocktake
            products={products}
            locationId={selectedLocationId} // +++ سحق ملاحظة P1: تمرير الموقع للمحرك המوحد +++
            isAuditLocked={isAuditLocked}
            authenticatedFetch={authFetch}
            onLockChange={async (locked) => {
              setIsAuditLocked(locked);
              // +++  (I-09): إجبار مسح الكاش وتحديث دفتر الأستاذ (Ledger) بعد الجرد +++
              ledgerFetchedRef.current = false;
              await Promise.all([fetchStock(), fetchAlerts(), fetchLedger(true)]);
            }}
          />
        )}
        {activeTab === "ledger" && (
          <Tab4Ledger
            entries={ledger}
            loading={loadingLedger}
            // +++   تمرير دالة التحديث للابن لمنع الريفرش الإجباري +++
            onRefresh={() => fetchLedger(true)}
          />
        )}
      </div>
    </div>
  );
}
