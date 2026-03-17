// Data structures matching Flask backend exactly

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
  starting_quantity: number;
  sold_quantity: number;
  remaining_quantity: number;
}

export interface SettlementReport {
  driver_name: string;
  status: string; // "نشطة الآن" | "مغلقة بانتظار التسوية" | "في استراحة"
  financials: {
    expected_cash_in_hand: number;
    cash_from_sales: number;
    cash_from_debts: number;
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
  avatar: string;
}


export const systemAlerts = [
  { id: 1, text: "أحمد تجاوز وقت الاستراحة بـ 15 دقيقة", type: "warning" as const },
  { id: 2, text: "سامي - كاش عالي يحتاج تسوية فورية", type: "danger" as const },
  { id: 3, text: "فادي لم يبدأ الجولة بعد", type: "info" as const },
];

// Computed fleet stats
export function getFleetStats(drivers: DriverData[]) {
  const totalCash = drivers.reduce((s, d) => s + d.settlement.financials.expected_cash_in_hand, 0);
  const cashFromSales = drivers.reduce((s, d) => s + d.settlement.financials.cash_from_sales, 0);
  const cashFromDebts = drivers.reduce((s, d) => s + d.settlement.financials.cash_from_debts, 0);
  const totalSoldCartons = drivers.reduce(
    (s, d) => s + d.settlement.inventory.reduce((si, item) => si + item.sold_quantity, 0), 0
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
