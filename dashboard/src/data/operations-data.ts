// Data structures matching FastAPI backend exactly

export interface Session {
  session_id: number;
  driver_name: string;
  start_time: string;
  is_authorized_to_sell: boolean;
  is_on_break: boolean;
}

export interface InventoryItem {
  product_id: number;
  product_name: string;
  // الكميات الإجمالية
  starting_quantity: number;
  sold_quantity: number;
  remaining_quantity: number;
  // التفاصيل (كراتين وحبات)
  packs_per_carton: number;
  starting_cartons: number;
  starting_loose_packs: number;
  sold_cartons: number;
  sold_loose_packs: number;
  remaining_cartons: number;
  remaining_loose_packs: number;
}

export interface SettlementReport {
  driver_name: string;
  status: string;
  financials: {
    expected_cash_in_hand: string; // تم التعديل إلى نص لتطابق الخادم
    cash_from_sales: string;       // تم التعديل إلى نص لتطابق الخادم
    cash_from_debts: string;       // تم التعديل إلى نص لتطابق الخادم
  };
  visits: {
    completed_total: number;
    successful_sales: number;
    pending_remaining: number;
  };
  inventory: InventoryItem[];
}

export interface DriverData {
  session: Session;
  settlement: SettlementReport;
  avatar?: string; // اختياري لأنه لا يأتي من الخادم حالياً
}

export const systemAlerts = [
  { id: 1, text: "أحمد تجاوز وقت الاستراحة بـ 15 دقيقة", type: "warning" as const },
  { id: 2, text: "سامي - كاش عالي يحتاج تسوية فورية", type: "danger" as const },
  { id: 3, text: "فادي لم يبدأ الجولة بعد", type: "info" as const },
];

// Computed fleet stats
export function getFleetStats(drivers: DriverData[]) {
  // استخدام parseFloat لتحويل النصوص القادمة من الخادم إلى أرقام للعمليات الحسابية
  const totalCash = drivers.reduce((s, d) => s + parseFloat(d.settlement.financials.expected_cash_in_hand || "0"), 0);
  const cashFromSales = drivers.reduce((s, d) => s + parseFloat(d.settlement.financials.cash_from_sales || "0"), 0);
  const cashFromDebts = drivers.reduce((s, d) => s + parseFloat(d.settlement.financials.cash_from_debts || "0"), 0);
  
  // +++ الكي الجراحي: جمع الكراتين الصافية فقط بدلاً من إجمالي الحبات لحساب الإحصائيات بدقة +++
  const totalSoldCartons = drivers.reduce(
    (s, d) => s + d.settlement.inventory.reduce((si, item) => si + (item.sold_cartons || 0), 0), 0
  );
  
  const completedVisits = drivers.reduce((s, d) => s + d.settlement.visits.completed_total, 0);
  const pendingVisits = drivers.reduce((s, d) => s + d.settlement.visits.pending_remaining, 0);
  const activeDrivers = drivers.filter((d) => d.settlement.status !== "غير متصل" && d.settlement.status !== "مغلقة بانتظار التسوية" && !d.session.is_on_break).length;
  const onBreakDrivers = drivers.filter((d) => d.settlement.status !== "غير متصل" && d.session.is_on_break).length;

  return {
    totalCash,
    cashFromSales,
    cashFromDebts,
    totalSoldCartons,
    completedVisits,
    pendingVisits,
    totalVisits: completedVisits + pendingVisits,
    activeDrivers,
    onBreakDrivers,
    totalDrivers: drivers.length,
  };
}