import { z } from "zod";

// Data structures matching FastAPI backend exactly

export interface Session {
  session_id: number;
  driver_name: string;
  start_time: string | null;
  is_authorized_to_sell: boolean;
  is_on_break: boolean;
  vehicle_label: string | null;
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
    inventory_shortage_cash: string;
  };
  visits: {
    completed_total: number;
    successful_sales: number;
    pending_remaining: number;
  };
  inventory: InventoryItem[];
}

export const SESSION_STATUS = {
  ACTIVE: "في الطريق",
  ON_BREAK: "استراحة",
  AWAITING_INVENTORY_RECONCILIATION: "مغلقة بانتظار التسوية المخزنية",
  AWAITING_FINANCIAL_SETTLEMENT: "تمت التسوية المخزنية بانتظار المالية",
  SETTLED: "تمت التسوية",
  OFFLINE: "غير متصل",
} as const;

export const FINANCIAL_SETTLEMENT_READY_STATUS =
  SESSION_STATUS.AWAITING_FINANCIAL_SETTLEMENT;

export interface SettlementSampleItem {
  shop_name: string;
  product_name: string;
  sample_quantity_cartons: number;
  sample_quantity_packs: number;
  reason: string | null;
}

export interface SessionSettlementReport extends SettlementReport {
  session_date: string | null;
  samples_given: SettlementSampleItem[];
}

const inventoryItemSchema = z.object({
  product_id: z.number().int().positive(),
  product_name: z.string(),
  starting_quantity: z.number().int(),
  sold_quantity: z.number().int(),
  remaining_quantity: z.number().int(),
  packs_per_carton: z.number().int().positive(),
  starting_cartons: z.number().int(),
  starting_loose_packs: z.number().int(),
  sold_cartons: z.number().int(),
  sold_loose_packs: z.number().int(),
  remaining_cartons: z.number().int(),
  remaining_loose_packs: z.number().int(),
});

const sessionSettlementReportSchema = z.object({
  driver_name: z.string(),
  session_date: z.string().nullable(),
  status: z.string(),
  financials: z.object({
    expected_cash_in_hand: z.string(),
    cash_from_sales: z.string(),
    cash_from_debts: z.string(),
    inventory_shortage_cash: z.string(),
  }),
  visits: z.object({
    completed_total: z.number().int().nonnegative(),
    successful_sales: z.number().int().nonnegative(),
    pending_remaining: z.number().int().nonnegative(),
  }),
  inventory: z.array(inventoryItemSchema),
  samples_given: z.array(z.object({
    shop_name: z.string(),
    product_name: z.string(),
    sample_quantity_cartons: z.number().int().nonnegative(),
    sample_quantity_packs: z.number().int().nonnegative(),
    reason: z.string().nullable(),
  })),
});

export function parseSessionSettlementReport(raw: unknown): SessionSettlementReport {
  const result = sessionSettlementReportSchema.safeParse(raw);
  if (!result.success) {
    throw new Error("استجابة تقرير التسوية لا تطابق عقد الخادم.");
  }
  return result.data as SessionSettlementReport;
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
  const activeDrivers = drivers.filter(
    (d) => d.settlement.status === SESSION_STATUS.ACTIVE && !d.session.is_on_break
  ).length;
  const onBreakDrivers = drivers.filter(
    (d) => d.settlement.status === SESSION_STATUS.ON_BREAK || d.session.is_on_break
  ).length;

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
