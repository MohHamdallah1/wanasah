import { Radar, CheckCircle2, RotateCcw, Eye, Package, Banknote, Search } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { useState } from "react";
import { Modal } from "@/components/ui/modal";

// --- الدروع الصارمة (Strict Interfaces) ---
interface DriverVisits {
  completed: number;
  pending: number;
}

interface Financials {
  cash_from_sales: number;
  cash_from_debts: number;
  expected_cash_in_hand: number;
}

interface InventoryItem {
  product_id: number | string;
  product_name: string;
  packs_per_carton: number;
  starting_quantity: number;
  sold_quantity: number;
  remaining_quantity: number; 
}

interface Settlement {
  status: string;
  financials: Financials; 
  inventory: InventoryItem[];
}

export interface ActiveDriver {
  session: {
    session_id: number;
    driver_name: string;
    vehicle_label: string;
  };
  settlement: Settlement;
  visits?: DriverVisits;
  completedVisits?: number;
  pendingVisits?: number;
}

interface CommandCenterProps {
  driver: ActiveDriver | null;
  onApproveSettlement: () => void;
  onUndoEndWork?: () => void;
}

export function CommandCenter({ driver, onApproveSettlement, onUndoEndWork }: CommandCenterProps) {
  const [showInventoryModal, setShowInventoryModal] = useState(false);
  const [inventorySearch, setInventorySearch] = useState(""); 
  
  const canApprove = driver?.settlement?.status === "مغلقة بانتظار التسوية";
  const GLOBAL_CURRENCY = "د.أ";
  const formatMoney = (val: number) => parseFloat(Number(val || 0).toFixed(2)).toLocaleString('en-US');

  // +++ الدرع اللغوي: أخذ الحرف الأول فقط لتجنب كوارث دمج الحروف العربية (مت، سم، دم) +++
  const getInitials = (name: string) => {
    return name ? name.trim().charAt(0).toUpperCase() : "م";
  };

  const filteredInventory = driver?.settlement.inventory.filter(item => 
    item.product_name.toLowerCase().includes(inventorySearch.toLowerCase())
  ) || [];

  return (
    //الكود المسؤول عن لون البطاقة العام bg-white
    <div className="relative bg-[#FBB117] rounded-3xl p-6 md:p-8 shadow-sm border border-slate-200 overflow-hidden flex flex-col gap-5 min-h-[420px]">
      <AnimatePresence mode="wait">
        {!driver ? (
          <motion.div
            key="empty"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="flex-1 flex flex-col items-center justify-center gap-4 relative z-10"
          >
            <div className="w-20 h-20 rounded-full bg-slate-50 flex items-center justify-center mb-2 border border-slate-100">
              <Radar className="w-10 h-10 text-slate-400 animate-spin-slow" strokeWidth={1.5} />
            </div>
            <p className="text-base font-bold text-slate-600">مركز التحكم الميداني</p>
            <p className="text-xs text-slate-400 font-medium text-center">حدد مندوباً من الرادار لإدارة عهدته</p>
          </motion.div>
        ) : (
          <motion.div
            key="active"
            initial={{ opacity: 0, scale: 0.98 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.98 }}
            className="flex flex-col h-full z-10 gap-5"
          >
            {/* 1. Header (المندوب والسيارة) */}
            <div className="flex items-center gap-4">
              <div className="w-12 h-12 rounded-2xl bg-slate-100 text-slate-700 flex items-center justify-center font-black text-lg border border-slate-200">
                {getInitials(driver.session.driver_name)}
              </div>
              <div>
                <h3 className="text-lg font-black text-slate-800 tracking-tight">{driver.session.driver_name}</h3>
                <div className="flex items-center gap-2 mt-1">
                  <span className="text-[10px] font-bold text-slate-500 bg-slate-50 border border-slate-100 px-2 py-0.5 rounded-md">
                    {driver.session.vehicle_label}
                  </span>
                  <span className={`text-[10px] font-bold px-2 py-0.5 rounded-md border ${
                    canApprove ? "bg-amber-50 text-amber-600 border-amber-200" : "bg-emerald-50 text-emerald-600 border-emerald-200"
                  }`}>
                    {driver.settlement.status}
                  </span>
                </div>
              </div>
            </div>

            {/* 2. الأرقام المالية (مدمجة بسطر واحد أنيق وصغير الحجم) */}
            <div className="flex items-center bg-slate-50 rounded-2xl border border-slate-100 p-1 shadow-sm">
              <div className="flex-1 flex flex-col items-center justify-center py-2.5">
                <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-0.5">مبيعات نقدية</span>
                <span className="text-sm font-black text-slate-800">
                  {formatMoney(driver.settlement.financials.cash_from_sales)} <span className="text-[10px] text-slate-500 font-bold">{GLOBAL_CURRENCY}</span>
                </span>
              </div>
              <div className="w-px h-8 bg-slate-200" />
              <div className="flex-1 flex flex-col items-center justify-center py-2.5">
                <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-0.5">تحصيل ذمم</span>
                <span className="text-sm font-black text-slate-800">
                  {formatMoney(driver.settlement.financials.cash_from_debts)} <span className="text-[10px] text-slate-500 font-bold">{GLOBAL_CURRENCY}</span>
                </span>
              </div>
            </div>

            {/* 3. النقد المتوقع (بانر أنيق بارتفاع مناسب للعين) */}
            <div className="bg-emerald-50 border border-emerald-100 rounded-2xl p-4 flex items-center justify-between shadow-sm">
              <div className="flex items-center gap-2.5">
                <div className="w-8 h-8 rounded-xl bg-emerald-100 text-emerald-600 flex items-center justify-center">
                  <Banknote className="w-4 h-4" />
                </div>
                <span className="text-xs font-bold text-emerald-800">إجمالي النقد المتوقع</span>
              </div>
              <div className="text-xl font-black text-emerald-700 tracking-tight">
                {formatMoney(driver.settlement.financials.expected_cash_in_hand)} <span className="text-xs font-bold text-emerald-600/70">{GLOBAL_CURRENCY}</span>
              </div>
            </div>

            {/* 4. نظرة سريعة على الجرد (ترتيب نظيف مع زر حقيقي) */}
            <div className="flex flex-col gap-2">
              <div className="flex items-center justify-between px-1">
                <span className="text-xs font-bold text-slate-500 uppercase tracking-wider flex items-center gap-1.5"><Package className="w-4 h-4"/> نظرة سريعة للجرد</span>
                {/* +++ تم تحويله لزر حقيقي وواضح +++ */}
                <button onClick={() => setShowInventoryModal(true)} className="bg-white border border-slate-200 text-slate-600 hover:bg-slate-50 hover:text-blue-600 px-3 py-1.5 rounded-lg text-[10px] font-bold transition-all shadow-sm flex items-center gap-1.5">
                  <Eye className="w-3 h-3" /> عرض الكل
                </button>
              </div>
              <div className="bg-slate-50 rounded-2xl border border-slate-100 p-3 flex flex-col gap-2">
                {driver.settlement.inventory.slice(0, 2).map(item => {
                  const remC = Math.floor((item.remaining_quantity || 0) / (item.packs_per_carton || 1));
                  const remL = (item.remaining_quantity || 0) % (item.packs_per_carton || 1);
                  return (
                    <div key={item.product_id} className="flex justify-between items-center text-xs border-b border-slate-200/50 pb-2 last:border-0 last:pb-0">
                      <span className="font-bold text-slate-700 truncate max-w-[180px]">{item.product_name}</span>
                      <span className="font-black text-slate-800 bg-white px-2 py-1 rounded-md border border-slate-100 shadow-sm">{remC}ك {remL > 0 ? `+ ${remL}ح` : ''}</span>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* 5. Action Buttons (أزرار بحجم مناسب وألوان متناسقة) */}
            <div className="mt-auto flex flex-col gap-2 pt-2">
              {canApprove && onUndoEndWork && (
                <button
                  onClick={onUndoEndWork}
                  className="w-full flex items-center justify-center gap-2 bg-white text-slate-600 rounded-xl px-4 py-3 text-sm font-bold hover:bg-slate-50 transition-all border border-slate-200 shadow-sm"
                >
                  <RotateCcw className="w-4 h-4" strokeWidth={2.5} /> إعادة فتح الجلسة
                </button>
              )}

              <button
                onClick={onApproveSettlement}
                disabled={!canApprove}
                className={`w-full flex items-center justify-center gap-2 rounded-xl px-4 py-3.5 text-sm font-bold transition-all shadow-sm ${
                  canApprove
                    ? "bg-slate-900 text-white hover:bg-slate-800 active:scale-[0.99] border border-slate-800"
                    : "bg-slate-50 text-slate-400 cursor-not-allowed border border-slate-200"
                }`}
              >
                <CheckCircle2 className="w-5 h-5" strokeWidth={2.5} /> اعتماد التسوية وإغلاق العهدة
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* +++ المودال التفصيلي مع محرك البحث المدمج +++ */}
      {driver && (
        <Modal
          isOpen={showInventoryModal}
          onClose={() => {
            setShowInventoryModal(false);
            setInventorySearch(""); 
          }}
          title={`📦 جرد سيارة: ${driver.session.driver_name}`}
          maxWidth="max-w-2xl"
        >
          <div className="flex flex-col max-h-[75vh] overflow-hidden" dir="rtl">
            
            {/* حقل البحث الثابت في الأعلى */}
            <div className="p-3 bg-white border-b border-slate-100 shrink-0 z-20">
              <div className="relative">
                <Search className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
                <input
                  type="text"
                  placeholder="ابحث عن منتج..."
                  value={inventorySearch}
                  onChange={(e) => setInventorySearch(e.target.value)}
                  className="w-full bg-slate-50 border border-slate-200 rounded-xl py-2.5 pr-10 pl-4 text-sm font-bold text-slate-800 focus:outline-none focus:border-blue-400 focus:ring-1 focus:ring-blue-400 transition-all"
                />
              </div>
            </div>

            <div className="overflow-y-auto custom-scrollbar flex-1 pb-4">
              <div className="grid grid-cols-12 gap-2 p-3 bg-slate-50 border-b border-slate-100 sticky top-0 z-10 text-[10px] font-extrabold text-slate-400 uppercase">
                <div className="col-span-6">المنتج</div>
                <div className="col-span-2 text-center">استلام</div>
                <div className="col-span-2 text-center">مبيع</div>
                <div className="col-span-2 text-center text-emerald-600">باقي</div>
              </div>
              
              {filteredInventory.length === 0 ? (
                <div className="text-center text-slate-400 py-12 flex flex-col items-center gap-2">
                  <Package className="w-12 h-12 opacity-20" />
                  <p className="font-bold">لا توجد منتجات مطابقة للبحث.</p>
                </div>
              ) : (
                filteredInventory.map((item) => {
                  const ppc = item.packs_per_carton || 1;
                  const formatQty = (qty: number) => {
                    const c = Math.floor((qty || 0) / ppc);
                    const l = (qty || 0) % ppc;
                    return `${c}ك ${l > 0 ? `+${l}` : ''}`;
                  };

                  return (
                    <div key={item.product_id} className="grid grid-cols-12 gap-2 p-3 border-b border-slate-50 hover:bg-slate-50/80 items-center transition-colors">
                      <div className="col-span-6 flex flex-col">
                        <span className="text-sm font-black text-slate-700 truncate" title={item.product_name}>{item.product_name}</span>
                        <span className="text-[10px] text-slate-400 font-bold">{ppc} حبة بالكرتونة</span>
                      </div>
                      <div className="col-span-2 text-center text-xs font-bold text-slate-600 bg-slate-100/50 py-1 rounded">
                        {formatQty(item.starting_quantity)}
                      </div>
                      <div className="col-span-2 text-center text-xs font-bold text-blue-600 bg-blue-50/50 py-1 rounded">
                        {formatQty(item.sold_quantity)}
                      </div>
                      <div className="col-span-2 text-center text-xs font-black text-emerald-700 bg-emerald-50/50 py-1 rounded">
                        {formatQty(item.remaining_quantity)}
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
}