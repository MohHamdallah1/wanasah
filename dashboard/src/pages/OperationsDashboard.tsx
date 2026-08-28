import { useState, useEffect, useMemo, useCallback, useRef } from "react";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { getFleetStats } from "@/data/operations-data";
import type { DriverData } from "@/data/operations-data";
import { PulseBar } from "@/components/operations/PulseBar";
import { toast } from "sonner";
import { FleetRadar } from "@/components/operations/FleetRadar";
import { CommandCenter } from "@/components/operations/CommandCenter";
import { SettlementModal } from "@/components/operations/SettlementModal";
import { motion, AnimatePresence } from "framer-motion";

import { AlertTriangle, RotateCcw, X, PackageOpen, BarChart3, TrendingUp } from "lucide-react";

// +++ المكون المعماري الجديد: نافذة تفاصيل المبيعات (Modern Light Glassmorphism) +++
const SalesDetailsModal = ({ isOpen, onClose, productSales, totalLogisticsCartons }: { isOpen: boolean, onClose: () => void, productSales: any[], totalLogisticsCartons: number }) => {
  if (!isOpen) return null;
  
  const getCartonWord = (n: number) => n === 1 ? "كرتونة" : n === 2 ? "كرتونتان" : (n >= 3 && n <= 10) ? "كراتين" : "كرتونة";

  return (
    <AnimatePresence>
      <div className="fixed inset-0 z-[100] flex items-center justify-center p-4 md:p-6" dir="rtl">
        {/* خلفية ضبابية ناعمة */}
        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="absolute inset-0 bg-slate-900/40 backdrop-blur-sm" onClick={onClose} />
        
        {/* هيكل النافذة الزجاجي الفاتح */}
        <motion.div initial={{ opacity: 0, scale: 0.95, y: 20 }} animate={{ opacity: 1, scale: 1, y: 0 }} exit={{ opacity: 0, scale: 0.95, y: 20 }} className="relative w-full max-w-5xl max-h-[90vh] flex flex-col bg-white/95 backdrop-blur-xl border border-white shadow-2xl rounded-[2rem] overflow-hidden">
          
          {/* رأس النافذة الأنيق */}
          <div className="flex items-center justify-between p-6 border-b border-slate-100 bg-slate-50/50">
            <div className="flex items-center gap-4">
              <div className="w-12 h-12 rounded-2xl bg-blue-50 border border-blue-100 flex items-center justify-center shadow-sm">
                <BarChart3 className="w-6 h-6 text-blue-600" />
              </div>
              <div>
                <h2 className="text-xl font-black text-slate-800 tracking-wide">التحليل اللوجستي للمبيعات</h2>
                <p className="text-sm text-slate-500 font-medium mt-1">إجمالي الحجم المنقول: {totalLogisticsCartons} {getCartonWord(totalLogisticsCartons)} صحيحة</p>
              </div>
            </div>
            <button onClick={onClose} className="p-2.5 bg-slate-100 hover:bg-red-50 text-slate-400 hover:text-red-500 rounded-xl transition-all duration-300">
              <X className="w-5 h-5" />
            </button>
          </div>

          {/* محتوى المنتجات (Grid Cards) */}
          <div className="flex-1 overflow-y-auto p-6 custom-scrollbar bg-slate-50/30">
            {productSales.length === 0 ? (
              <div className="h-full flex flex-col items-center justify-center text-slate-400">
                <PackageOpen className="w-16 h-16 mb-4 opacity-20" />
                <p className="text-lg font-bold">لا توجد مبيعات مسجلة حتى الآن</p>
              </div>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
                {productSales.map((prod, idx) => (
                  <motion.div 
                    initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: idx * 0.05 }}
                    key={prod.id} 
                    className="group bg-white border border-slate-200 hover:border-blue-300 hover:shadow-lg rounded-2xl p-5 transition-all duration-300"
                  >
                    <div className="flex justify-between items-start mb-4">
                      <h3 className="text-base font-bold text-slate-800 line-clamp-1">{prod.name}</h3>
                      <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-emerald-50 border border-emerald-100">
                        <TrendingUp className="w-3.5 h-3.5 text-emerald-600" />
                        <span className="text-xs font-bold text-emerald-700">{prod.packsPerCarton} ح/ك</span>
                      </div>
                    </div>

                    <div className="grid grid-cols-2 gap-3 mt-2">
                      <div className="bg-slate-50 rounded-xl p-3 border border-slate-100">
                        <p className="text-[10px] text-slate-400 font-bold mb-1 uppercase tracking-wider">كراتين صحيحة</p>
                        <p className="text-2xl font-black text-slate-800 tabular-nums">{prod.soldCartons}</p>
                      </div>
                      <div className="bg-blue-50/50 rounded-xl p-3 border border-blue-50">
                        <p className="text-[10px] text-slate-400 font-bold mb-1 uppercase tracking-wider">حبات فرط</p>
                        <p className="text-2xl font-black text-blue-600 tabular-nums">{prod.soldLoose}</p>
                      </div>
                    </div>
                    
                    <div className="mt-4">
                      <div className="flex justify-between text-[10px] text-slate-400 font-bold mb-1.5">
                        <span>إجمالي القطع: {prod.totalPacks}</span>
                        <span>{Math.round((prod.soldLoose / prod.packsPerCarton) * 100)}% لتقفيل كرتونة</span>
                      </div>
                      <div className="h-1.5 w-full bg-slate-100 rounded-full overflow-hidden">
                        <div className="h-full bg-blue-500 rounded-full" style={{ width: `${(prod.soldLoose / prod.packsPerCarton) * 100}%` }} />
                      </div>
                    </div>
                  </motion.div>
                ))}
              </div>
            )}
          </div>
        </motion.div>
      </div>
    </AnimatePresence>
  );
};

const Index = () => {
  const authFetch = useAuthFetch(); 
  const [drivers, setDrivers] = useState<DriverData[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [isSettlementModalOpen, setIsSettlementModalOpen] = useState(false);
  const [undoSessionId, setUndoSessionId] = useState<number | null>(null);
  
  // +++ تحكم نافذة المبيعات التفصيلية +++
  const [isSalesModalOpen, setIsSalesModalOpen] = useState(false);

  // +++ استخراج الدالة وتغليفها بـ useCallback لتكون متاحة للتحديث الفوري (Instant UI Update) +++
  const fetchLiveOperations = useCallback(async (isMounted = true) => {
    try {
      const data = await authFetch("/admin/sessions/today");
      if (data && isMounted) {
        // +++  للـ Mutation: استخدام Deep Copy مع احترام Immutability +++
        const formattedData = data.map((d: any) => {
          let localTime = d.session?.start_time;
          if (localTime) {
            const utcDate = new Date(localTime);
            localTime = utcDate.toLocaleTimeString('ar-EG', { hour: '2-digit', minute: '2-digit', hour12: true });
          }
          
          return {
            ...d,
            session: {
              ...d.session,
              start_time: localTime // حقل جديد بدون المساس بالكائن الأصلي
            }
          };
        });
        
        setDrivers(formattedData);
      }
    } catch (error: any) {
      console.error("فشل الاتصال بالسيرفر:", error);
      // +++ E-03: إظهار إشعار للمستخدم عند فشل التحديث الصامت (مع تجاهل 401 لأنه يعالج بالتوجيه) +++
      if (error?.status !== 401) toast.error("حدث خطأ أثناء تحديث بيانات غرفة العمليات");
      throw error; // H-04: Re-throw so the polling loop increments backoff on failure
    }
  }, [authFetch]);

  // H-04: Adaptive polling with exponential backoff, jitter, and visibility awareness
  const POLL_BASE_MS = 30_000;
  const POLL_MAX_MS = 120_000;
  const attemptRef = useRef(0);

  const scheduleNextPoll = useCallback((fn: () => void, attempt: number) => {
    const backoff = Math.min(POLL_BASE_MS * Math.pow(2, attempt), POLL_MAX_MS);
    // Add ±15% jitter to prevent server thundering herd
    const jitter = backoff * 0.15 * (Math.random() * 2 - 1);
    return setTimeout(fn, backoff + jitter);
  }, []);

  useEffect(() => {
    let isMounted = true;
    let timerId: ReturnType<typeof setTimeout>;

    const poll = async (attempt: number) => {
      try {
        await fetchLiveOperations(isMounted);
        // Reset backoff on success (unless the tab is hidden)
        if (document.visibilityState === 'visible') {
          attemptRef.current = 0;
        }
      } catch {
        // Increase backoff on failure (capped)
        attemptRef.current = Math.min(attemptRef.current + 1, 3);
      }

      if (isMounted) {
        timerId = scheduleNextPoll(() => poll(attemptRef.current), attemptRef.current);
      }
    };

    // Reset backoff and immediately poll when tab becomes visible
    const handleVisibility = () => {
      if (document.visibilityState === 'visible') {
        attemptRef.current = 0;
        clearTimeout(timerId);
        if (isMounted) {
          timerId = scheduleNextPoll(() => poll(0), 0);
        }
      }
    };

    document.addEventListener('visibilitychange', handleVisibility);

    poll(0); // initial poll

    return () => {
      isMounted = false;
      clearTimeout(timerId);
      document.removeEventListener('visibilitychange', handleVisibility);
    };
  }, [fetchLiveOperations, scheduleNextPoll]);

  const stats = getFleetStats(drivers);
  const selectedDriver = drivers.find((d) => d.session.session_id === selectedId) ?? null;

  // +++ المحرك المحاسبي الصاروخي (O(N)): حساب المبيعات لكل منتج بشكل مستقل لحل مشكلة اختلاف أحجام الكراتين +++
  const aggregatedSales = useMemo(() => {
    const productMap: Record<number, any> = {};
    let totalLogisticsCartons = 0;

    drivers.forEach(driver => {
      // نتحقق من وجود بيانات المستودع في الجلسة أو التسوية
      const inventory = driver.settlement?.inventory || [];
      inventory.forEach((item: any) => {
        // نأخذ الكمية المباعة سواء من sold_quantity أو من الحقول المفصلة
        const soldPacks = item.sold_quantity || ((item.sold_cartons || 0) * (item.packs_per_carton || 1) + (item.sold_loose_packs || 0));
        
        if (soldPacks > 0) {
          if (!productMap[item.product_id]) {
            productMap[item.product_id] = {
              id: item.product_id,
              name: item.product_name,
              totalPacks: 0,
              packsPerCarton: item.packs_per_carton || 1
            };
          }
          productMap[item.product_id].totalPacks += soldPacks;
        }
      });
    });

    const productSales = Object.values(productMap).map(prod => {
      const soldCartons = Math.floor(prod.totalPacks / prod.packsPerCarton);
      const soldLoose = prod.totalPacks % prod.packsPerCarton;
      totalLogisticsCartons += soldCartons; // نجمع الكراتين الصحيحة فقط للمؤشر اللوجستي
      return { ...prod, soldCartons, soldLoose };
    });

    // ترتيب المنتجات الأكثر مبيعاً أولاً
    productSales.sort((a, b) => b.soldCartons - a.soldCartons);

    return { productSales, totalLogisticsCartons };
  }, [drivers]);

  // --- متغيرات النظام العامة (يسهل ربطها بالـ API لاحقاً) ---
  const GLOBAL_CURRENCY = "د.أ"; 

  // دالة زر الضوء الأخضر (مُحصنة بـ authFetch)
  const handleToggleAuth = async (id: number) => {
    if (id < 0) {
      toast.error("لا يمكن إعطاء صلاحية البيع لمندوب لم يبدأ دوامه الفعلي من التطبيق.");
      return;
    }
    const driver = drivers.find((d) => d.session.session_id === id);
    if (!driver) return;
    const newAuthStatus = !driver.session.is_authorized_to_sell;

    // تحديث الواجهة فورياً (Optimistic UI)
    setDrivers((prev) => prev.map((d) => d.session.session_id === id ? { ...d, session: { ...d.session, is_authorized_to_sell: newAuthStatus } } : d));

    try {
      // +++  لطبقة الاتصال: استخدام الهوك الموحد لمنع كراش الـ Token Expiration +++
      const response = await authFetch(`/admin/sessions/${id}/authorize`, {
        method: 'PUT',
        body: JSON.stringify({ is_authorized: newAuthStatus, inventory: [] })
      });
      if (!response) throw new Error('فشل في تحديث الصلاحية من السيرفر');
    } catch (error) {
      // تراجع عن التحديث في حال الفشل
      setDrivers((prev) => prev.map((d) => d.session.session_id === id ? { ...d, session: { ...d.session, is_authorized_to_sell: !newAuthStatus } } : d));
      toast.error("حدث خطأ أثناء الاتصال بالسيرفر");
    }
  };

  // دالة تأكيد التسوية (مُحصنة)
  const handleConfirmSettlement = async (actualCash: number, inventoryJard: any[], notes: string) => {
    if (!selectedDriver) return;
    try {
      const response = await authFetch(`/admin/sessions/${selectedDriver.session.session_id}/settle`, {
        method: 'PUT',
        body: JSON.stringify({ actual_cash: actualCash, inventory_jard: inventoryJard, notes: notes })
      });
      if (!response) throw new Error('فشل الاعتماد من الخادم');

      toast.success(`تم اعتماد تسوية ${selectedDriver.session.driver_name} وإغلاق العهدة بنجاح!`);
      setIsSettlementModalOpen(false);
      fetchLiveOperations();
    } catch (error: any) {
      // +++ E-08: منع ظهور رسالة فارغة (Undefined) عند رمي أخطاء غير قياسية +++
      toast.error(error?.message || (typeof error === 'string' ? error : "حدث خطأ غير معروف أثناء التسوية"));
    }
  };

  // دالة التراجع عن إنهاء العمل (مُحصنة)
  const handleUndoEndWork = async () => {
    if (!undoSessionId) return;
    try {
      const res = await authFetch(`/dispatch/session/${undoSessionId}/undo_end_work`, {
        method: "PUT"
      });
      if (res) {
        toast.success("تم التراجع بنجاح. يمكن للمندوب متابعة عمله.");
        fetchLiveOperations();
      } else {
        throw new Error("حدث خطأ أثناء التراجع.");
      }
    } catch (error: any) {
      toast.error(error.message || "خطأ في الاتصال بالسيرفر");
    } finally {
      setUndoSessionId(null);
    }
  };

  return (
    <div className="w-full flex flex-col gap-4 animate-in fade-in duration-500">

      <PulseBar
        totalCash={stats.totalCash}
        cashFromSales={stats.cashFromSales}
        cashFromDebts={stats.cashFromDebts}
        // +++ استبدال الغباء المحاسبي بالرقم اللوجستي الصحيح 100% +++
        totalSoldCartons={aggregatedSales.totalLogisticsCartons}
        completedVisits={stats.completedVisits}
        totalVisits={stats.totalVisits}
        activeDrivers={stats.activeDrivers}
        onBreakDrivers={stats.onBreakDrivers}
        // +++ تفعيل زر العين السري +++
        onOpenSalesDetails={() => setIsSalesModalOpen(true)}
      />

      {/* زرع النافذة المنبثقة للتحليل اللوجستي */}
      <SalesDetailsModal 
        isOpen={isSalesModalOpen} 
        onClose={() => setIsSalesModalOpen(false)} 
        productSales={aggregatedSales.productSales}
        totalLogisticsCartons={aggregatedSales.totalLogisticsCartons}
      />

      <div className="flex flex-col lg:flex-row gap-4 flex-1">
        <div className="lg:flex-[65] min-w-0">
          <FleetRadar
            drivers={drivers}
            selectedId={selectedId}
            onSelect={setSelectedId}
            onToggleAuth={handleToggleAuth}
            searchQuery={searchQuery}
            onSearchChange={setSearchQuery}
          />
        </div>
        <div className="lg:flex-[35] min-w-0">
        <CommandCenter
            // +++   إجبار المترجم على قبول هيكل السيرفر الحقيقي بدل الهيكل الوهمي القديم +++
            driver={selectedDriver as any}
            onApproveSettlement={() => setIsSettlementModalOpen(true)}
            onUndoEndWork={() => {
              if (!selectedDriver) return;
              setUndoSessionId(selectedDriver.session.session_id);
            }}
          />
        </div>
      </div>

      <SettlementModal
        isOpen={isSettlementModalOpen}
        onClose={() => setIsSettlementModalOpen(false)}
        driver={selectedDriver}
        onConfirmSettlement={handleConfirmSettlement}
      />

      {/* ═══ Custom Undo Confirmation Modal ═══ */}
      {undoSessionId !== null && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4" dir="rtl">
          <div
            className="absolute inset-0 bg-slate-900/50 backdrop-blur-sm"
            onClick={() => setUndoSessionId(null)}
          />
          <div className="relative z-10 w-full max-w-md bg-white rounded-2xl shadow-2xl overflow-hidden animate-in fade-in zoom-in-95 duration-200">
            <div className="flex items-center gap-3 px-6 pt-6 pb-4 border-b border-slate-100">
              <div className="flex-shrink-0 w-10 h-10 rounded-xl bg-amber-100 flex items-center justify-center">
                <AlertTriangle className="w-5 h-5 text-amber-600" />
              </div>
              <div>
                <h2 className="text-base font-bold text-slate-800">تأكيد إعادة فتح الجلسة</h2>
                <p className="text-xs text-slate-400 mt-0.5">هذا الإجراء يتطلب موافقة إدارية</p>
              </div>
            </div>
            <div className="px-6 py-5">
              <p className="text-sm text-slate-600 leading-relaxed">
                هل أنت متأكد من <span className="font-bold text-amber-700">إعادة فتح الجلسة المالية</span> وإعادة المندوب لحالة نشط؟
              </p>
              <p className="text-xs text-red-500 mt-3 bg-red-50 border border-red-100 rounded-lg px-3 py-2">
                ⚠️ سيتمكن المندوب من مواصلة تسجيل المبيعات بعد هذا الإجراء.
              </p>
            </div>
            <div className="flex items-center gap-3 px-6 pb-6">
              <button
                onClick={() => setUndoSessionId(null)}
                className="flex-1 py-2.5 rounded-xl border border-slate-200 text-slate-600 text-sm font-bold hover:bg-slate-50 transition-all"
              >
                إلغاء
              </button>
              <button
                onClick={handleUndoEndWork}
                className="flex-1 py-2.5 rounded-xl bg-amber-500 text-white text-sm font-bold hover:bg-amber-600 transition-all shadow-lg shadow-amber-500/25 flex items-center justify-center gap-2"
              >
                <RotateCcw className="w-4 h-4" />
                نعم، إعادة الفتح
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default Index;