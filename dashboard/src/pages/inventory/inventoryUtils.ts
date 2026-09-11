// ============================================================
// Utility Types & Helpers for MainInventory
// ============================================================

export interface WarehouseAlert {
  product_variant_id: number;
  product_name: string;
  current_total_packs: number;
  min_threshold_packs: number;
}

export interface InboundRow {
  product_variant_id: string;
  cartons: number;
  loose_packs: number;
}

export type StocktakeStockStatus = "AVAILABLE" | "DAMAGED";

export interface StocktakeRow {
  row_key: string;
  product_variant_id: number;
  batch_id: number | null;
  stock_status: StocktakeStockStatus;
  product_name: string;
  batch_number: string | null;
  expiry_date: string | null;
  base_uom_id: number;
  base_uom_code: string;
  base_uom_name: string;
  quantity_scale: number;
  quantity_step: string;
  actual_quantity: string;
  counted: boolean;
}

// +++  للكارثة الرياضية (الأرقام السالبة) +++
export function formatQty(packs: number, ppc: number): string {
  if (!ppc || ppc <= 0) ppc = 1;

  const isNegative = packs < 0;
  const absPacks = Math.abs(packs); // العمل على القيم المطلقة فقط لمنع التخريف

  const cartons = Math.floor(absPacks / ppc);
  const loose = absPacks % ppc;

  const sign = isNegative ? "-" : "";

  if (cartons === 0 && loose === 0) return "0 كرتونة";
  if (cartons === 0) return `${sign}${loose} حبة`;
  if (loose === 0) return `${sign}${cartons} كرتونة`;
  return `${sign}${cartons} كرتونة و ${loose} حبة`;
}

// +++ حماية الحسابات من نصوص الإدخال والكسور العائمة +++
export function toTotalPacks(cartons: number, loosePacks: number, ppc: number): number {
  const c = Math.max(0, Math.floor(Number(cartons) || 0));
  const l = Math.max(0, Math.floor(Number(loosePacks) || 0));
  const p = Math.max(1, Math.floor(Number(ppc) || 1));
  return (c * p) + l;
}

export const LEDGER_BADGE: Record<string, { bg: string; text: string; label: string }> = {
  INBOUND_SUPPLIER: { bg: "bg-emerald-100", text: "text-emerald-700", label: "توريد بضاعة" },
  AUDIT_ADJUSTMENT: { bg: "bg-amber-100", text: "text-amber-700", label: "تسوية جرد" },
  DISPATCH_LOAD: { bg: "bg-blue-100", text: "text-blue-700", label: "تحميل سيارة" },
  DISPATCH_UNLOAD: { bg: "bg-rose-100", text: "text-rose-700", label: "تفريغ من سيارة" },
  HANDSHAKE_RESERVE: { bg: "bg-violet-100", text: "text-violet-700", label: "حجز (قيد النقل)" },
  HANDSHAKE_RELEASE: { bg: "bg-rose-100", text: "text-rose-700", label: "رفض المندوب" },
  HANDSHAKE_COMMIT: { bg: "bg-blue-100", text: "text-blue-700", label: "استلام المندوب" },
  HANDSHAKE_COMMIT_PULL: { bg: "bg-rose-100", text: "text-rose-700", label: "استرجاع من مندوب" },
  'Warehouse Return': { bg: "bg-emerald-50 border border-emerald-200", text: "text-emerald-700", label: "إرجاع فراطة صالحة" },
  AUDIT_DISCREPANCY: { bg: "bg-red-600 animate-pulse", text: "text-white", label: "⚠️ تلاعب / عجز" },
  INBOUND_CORRECTION: { bg: "bg-purple-100", text: "text-purple-700", label: "تعديل توريد" },
  DRIVER_SHORTAGE: { bg: "bg-red-100", text: "text-red-700", label: "عجز عهدة مندوب" },
  DRIVER_SURPLUS: { bg: "bg-emerald-100", text: "text-emerald-700", label: "زيادة عهدة مندوب" },
  HANDSHAKE_POST: { bg: "bg-blue-100", text: "text-blue-700", label: "ترحيل مصافحة" },
  VISIT_ITEM_OUT: { bg: "bg-sky-100", text: "text-sky-700", label: "صرف بيع من زيارة" },
  VISIT_EXCHANGE_OUT: { bg: "bg-orange-100", text: "text-orange-700", label: "صرف استبدال من زيارة" },
  VISIT_RETURN_IN: { bg: "bg-rose-100", text: "text-rose-700", label: "مرتجع زيارة" },
  VISIT_REVERSAL: { bg: "bg-slate-200", text: "text-slate-700", label: "عكس حركة زيارة" },
  TRANSFER_DISPATCH: { bg: "bg-indigo-100", text: "text-indigo-700", label: "إرسال حوالة" },
  TRANSFER_RECEIPT: { bg: "bg-emerald-100", text: "text-emerald-700", label: "استلام حوالة" },
  TRANSFER_CANCELLED: { bg: "bg-amber-100", text: "text-amber-700", label: "إلغاء حوالة" },
  TRANSFER_REJECTED: { bg: "bg-red-100", text: "text-red-700", label: "رفض حوالة" },
};

// +++ الدرع الفولاذي لمنع انهيار الواجهة (UI Crash) بسبب أنواع غير معروفة +++
export function getLedgerBadge(type: string) {
  return LEDGER_BADGE[type] || { bg: "bg-slate-100", text: "text-slate-700", label: type || "حركة غير معروفة" };
}
