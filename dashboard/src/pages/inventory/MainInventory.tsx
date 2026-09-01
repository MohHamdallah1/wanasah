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

  // +++ الكي الجراحي: قراءة التبويب الأخير من الذاكرة، وحفظه فور تغييره +++
  const [activeTab, setActiveTab] = useState<TabId>(() => (localStorage.getItem("inventory_active_tab") as TabId) || "live");
  useEffect(() => { localStorage.setItem("inventory_active_tab", activeTab); }, [activeTab]);
  const [products, setProducts] = useState<WarehouseProduct[]>([]);
  const [alerts, setAlerts] = useState<WarehouseAlert[]>([]);
  const [ledger, setLedger] = useState<LedgerEntry[]>([]);
  const ledgerFetchedRef = useRef(false); // +++ درع حماية الـ IO لمنع التكرار (Caching) +++
  const [isAuditLocked, setIsAuditLocked] = useState<boolean>(true);
  const [loadingStatus, setLoadingStatus] = useState(true);
  const [loadingStock, setLoadingStock] = useState(false);
  const [loadingLedger, setLoadingLedger] = useState(false);
  // +++ الكي الجراحي: حالة وقت التحديث للبار العلوي +++
  const [lastSync, setLastSync] = useState<Date>(new Date());

  // ── fetchers ────────────────────────────────────────────────────────────────
  const fetchStock = useCallback(async () => {
    setLoadingStock(true);
    try {
      // +++  استلام البيانات الجاهزة من الـ Hook الموحد +++
      const data = await authFetch("/warehouse/inventory");
      if (Array.isArray(data)) {
        setProducts(data);
        setLastSync(new Date()); // +++ تحديث الوقت اللحظي +++
      } else {
        throw new Error("تنسيق بيانات المخزون غير صالح");
      }
    } catch (e: any) {
      toast.error(e.message || "خطأ حرج في جلب المخزون");
      setProducts([]);
    } finally {
      setLoadingStock(false);
    }
  }, [authFetch]);

  const fetchAlerts = useCallback(async () => {
    try {
      const data = await authFetch("/warehouse/alerts");
      if (Array.isArray(data)) {
        setAlerts(data);
        // +++  (I-10): تفعيل نظام الإشعارات لنواقص المستودع +++
        if (data.length > 0) {
          toast.warning(`تنبيه: يوجد ${data.length} منتجات تجاوزت الحد الأدنى للمخزون!`);
        }
      }
    } catch (e: any) {
      console.error("Alerts Fetch Error:", e);
      toast.warning("تنبيه: فشل الاتصال بخدمة التنبيهات");
    }
  }, [authFetch]);

  const fetchStatus = useCallback(async () => {
    setLoadingStatus(true);
    try {
      const data = await authFetch("/warehouse/status");
      if (data) {
        setIsAuditLocked(data.status === "AUDIT_LOCK");
      }
    } catch (e: any) {
      toast.error("خطأ حرج: تعذر التأكد من حالة قفل المستودع. تم تعطيل العمليات لضمان الأمان.");
      setIsAuditLocked(true); // +++ إغلاق المستودع إجبارياً لحماية البيانات +++
    } finally {
      setLoadingStatus(false);
    }
  }, [authFetch]);

  const fetchLedger = useCallback(async (force = false) => {
    if (!force && ledgerFetchedRef.current) return;
    setLoadingLedger(true);
    try {
      const data = await authFetch("/warehouse/ledger");
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
  }, [authFetch]);

  // ── on mount ────────────────────────────────────────────────────────────────
  useEffect(() => {
    fetchStatus();
    fetchStock();
    fetchAlerts();
  }, [fetchStatus, fetchStock, fetchAlerts]);

  useEffect(() => {
    if (activeTab === "ledger" && !ledgerFetchedRef.current) {
      fetchLedger();
    }
  }, [activeTab, fetchLedger]);

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
        {activeTab === "inbound" && (
          <Tab2Inbound
            products={products}
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
        {activeTab === "stocktake" && (
          <Tab3Stocktake
            products={products}
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
