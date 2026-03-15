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
  starting_cartons: number;
  sold_cartons: number;
  remaining_cartons: number;
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

export const driversData: DriverData[] = [
  {
    session: {
      session_id: 1,
      driver_name: "أحمد خليل",
      start_time: "06:30",
      is_authorized_to_sell: true,
      is_on_break: false,
    },
    settlement: {
      driver_name: "أحمد خليل",
      status: "نشطة الآن",
      financials: { expected_cash_in_hand: 350, cash_from_sales: 300, cash_from_debts: 50 },
      visits: { completed_total: 18, successful_sales: 15, pending_remaining: 4 },
      inventory: [
        { product_id: 1, product_name: "حليب كامل 1L", starting_cartons: 20, sold_cartons: 16, remaining_cartons: 4 },
        { product_id: 2, product_name: "لبن طازج 500ml", starting_cartons: 15, sold_cartons: 12, remaining_cartons: 3 },
        { product_id: 3, product_name: "جبنة بيضاء 400g", starting_cartons: 15, sold_cartons: 12, remaining_cartons: 3 },
      ],
    },
    avatar: "أخ",
  },
  {
    session: {
      session_id: 2,
      driver_name: "عمر حداد",
      start_time: "07:00",
      is_authorized_to_sell: true,
      is_on_break: false,
    },
    settlement: {
      driver_name: "عمر حداد",
      status: "نشطة الآن",
      financials: { expected_cash_in_hand: 275.5, cash_from_sales: 225.5, cash_from_debts: 50 },
      visits: { completed_total: 14, successful_sales: 11, pending_remaining: 8 },
      inventory: [
        { product_id: 1, product_name: "حليب كامل 1L", starting_cartons: 18, sold_cartons: 10, remaining_cartons: 8 },
        { product_id: 2, product_name: "لبن طازج 500ml", starting_cartons: 16, sold_cartons: 12, remaining_cartons: 4 },
        { product_id: 3, product_name: "جبنة بيضاء 400g", starting_cartons: 16, sold_cartons: 10, remaining_cartons: 6 },
      ],
    },
    avatar: "عح",
  },
  {
    session: {
      session_id: 3,
      driver_name: "سامي ناصر",
      start_time: "05:45",
      is_authorized_to_sell: false,
      is_on_break: false,
    },
    settlement: {
      driver_name: "سامي ناصر",
      status: "مغلقة بانتظار التسوية",
      financials: { expected_cash_in_hand: 490, cash_from_sales: 420, cash_from_debts: 70 },
      visits: { completed_total: 22, successful_sales: 20, pending_remaining: 0 },
      inventory: [
        { product_id: 1, product_name: "حليب كامل 1L", starting_cartons: 20, sold_cartons: 19, remaining_cartons: 1 },
        { product_id: 2, product_name: "لبن طازج 500ml", starting_cartons: 15, sold_cartons: 15, remaining_cartons: 0 },
        { product_id: 3, product_name: "جبنة بيضاء 400g", starting_cartons: 15, sold_cartons: 14, remaining_cartons: 1 },
      ],
    },
    avatar: "سن",
  },
  {
    session: {
      session_id: 4,
      driver_name: "فادي منصور",
      start_time: "08:00",
      is_authorized_to_sell: false,
      is_on_break: true,
    },
    settlement: {
      driver_name: "فادي منصور",
      status: "في استراحة",
      financials: { expected_cash_in_hand: 120, cash_from_sales: 95, cash_from_debts: 25 },
      visits: { completed_total: 7, successful_sales: 5, pending_remaining: 15 },
      inventory: [
        { product_id: 1, product_name: "حليب كامل 1L", starting_cartons: 18, sold_cartons: 6, remaining_cartons: 12 },
        { product_id: 2, product_name: "لبن طازج 500ml", starting_cartons: 16, sold_cartons: 5, remaining_cartons: 11 },
        { product_id: 3, product_name: "جبنة بيضاء 400g", starting_cartons: 16, sold_cartons: 4, remaining_cartons: 12 },
      ],
    },
    avatar: "فم",
  },
  {
    session: {
      session_id: 5,
      driver_name: "رامي يوسف",
      start_time: "06:15",
      is_authorized_to_sell: true,
      is_on_break: false,
    },
    settlement: {
      driver_name: "رامي يوسف",
      status: "نشطة الآن",
      financials: { expected_cash_in_hand: 410.25, cash_from_sales: 350.25, cash_from_debts: 60 },
      visits: { completed_total: 16, successful_sales: 14, pending_remaining: 6 },
      inventory: [
        { product_id: 1, product_name: "حليب كامل 1L", starting_cartons: 20, sold_cartons: 14, remaining_cartons: 6 },
        { product_id: 2, product_name: "لبن طازج 500ml", starting_cartons: 15, sold_cartons: 12, remaining_cartons: 3 },
        { product_id: 3, product_name: "جبنة بيضاء 400g", starting_cartons: 15, sold_cartons: 12, remaining_cartons: 3 },
      ],
    },
    avatar: "ري",
  },
];

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
    (s, d) => s + d.settlement.inventory.reduce((si, item) => si + item.sold_cartons, 0), 0
  );
  const completedVisits = drivers.reduce((s, d) => s + d.settlement.visits.completed_total, 0);
  const pendingVisits = drivers.reduce((s, d) => s + d.settlement.visits.pending_remaining, 0);
  const activeDrivers = drivers.filter((d) => !d.session.is_on_break).length;
  const onBreakDrivers = drivers.filter((d) => d.session.is_on_break).length;

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
