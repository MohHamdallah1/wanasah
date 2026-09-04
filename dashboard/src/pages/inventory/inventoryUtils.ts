// ============================================================
// Utility Types & Helpers for MainInventory
// ============================================================

export interface WarehouseProduct {
  id: number;
  name: string;
  sku: string;
  packs_per_carton: number;
  available_packs: number;
  reserved_packs: number;
  total_packs: number;
  damaged_packs: number; // +++ حقل التوالف الرسمي +++
  available_cartons: number;
  available_loose_packs: number;
  min_threshold: number;
}

export interface WarehouseAlert {
  product_variant_id: number;
  product_name: string;
  current_total_packs: number;
  min_threshold_packs: number;
}

export interface LedgerEntry {
  id: number;
  product_name: string;
  packs_per_carton: number;
  type: string;
  quantity_packs: number;
  balance_before: number; // +++ الحقل الجديد +++
  balance_after: number;
  admin_name: string;
  reference: string;
  notes: string;
  date: string;
}

export interface InboundRow {
  product_variant_id: string;
  cartons: number;
  loose_packs: number;
}

export interface StocktakeRow {
  row_key: string;
  product_variant_id: number;
  batch_id: number | null;
  product_name: string;
  batch_number: string | null;
  expiry_date: string | null;
  packs_per_carton: number;
  actual_cartons: number;
  actual_loose_packs: number;
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
};

// +++ الدرع الفولاذي لمنع انهيار الواجهة (UI Crash) بسبب أنواع غير معروفة +++
export function getLedgerBadge(type: string) {
  return LEDGER_BADGE[type] || { bg: "bg-slate-100", text: "text-slate-700", label: type || "حركة غير معروفة" };
}